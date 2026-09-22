#!/usr/bin/env python3
"""Use with Helm --post-renderer to preserve main-cluster placement on upgrades."""

import argparse
import copy
import os
import sys

import yaml
from plan import patch_for

parser = argparse.ArgumentParser()
parser.add_argument("--namespace", default=os.environ.get("MAIN_HELM_NAMESPACE"))
args = parser.parse_args()
# Helm charts can include empty or comment-only documents for disabled templates.
# Emitting those as "--- null" is rejected by Kubernetes' YAML document reader.
objects = [obj for obj in yaml.safe_load_all(sys.stdin) if obj is not None]
for obj in objects:
    if not obj or "spec" not in obj:
        continue
    if obj["kind"] in {
        "Deployment",
        "StatefulSet",
        "CronJob",
        "Cluster",
        "AutoscalingRunnerSet",
        "WorkflowTemplate",
        "Service",
        "Ingress",
    } and not obj["metadata"].get("namespace"):
        namespace = args.namespace
        if not namespace:
            raise SystemExit(
                "Set MAIN_HELM_NAMESPACE to the Helm release namespace; refusing to silently skip placement"
            )
        obj["metadata"]["namespace"] = namespace
    probe = copy.deepcopy(obj)
    probe["metadata"]["uid"] = "render-only"
    patch = patch_for(probe)
    if patch:
        obj["spec"] = patch[-1]["value"]
    meta = obj["metadata"]
    ns, name = meta.get("namespace"), meta["name"]
    if (obj["kind"], ns, name) in {
        ("Service", "homelab-services", "pihole-dns"),
        ("Ingress", "homelab-services", "pihole"),
        ("Ingress", "homelab-jobs", "argo"),
        ("Ingress", "homelab-platform", "ai-lifecycle"),
        ("Ingress", "homelab-models", "ollama"),
        ("Ingress", "homelab-models", "odysseus"),
    }:
        meta.setdefault("annotations", {})["tailscale.com/proxy-class"] = (
            "primary-applications"
        )
yaml.safe_dump_all(objects, sys.stdout, sort_keys=False)
