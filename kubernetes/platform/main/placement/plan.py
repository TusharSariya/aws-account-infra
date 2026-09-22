#!/usr/bin/env python3
"""Prepare reversible, UID-guarded placement patches from a private live inventory.
No changes occur without --apply. Never patches existing claims, PVs or AI workloads.
"""

import argparse
import copy
import json
import os
import subprocess
from pathlib import Path

PRIMARY = {"homelab.tfdraw.dev/worker-role": "primary"}
STORAGE = {"homelab.tfdraw.dev/storage": "local-primary"}
ESSENTIAL = {"coredns", "cilium-operator"}
ALWAYS_ON = {
    "homelab-services": {"pihole"},
    "arc-systems": {"arc-gha-rs-controller"},
    "homelab-jobs": {"argo-workflows-server", "argo-workflows-workflow-controller"},
    "homelab-platform": {"ai-lifecycle"},
    "kueue-system": {"kueue-controller-manager"},
    "tailscale": {"operator"},
}


def control_plane(pod):
    selector = pod.setdefault("nodeSelector", {})
    for key in (
        "kubernetes.io/hostname",
        "homelab.tfdraw.dev/worker-role",
        "homelab.tfdraw.dev/storage",
    ):
        selector.pop(key, None)
    selector["node-role.kubernetes.io/control-plane"] = ""
    tol = {
        "key": "node-role.kubernetes.io/control-plane",
        "operator": "Exists",
        "effect": "NoSchedule",
    }
    if tol not in pod.setdefault("tolerations", []):
        pod["tolerations"].append(tol)


DEPLOYMENTS = {
    "arc-systems": {"arc-gha-rs-controller"},
    "cnpg-system": {"cnpg"},
    "homelab-cache": {"nexus", "nexus-postgres"},
    "homelab-jobs": {"argo-workflows-server", "argo-workflows-workflow-controller"},
    "homelab-platform": {"guest-capacity", "physical-capacity", "ai-lifecycle"},
    "homelab-services": {"pihole"},
    "kueue-system": {"kueue-controller-manager"},
    "local-path-storage": {"local-path-provisioner"},
    "tailscale": {"operator"},
}


def required_storage(spec):
    affinity = spec.setdefault("affinity", {}).setdefault("nodeAffinity", {})
    terms = affinity.setdefault(
        "requiredDuringSchedulingIgnoredDuringExecution", {}
    ).setdefault("nodeSelectorTerms", [{}])
    for term in terms:
        expr = {
            "key": "homelab.tfdraw.dev/storage",
            "operator": "In",
            "values": ["local-primary"],
        }
        expressions = term.setdefault("matchExpressions", [])
        if expr not in expressions:
            expressions.append(expr)


def patch_for(obj):
    ns = obj["metadata"].get("namespace")
    name = obj["metadata"]["name"]
    kind = obj["kind"]
    new = copy.deepcopy(obj["spec"])
    if kind == "Deployment":
        pod = new["template"]["spec"]
        if (ns == "kube-system" and name in ESSENTIAL) or name in ALWAYS_ON.get(
            ns, set()
        ):
            control_plane(pod)
        elif name in DEPLOYMENTS.get(ns, set()):
            pod.setdefault("nodeSelector", {}).update(PRIMARY)
            if ns in {"homelab-cache", "homelab-services", "local-path-storage"}:
                required_storage(pod)
        else:
            return None
    elif kind == "CronJob" and ns in {"homelab-cache", "homelab-data"}:
        job_pod = new["jobTemplate"]["spec"]["template"]["spec"]
        job_pod.setdefault("nodeSelector", {}).update(PRIMARY)
        if any(
            "persistentVolumeClaim" in v or "ephemeral" in v
            for v in job_pod.get("volumes", [])
        ):
            required_storage(job_pod)
    elif kind == "Cluster" and ns == "homelab-data" and name == "apps-db":
        new.setdefault("affinity", {}).setdefault("nodeSelector", {}).update(
            PRIMARY | STORAGE
        )
    elif (
        kind == "WorkflowTemplate"
        and ns == "homelab-jobs"
        and name in {"smoke", "independent-smoke"}
    ):
        new.setdefault("nodeSelector", {})["homelab.tfdraw.dev/stateless-compute"] = (
            "true"
        )
        preference = {
            "weight": 100,
            "preference": {
                "matchExpressions": [
                    {
                        "key": "homelab.tfdraw.dev/worker-role",
                        "operator": "In",
                        "values": ["primary"],
                    }
                ]
            },
        }
        prefs = (
            new.setdefault("affinity", {})
            .setdefault("nodeAffinity", {})
            .setdefault("preferredDuringSchedulingIgnoredDuringExecution", [])
        )
        if preference not in prefs:
            prefs.append(preference)
    elif kind == "AutoscalingRunnerSet" and ns == "arc-runners":
        # Controller-owned listener template, not ephemeral listener Pod patches.
        control_plane(new.setdefault("listenerTemplate", {}).setdefault("spec", {}))
        pod = new["template"]["spec"]
        # Keep PVC-using runners pinned; local ephemeral claims also count.
        if any(
            "persistentVolumeClaim" in v or "ephemeral" in v
            for v in pod.get("volumes", [])
        ):
            pod.setdefault("nodeSelector", {}).update(PRIMARY | STORAGE)
        else:
            pod.setdefault("nodeSelector", {}).pop("kubernetes.io/hostname", None)
            pod["nodeSelector"].pop("homelab.tfdraw.dev/worker-role", None)
            pod["nodeSelector"]["homelab.tfdraw.dev/stateless-compute"] = "true"
            pref = (
                pod.setdefault("affinity", {})
                .setdefault("nodeAffinity", {})
                .setdefault("preferredDuringSchedulingIgnoredDuringExecution", [])
            )
            preference = {
                "weight": 100,
                "preference": {
                    "matchExpressions": [
                        {
                            "key": "homelab.tfdraw.dev/worker-role",
                            "operator": "In",
                            "values": ["primary"],
                        }
                    ]
                },
            }
            if preference not in pref:
                pref.append(preference)
    else:
        return None
    if new == obj["spec"]:
        return None
    return [
        {"op": "test", "path": "/metadata/uid", "value": obj["metadata"]["uid"]},
        {
            "op": "test",
            "path": "/spec",
            "value": obj["spec"],
        },
        {"op": "replace", "path": "/spec", "value": new},
    ]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--kubeconfig", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    os.umask(0o077)
    args.output.mkdir(mode=0o700, parents=True, exist_ok=False)
    k = [
        os.environ.get("KUBECTL", "kubectl"),
        "--kubeconfig",
        args.kubeconfig,
        "--server=https://10.0.0.231:6443",
        "--request-timeout=30s",
    ]
    records = []
    for resource in [
        "deployments",
        "cronjobs",
        "clusters.postgresql.cnpg.io",
        "autoscalingrunnersets.actions.github.com",
        "workflowtemplates.argoproj.io",
    ]:
        items = json.loads(
            subprocess.check_output(k + ["get", resource, "-A", "-o", "json"])
        )["items"]
        for obj in items:
            patch = patch_for(obj)
            if patch:
                m = obj["metadata"]
                record = {
                    "resource": resource,
                    "namespace": m["namespace"],
                    "name": m["name"],
                    "before": obj,
                    "patch": patch,
                }
                records.append(record)
    (args.output / "plan.json").write_text(json.dumps(records, indent=2) + "\n")
    for record in records:
        cmd = k + [
            "-n",
            record["namespace"],
            "patch",
            record["resource"],
            record["name"],
            "--type=json",
            "-p",
            json.dumps(record["patch"]),
        ]
        subprocess.run(cmd + ["--dry-run=server"], check=True)
    if args.apply:
        for record in records:
            subprocess.run(
                k
                + [
                    "-n",
                    record["namespace"],
                    "patch",
                    record["resource"],
                    record["name"],
                    "--type=json",
                    "-p",
                    json.dumps(record["patch"]),
                ],
                check=True,
            )
    print(f"{len(records)} placement patches; originals retained at {args.output}")


if __name__ == "__main__":
    main()
