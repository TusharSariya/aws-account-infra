#!/usr/bin/env python3
"""Render and reconcile Ansible-owned Kubernetes tenant safety resources."""

from __future__ import annotations

import argparse
import fcntl
import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
CATALOG_SCRIPT = ROOT / "scripts" / "service-catalog.py"
DEFAULT_OUTPUT_DIR = ROOT / "ansible" / "roles" / "kubernetes_tenants" / "files"
LOCK_PATH = Path("/tmp/aws-account-infra-kubernetes-vending.lock")
MANAGED_LABEL = "platform.homelab.tfdraw.dev/managed"
ACTIVE_LABEL = "platform.homelab.tfdraw.dev/active-tenant"
CPU_QUANTITY = re.compile(r"^(?P<number>[0-9]+(?:\.[0-9]+)?)(?P<unit>n|u|m)?$")
BYTE_QUANTITY = re.compile(r"^(?P<number>[0-9]+(?:\.[0-9]+)?)(?P<unit>Ki|Mi|Gi|Ti|K|M|G|T)?$")

SPEC = importlib.util.spec_from_file_location("service_catalog", CATALOG_SCRIPT)
service_catalog = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(service_catalog)


class ReconcilePending(RuntimeError):
    """The cluster cannot currently prove that reconciliation is safe."""


class IndentedSafeDumper(yaml.SafeDumper):
    """Emit block sequences at the indentation expected by ansible-lint."""

    def increase_indent(self, flow: bool = False, indentless: bool = False):
        return super().increase_indent(flow, indentless=False)


def metadata(name: str, namespace: str | None = None, labels: dict | None = None) -> dict:
    value = {"name": name, "labels": {MANAGED_LABEL: "true", **(labels or {})}}
    if namespace:
        value["namespace"] = namespace
    return value


def global_resources(target: str) -> list[dict]:
    tenant_selector = {"matchLabels": {MANAGED_LABEL: "true"}}
    admin = "'system:masters' in request.userInfo.groups"
    workload_kinds = ["Pod", "Deployment", "StatefulSet", "ReplicaSet", "Job", "CronJob"]
    return [
        {
            "apiVersion": "argoproj.io/v1alpha1",
            "kind": "AppProject",
            "metadata": metadata("default", "argocd"),
            "spec": {
                "sourceRepos": [],
                "destinations": [],
                "clusterResourceWhitelist": [],
                "namespaceResourceWhitelist": [],
            },
        },
        {
            "apiVersion": "admissionregistration.k8s.io/v1",
            "kind": "ValidatingAdmissionPolicy",
            "metadata": metadata("vended-tenant-baseline"),
            "spec": {
                "failurePolicy": "Fail",
                "matchConstraints": {
                    "resourceRules": [{
                        "apiGroups": ["*"],
                        "apiVersions": ["*"],
                        "operations": ["CREATE", "UPDATE"],
                        "resources": ["*", "*/*"],
                        "scope": "Namespaced",
                    }]
                },
                "validations": [
                    {
                        "expression": admin + " || request.kind.kind in " + json.dumps([
                            "Pod", "Deployment", "StatefulSet", "ReplicaSet", "Job", "CronJob",
                            "ConfigMap", "Service", "ServiceAccount", "HorizontalPodAutoscaler", "ScaledObject",
                        ]).replace('"', "'"),
                        "message": "kind is platform-owned or prohibited in vended namespaces",
                    },
                    {
                        "expression": admin + " || request.kind.kind != 'Service' || (object.spec.type == 'ClusterIP' && !has(object.spec.externalIPs))",
                        "message": "Services must be ClusterIP without externalIPs; ExternalName is prohibited",
                    },
                    {
                        "expression": admin + " || !(request.kind.kind in " + json.dumps(workload_kinds).replace('"', "'") + ") || (request.kind.kind == 'Pod' ? ((!has(object.spec.hostNetwork) || !object.spec.hostNetwork) && (!has(object.spec.hostPID) || !object.spec.hostPID) && (!has(object.spec.hostIPC) || !object.spec.hostIPC)) : (request.kind.kind == 'CronJob' ? ((!has(object.spec.jobTemplate.spec.template.spec.hostNetwork) || !object.spec.jobTemplate.spec.template.spec.hostNetwork) && (!has(object.spec.jobTemplate.spec.template.spec.hostPID) || !object.spec.jobTemplate.spec.template.spec.hostPID) && (!has(object.spec.jobTemplate.spec.template.spec.hostIPC) || !object.spec.jobTemplate.spec.template.spec.hostIPC)) : ((!has(object.spec.template.spec.hostNetwork) || !object.spec.template.spec.hostNetwork) && (!has(object.spec.template.spec.hostPID) || !object.spec.template.spec.hostPID) && (!has(object.spec.template.spec.hostIPC) || !object.spec.template.spec.hostIPC))))",
                        "message": "host network, PID and IPC access are prohibited",
                    },
                    {
                        "expression": admin + " || !(request.kind.kind in ['Deployment', 'StatefulSet', 'ReplicaSet']) || !has(object.spec.replicas) || object.spec.replicas <= 3",
                        "message": "controller replicas may not exceed 3",
                    },
                    {
                        "expression": admin + " || request.kind.kind != 'Pod' || (object.spec.containers.all(c, has(c.resources.requests.cpu) && has(c.resources.requests.memory) && has(c.resources.requests['ephemeral-storage']) && has(c.resources.limits.cpu) && has(c.resources.limits.memory) && has(c.resources.limits['ephemeral-storage'])) && (!has(object.spec.initContainers) || object.spec.initContainers.all(c, has(c.resources.requests.cpu) && has(c.resources.requests.memory) && has(c.resources.requests['ephemeral-storage']) && has(c.resources.limits.cpu) && has(c.resources.limits.memory) && has(c.resources.limits['ephemeral-storage']))))",
                        "message": "every container must declare CPU, memory and ephemeral-storage requests and limits",
                    },
                    {
                        "expression": admin + " || !(request.kind.kind in ['Deployment', 'StatefulSet', 'ReplicaSet', 'Job']) || (object.spec.template.spec.containers.all(c, has(c.resources.requests.cpu) && has(c.resources.requests.memory) && has(c.resources.requests['ephemeral-storage']) && has(c.resources.limits.cpu) && has(c.resources.limits.memory) && has(c.resources.limits['ephemeral-storage'])) && (!has(object.spec.template.spec.initContainers) || object.spec.template.spec.initContainers.all(c, has(c.resources.requests.cpu) && has(c.resources.requests.memory) && has(c.resources.requests['ephemeral-storage']) && has(c.resources.limits.cpu) && has(c.resources.limits.memory) && has(c.resources.limits['ephemeral-storage']))))",
                        "message": "every workload container must declare CPU, memory and ephemeral-storage requests and limits",
                    },
                    {
                        "expression": admin + " || request.kind.kind != 'CronJob' || (object.spec.jobTemplate.spec.template.spec.containers.all(c, has(c.resources.requests.cpu) && has(c.resources.requests.memory) && has(c.resources.requests['ephemeral-storage']) && has(c.resources.limits.cpu) && has(c.resources.limits.memory) && has(c.resources.limits['ephemeral-storage'])) && (!has(object.spec.jobTemplate.spec.template.spec.initContainers) || object.spec.jobTemplate.spec.template.spec.initContainers.all(c, has(c.resources.requests.cpu) && has(c.resources.requests.memory) && has(c.resources.requests['ephemeral-storage']) && has(c.resources.limits.cpu) && has(c.resources.limits.memory) && has(c.resources.limits['ephemeral-storage']))))",
                        "message": "every CronJob container must declare CPU, memory and ephemeral-storage requests and limits",
                    },
                    {
                        "expression": admin + " || !(request.kind.kind in " + json.dumps(workload_kinds).replace('"', "'") + ") || (request.kind.kind == 'Pod' ? (!has(object.spec.volumes) || object.spec.volumes.all(v, !has(v.hostPath) && (!has(v.emptyDir) || has(v.emptyDir.sizeLimit)))) : (request.kind.kind == 'CronJob' ? (!has(object.spec.jobTemplate.spec.template.spec.volumes) || object.spec.jobTemplate.spec.template.spec.volumes.all(v, !has(v.hostPath) && (!has(v.emptyDir) || has(v.emptyDir.sizeLimit)))) : (!has(object.spec.template.spec.volumes) || object.spec.template.spec.volumes.all(v, !has(v.hostPath) && (!has(v.emptyDir) || has(v.emptyDir.sizeLimit))))))",
                        "message": "hostPath is prohibited and emptyDir requires sizeLimit",
                    },
                    {
                        "expression": admin + " || !(request.kind.kind in " + json.dumps(workload_kinds).replace('"', "'") + ") || (request.kind.kind == 'Pod' ? (!has(object.spec.priorityClassName) || object.spec.priorityClassName == 'tenant-normal') : (request.kind.kind == 'CronJob' ? (!has(object.spec.jobTemplate.spec.template.spec.priorityClassName) || object.spec.jobTemplate.spec.template.spec.priorityClassName == 'tenant-normal') : (!has(object.spec.template.spec.priorityClassName) || object.spec.template.spec.priorityClassName == 'tenant-normal')))",
                        "message": "platform priority classes are prohibited",
                    },
                    {
                        "expression": admin + " || request.kind.kind != 'Job' || (has(object.spec.ttlSecondsAfterFinished) && object.spec.ttlSecondsAfterFinished <= 86400)",
                        "message": "Jobs require ttlSecondsAfterFinished no greater than one day",
                    },
                    {
                        "expression": admin + " || request.kind.kind != 'CronJob' || (has(object.spec.successfulJobsHistoryLimit) && object.spec.successfulJobsHistoryLimit <= 3 && has(object.spec.failedJobsHistoryLimit) && object.spec.failedJobsHistoryLimit <= 3 && has(object.spec.jobTemplate.spec.ttlSecondsAfterFinished) && object.spec.jobTemplate.spec.ttlSecondsAfterFinished <= 86400)",
                        "message": "CronJobs require bounded history and Job TTL",
                    },
                    {
                        "expression": admin + " || request.kind.kind != 'ScaledObject' || (object.spec.minReplicaCount >= 0 && object.spec.maxReplicaCount <= 3 && object.spec.minReplicaCount <= object.spec.maxReplicaCount)",
                        "message": "KEDA replica bounds must remain between 0 and 3",
                    },
                ],
            },
        },
        {
            "apiVersion": "admissionregistration.k8s.io/v1",
            "kind": "ValidatingAdmissionPolicyBinding",
            "metadata": metadata("vended-tenant-baseline"),
            "spec": {
                "policyName": "vended-tenant-baseline",
                "validationActions": ["Deny"],
                "matchResources": {"namespaceSelector": tenant_selector},
            },
        },
    ]


def quota_resource(namespace: str, profile: dict) -> dict:
    hard = {
        "requests.cpu": profile["requests_cpu"],
        "limits.cpu": profile["limits_cpu"],
        "requests.memory": profile["requests_memory"],
        "limits.memory": profile["limits_memory"],
        "requests.ephemeral-storage": profile["requests_ephemeral_storage"],
        "limits.ephemeral-storage": profile["limits_ephemeral_storage"],
        "pods": str(profile["pods"]),
        "count/deployments.apps": str(profile["deployments"]),
        "count/statefulsets.apps": str(profile["statefulsets"]),
        "count/replicasets.apps": str(profile["replicasets"]),
        "count/jobs.batch": str(profile["jobs"]),
        "count/cronjobs.batch": str(profile["cronjobs"]),
        "services": str(profile["services"]),
        "configmaps": str(profile["configmaps"]),
        "secrets": str(profile["secrets"]),
        "count/serviceaccounts": str(profile["serviceaccounts"]),
        "count/httproutes.gateway.networking.k8s.io": str(profile["httproutes"]),
        "count/scaledobjects.keda.sh": str(profile["scaledobjects"]),
    }
    return {
        "apiVersion": "v1",
        "kind": "ResourceQuota",
        "metadata": metadata("tenant-quota", namespace),
        "spec": {"hard": hard},
    }


def tenant_resources(service_id: str, service: dict, target_id: str, cluster: dict) -> list[dict]:
    target = service["kubernetes"][target_id]
    lifecycle = target["lifecycle"]
    namespace = f"{service_id}-local"
    profile = cluster["quota_profiles"][target["quota_profile"]]
    labels = {
        "kubernetes.io/metadata.name": namespace,
        "pod-security.kubernetes.io/enforce": "restricted",
        "pod-security.kubernetes.io/enforce-version": "v1.35",
        "pod-security.kubernetes.io/audit": "restricted",
        "pod-security.kubernetes.io/audit-version": "v1.35",
        "pod-security.kubernetes.io/warn": "restricted",
        "pod-security.kubernetes.io/warn-version": "v1.35",
        ACTIVE_LABEL: "true" if lifecycle == "active" else "false",
        "platform.homelab.tfdraw.dev/service-id": service_id,
        "platform.homelab.tfdraw.dev/lifecycle": lifecycle,
    }
    resources = [
        {"apiVersion": "v1", "kind": "Namespace", "metadata": metadata(namespace, labels=labels)},
        quota_resource(namespace, profile),
        {
            "apiVersion": "v1",
            "kind": "LimitRange",
            "metadata": metadata("tenant-bounds", namespace),
            "spec": {"limits": [{
                "type": "Container",
                "min": {"cpu": "10m", "memory": "16Mi", "ephemeral-storage": "16Mi"},
                "max": {"cpu": profile["limits_cpu"], "memory": profile["limits_memory"], "ephemeral-storage": profile["limits_ephemeral_storage"]},
            }]},
        },
        {
            "apiVersion": "v1",
            "kind": "ConfigMap",
            "metadata": metadata("tenant-platform-metadata", namespace),
            "data": {
                "catalog_uid": service["service"]["uid"],
                "service_id": service_id,
                "repository_identity": service["repository"]["identity"],
                "ecr_repository": target["ecr_repository"],
                "hostname": target["ingress_hostname"],
                "lifecycle": lifecycle,
                "runtime_contracts": json.dumps(target["secrets"], sort_keys=True),
            },
        },
        {
            "apiVersion": "networking.k8s.io/v1", "kind": "NetworkPolicy",
            "metadata": metadata("default-deny", namespace),
            "spec": {"podSelector": {}, "policyTypes": ["Ingress", "Egress"]},
        },
        {
            "apiVersion": "networking.k8s.io/v1", "kind": "NetworkPolicy",
            "metadata": metadata("allow-dns", namespace),
            "spec": {
                "podSelector": {}, "policyTypes": ["Egress"],
                "egress": [{"to": [{"namespaceSelector": {"matchLabels": {"kubernetes.io/metadata.name": "kube-system"}}, "podSelector": {"matchLabels": {"k8s-app": "kube-dns"}}}], "ports": [{"protocol": "UDP", "port": 53}, {"protocol": "TCP", "port": 53}]}],
            },
        },
        {
            "apiVersion": "networking.k8s.io/v1", "kind": "NetworkPolicy",
            "metadata": metadata("allow-same-namespace", namespace),
            "spec": {
                "podSelector": {}, "policyTypes": ["Ingress", "Egress"],
                "ingress": [{"from": [{"podSelector": {}}]}],
                "egress": [{"to": [{"podSelector": {}}]}],
            },
        },
        {
            "apiVersion": "networking.k8s.io/v1", "kind": "NetworkPolicy",
            "metadata": metadata("allow-gateway-ingress", namespace),
            "spec": {
                "podSelector": {}, "policyTypes": ["Ingress"],
                "ingress": [{"from": [{"namespaceSelector": {"matchLabels": {"kubernetes.io/metadata.name": "istio-ingress"}}, "podSelector": {"matchLabels": {"gateway.networking.k8s.io/gateway-name": target_id}}}]}],
            },
        },
        {
            "apiVersion": "rbac.authorization.k8s.io/v1", "kind": "Role",
            "metadata": metadata(f"argocd-{service_id}", namespace),
            "rules": [
                {"apiGroups": [""], "resources": ["pods", "configmaps", "services", "serviceaccounts"], "verbs": ["get", "list", "watch", "create", "update", "patch", "delete"]},
                {"apiGroups": ["apps"], "resources": ["deployments", "statefulsets", "replicasets"], "verbs": ["get", "list", "watch", "create", "update", "patch", "delete"]},
                {"apiGroups": ["batch"], "resources": ["jobs", "cronjobs"], "verbs": ["get", "list", "watch", "create", "update", "patch", "delete"]},
                {"apiGroups": ["autoscaling"], "resources": ["horizontalpodautoscalers"], "verbs": ["get", "list", "watch", "create", "update", "patch", "delete"]},
                {"apiGroups": ["keda.sh"], "resources": ["scaledobjects"], "verbs": ["get", "list", "watch", "create", "update", "patch", "delete"]},
            ],
        },
        {
            "apiVersion": "rbac.authorization.k8s.io/v1", "kind": "RoleBinding",
            "metadata": metadata(f"argocd-{service_id}", namespace),
            "subjects": [{"kind": "ServiceAccount", "name": "argocd-application-controller", "namespace": "argocd"}],
            "roleRef": {"apiGroup": "rbac.authorization.k8s.io", "kind": "Role", "name": f"argocd-{service_id}"},
        },
        {
            "apiVersion": "argoproj.io/v1alpha1", "kind": "AppProject",
            "metadata": metadata(service_id, "argocd"),
            "spec": {
                "sourceRepos": [f"https://github.com/{service['repository']['identity']}.git"],
                "destinations": [{"server": "https://kubernetes.default.svc", "namespace": namespace}],
                "clusterResourceWhitelist": [],
                "namespaceResourceWhitelist": [
                    {"group": "", "kind": "ConfigMap"}, {"group": "", "kind": "Service"}, {"group": "", "kind": "ServiceAccount"},
                    {"group": "apps", "kind": "Deployment"}, {"group": "apps", "kind": "StatefulSet"}, {"group": "apps", "kind": "ReplicaSet"},
                    {"group": "batch", "kind": "Job"}, {"group": "batch", "kind": "CronJob"},
                    {"group": "autoscaling", "kind": "HorizontalPodAutoscaler"}, {"group": "keda.sh", "kind": "ScaledObject"},
                ],
            },
        },
    ]
    if lifecycle == "active":
        resources.extend([
            {
                "apiVersion": "gateway.networking.k8s.io/v1", "kind": "HTTPRoute",
                "metadata": metadata(service_id, namespace),
                "spec": {
                    "parentRefs": [{"name": target_id, "namespace": "istio-ingress", "sectionName": "https"}],
                    "hostnames": [target["ingress_hostname"]],
                    "rules": [{"backendRefs": [{"name": target["backend"]["service"], "port": target["backend"]["port"]}]}],
                },
            },
            {
                "apiVersion": "argoproj.io/v1alpha1", "kind": "Application",
                "metadata": metadata(service_id, "argocd"),
                "spec": {
                    "project": service_id,
                    "source": {"repoURL": f"https://github.com/{service['repository']['identity']}.git", "targetRevision": "main", "path": target["source_path"]},
                    "destination": {"server": "https://kubernetes.default.svc", "namespace": namespace},
                    "syncPolicy": {
                        "automated": {"prune": True, "selfHeal": True, "allowEmpty": False},
                        "syncOptions": ["CreateNamespace=false", "PrunePropagationPolicy=foreground", "PruneLast=true"],
                        "retry": {"limit": 5, "backoff": {"duration": "10s", "factor": 2, "maxDuration": "3m"}},
                    },
                },
            },
        ])
        if target["egress"]["dns_names"]:
            resources.append({
                "apiVersion": "cilium.io/v2",
                "kind": "CiliumNetworkPolicy",
                "metadata": metadata("allow-approved-fqdn-egress", namespace),
                "spec": {
                    "endpointSelector": {},
                    "egress": [{
                        "toFQDNs": [
                            {"matchName": hostname}
                            for hostname in sorted(target["egress"]["dns_names"])
                        ],
                        "toPorts": [{"ports": [{"port": "443", "protocol": "TCP"}]}],
                    }],
                },
            })
    return resources


def render_target(target: str, phase: str = "all") -> list[dict]:
    catalog = service_catalog.build_catalog()
    if target not in catalog["kubernetes_clusters"]:
        raise service_catalog.CatalogError(f"unknown Kubernetes target {target!r}")
    resources = global_resources(target)
    cluster = catalog["kubernetes_clusters"][target]
    for service_id, service in sorted(catalog["services"].items()):
        if target in service["kubernetes"]:
            resources.extend(tenant_resources(service_id, service, target, cluster))
    if phase == "all":
        return resources

    def is_argo(resource: dict) -> bool:
        if resource["kind"] in {"Application", "AppProject"}:
            return True
        return (
            resource["kind"] in {"Role", "RoleBinding"}
            and resource["metadata"]["name"].startswith("argocd-")
        )

    return [resource for resource in resources if is_argo(resource) == (phase == "argocd")]


def serialize(resources: list[dict]) -> str:
    return "---\n" + "---\n".join(
        yaml.dump(resource, Dumper=IndentedSafeDumper, sort_keys=False) for resource in resources
    )


def _kubectl(kubeconfig: str, *args: str, stdin: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["kubectl", "--kubeconfig", kubeconfig, *args],
        input=stdin,
        text=True,
        check=True,
        capture_output=True,
    )


def _best_effort_kubectl(kubeconfig: str, *args: str) -> None:
    result = subprocess.run(
        ["kubectl", "--kubeconfig", kubeconfig, *args],
        text=True,
        capture_output=True,
    )
    if result.returncode and not any(
        marker in result.stderr
        for marker in ("No resources found", "the server doesn't have a resource type")
    ):
        raise subprocess.CalledProcessError(
            result.returncode, result.args, output=result.stdout, stderr=result.stderr
        )


def _cpu_millicores(value: str) -> int:
    match = CPU_QUANTITY.fullmatch(value or "0")
    if not match:
        raise ReconcilePending(f"unsupported live CPU quantity {value!r}")
    number = float(match.group("number"))
    return int(number * {None: 1000, "m": 1, "u": 0.001, "n": 0.000001}[match.group("unit")])


def _bytes(value: str) -> int:
    match = BYTE_QUANTITY.fullmatch(value or "0")
    if not match:
        raise ReconcilePending(f"unsupported live storage/memory quantity {value!r}")
    number = float(match.group("number"))
    multiplier = {
        None: 1, "K": 1000, "M": 1000**2, "G": 1000**3, "T": 1000**4,
        "Ki": 1024, "Mi": 1024**2, "Gi": 1024**3, "Ti": 1024**4,
    }[match.group("unit")]
    return int(number * multiplier)


def _normalized(resources: dict) -> dict[str, int]:
    return {
        "requests_cpu": _cpu_millicores(resources.get("requests_cpu", "0")),
        "requests_memory": _bytes(resources.get("requests_memory", "0")),
        "limits_memory": _bytes(resources.get("limits_memory", "0")),
        "requests_ephemeral_storage": _bytes(resources.get("requests_ephemeral_storage", "0")),
        "limits_ephemeral_storage": _bytes(resources.get("limits_ephemeral_storage", "0")),
        "pods": int(resources.get("pods", 0)),
        "physical_storage": _bytes(resources.get("physical_storage", "0")),
    }


def _verify_live_capacity(kubeconfig: str, target: str, catalog: dict) -> None:
    try:
        nodes = json.loads(_kubectl(kubeconfig, "get", "nodes", "-o", "json").stdout)
        pods = json.loads(_kubectl(kubeconfig, "get", "pods", "--all-namespaces", "-o", "json").stdout)
    except (KeyError, TypeError, ValueError, subprocess.CalledProcessError) as exc:
        raise ReconcilePending("live capacity facts unavailable; reconciliation remains pending") from exc
    if not nodes.get("items"):
        raise ReconcilePending("no schedulable node capacity reported; reconciliation remains pending")

    allocatable = {field: 0 for field in service_catalog.CAPACITY_FIELDS}
    for node in nodes["items"]:
        values = node.get("status", {}).get("allocatable", {})
        allocatable["requests_cpu"] += _cpu_millicores(values.get("cpu", "0"))
        allocatable["requests_memory"] += _bytes(values.get("memory", "0"))
        allocatable["limits_memory"] += _bytes(values.get("memory", "0"))
        allocatable["requests_ephemeral_storage"] += _bytes(values.get("ephemeral-storage", "0"))
        allocatable["limits_ephemeral_storage"] += _bytes(values.get("ephemeral-storage", "0"))
        allocatable["pods"] += int(values.get("pods", 0))

    tenant_namespaces = {
        f"{service_id}-local"
        for service_id, service in catalog["services"].items()
        if target in service["kubernetes"]
    }
    measured = {field: 0 for field in service_catalog.CAPACITY_FIELDS}
    for pod in pods.get("items", []):
        if pod.get("metadata", {}).get("namespace") in tenant_namespaces:
            continue
        if pod.get("status", {}).get("phase") in {"Succeeded", "Failed"}:
            continue
        measured["pods"] += 1
        containers = pod.get("spec", {}).get("initContainers", []) + pod.get("spec", {}).get("containers", [])
        for container in containers:
            resources = container.get("resources", {})
            requests = resources.get("requests", {})
            limits = resources.get("limits", {})
            measured["requests_cpu"] += _cpu_millicores(requests.get("cpu", "0"))
            measured["requests_memory"] += _bytes(requests.get("memory", "0"))
            measured["limits_memory"] += _bytes(limits.get("memory", "0"))
            measured["requests_ephemeral_storage"] += _bytes(requests.get("ephemeral-storage", "0"))
            measured["limits_ephemeral_storage"] += _bytes(limits.get("ephemeral-storage", "0"))

    cluster = catalog["kubernetes_clusters"][target]
    basis = cluster["capacity_basis"]
    declared = _normalized(basis["declared_platform_budget"])
    reservations = _normalized(basis["system_reservations"])
    headroom = _normalized(basis["eviction_recovery_headroom"])
    reviewed = _normalized(cluster["capacity"])
    for field in service_catalog.CAPACITY_FIELDS:
        live_budget = allocatable[field] - max(measured[field], declared[field]) - reservations[field] - headroom[field]
        if live_budget < reviewed[field]:
            raise ReconcilePending(
                f"live {field} tenant budget {live_budget} is below reviewed budget "
                f"{reviewed[field]}; reconciliation remains pending"
            )


def reconcile(target: str, kubeconfig: str, argocd_ready: bool) -> None:
    with LOCK_PATH.open("w", encoding="utf-8") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            ready = _kubectl(kubeconfig, "get", "--raw=/readyz").stdout.strip()
        except (OSError, subprocess.CalledProcessError) as exc:
            raise ReconcilePending("Kubernetes API unavailable; reconciliation remains pending") from exc
        if ready != "ok":
            raise ReconcilePending(f"Kubernetes API is degraded ({ready!r}); reconciliation remains pending")

        catalog = service_catalog.build_catalog()
        _verify_live_capacity(kubeconfig, target, catalog)
        desired_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
        payload = serialize(render_target(target, phase="native"))
        _kubectl(kubeconfig, "apply", "--server-side", "--field-manager=ansible-kubernetes-vending", "-f", "-", stdin=payload)
        _kubectl(kubeconfig, "get", "validatingadmissionpolicy", "vended-tenant-baseline")
        if argocd_ready:
            try:
                _kubectl(kubeconfig, "get", "crd", "applications.argoproj.io")
                _kubectl(kubeconfig, "get", "crd", "appprojects.argoproj.io")
                _kubectl(kubeconfig, "wait", "deployment/kyverno-admission-controller", "-n", "kyverno", "--for=condition=Available", "--timeout=5m")
                endpoints = json.loads(
                    _kubectl(kubeconfig, "get", "endpoints", "kyverno-svc", "-n", "kyverno", "-o", "json").stdout
                )
            except (ValueError, subprocess.CalledProcessError) as exc:
                raise ReconcilePending("Argo or Kyverno admission readiness is unproven; reconciliation remains pending") from exc
            if not any(subset.get("addresses") for subset in endpoints.get("subsets", [])):
                raise ReconcilePending("Kyverno admission has no ready endpoint; Argo reconciliation remains pending")
            try:
                _kubectl(kubeconfig, "wait", "deployment/argocd-application-controller", "-n", "argocd", "--for=condition=Available", "--timeout=5m")
            except subprocess.CalledProcessError as exc:
                raise ReconcilePending("Argo controller readiness is unproven; reconciliation remains pending") from exc
            _kubectl(kubeconfig, "apply", "--server-side", "--field-manager=ansible-kubernetes-vending", "-f", "-", stdin=serialize(render_target(target, phase="argocd")))

        for service_id, service in sorted(catalog["services"].items()):
            if target not in service["kubernetes"]:
                continue
            lifecycle = service["kubernetes"][target]["lifecycle"]
            namespace = f"{service_id}-local"
            if lifecycle != "active":
                if argocd_ready:
                    _kubectl(kubeconfig, "delete", "application", service_id, "-n", "argocd", "--cascade=orphan", "--ignore-not-found")
                _kubectl(kubeconfig, "delete", "httproute", service_id, "-n", namespace, "--ignore-not-found")
                _best_effort_kubectl(kubeconfig, "scale", "deployment,statefulset", "--all", "-n", namespace, "--replicas=0")
                _best_effort_kubectl(kubeconfig, "patch", "cronjob", "--all", "-n", namespace, "--type=merge", "-p", '{"spec":{"suspend":true}}')
                _best_effort_kubectl(kubeconfig, "annotate", "scaledobject", "--all", "-n", namespace, "autoscaling.keda.sh/paused=true", "--overwrite")
                for contract in service["kubernetes"][target]["secrets"]:
                    _kubectl(kubeconfig, "delete", "secret", contract["name"], "-n", namespace, "--ignore-not-found")

        capacity_released = {}
        for service_id, service in sorted(catalog["services"].items()):
            if target not in service["kubernetes"]:
                continue
            lifecycle = service["kubernetes"][target]["lifecycle"]
            if lifecycle == "active":
                capacity_released[service_id] = False
                continue
            pods = json.loads(_kubectl(kubeconfig, "get", "pods", "-n", f"{service_id}-local", "-o", "json").stdout)
            capacity_released[service_id] = not any(
                pod.get("status", {}).get("phase") not in {"Succeeded", "Failed"}
                for pod in pods.get("items", [])
            )

        state = {
            "apiVersion": "v1", "kind": "ConfigMap",
            "metadata": {"name": "tenant-catalog-state", "namespace": "kube-system", "labels": {MANAGED_LABEL: "true"}},
            "data": {
                "desired_catalog_sha": desired_sha,
                "applied_catalog_sha": desired_sha,
                "target": target,
                "capacity_released": json.dumps(capacity_released, separators=(",", ":"), sort_keys=True),
            },
        }
        _kubectl(kubeconfig, "apply", "--server-side", "--field-manager=ansible-kubernetes-vending", "-f", "-", stdin=yaml.safe_dump(state, sort_keys=False))


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    render_parser = subparsers.add_parser("render")
    render_parser.add_argument("--target", default="homelab")
    render_parser.add_argument("--phase", choices=("native", "argocd", "all"), default="all")
    render_parser.add_argument("--output", type=Path)
    validate_parser = subparsers.add_parser("validate")
    validate_parser.add_argument("--target", default="homelab")
    validate_parser.add_argument("--phase", choices=("native", "argocd", "all"), default="all")
    validate_parser.add_argument("--output", type=Path)
    reconcile_parser = subparsers.add_parser("reconcile")
    reconcile_parser.add_argument("--target", default="homelab")
    reconcile_parser.add_argument("--kubeconfig", required=True)
    reconcile_parser.add_argument("--argocd-ready", action="store_true")
    args = parser.parse_args()
    try:
        if args.command == "reconcile":
            reconcile(args.target, args.kubeconfig, args.argocd_ready)
            return 0
        output = args.output or DEFAULT_OUTPUT_DIR / f"{args.target}-{args.phase}.yaml"
        payload = serialize(render_target(args.target, phase=args.phase))
        if args.command == "validate":
            if not output.exists() or output.read_text(encoding="utf-8") != payload:
                print(f"{output} is stale; run scripts/kubernetes-vending.py render --phase {args.phase}", file=sys.stderr)
                return 1
        else:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(payload, encoding="utf-8")
        return 0
    except (service_catalog.CatalogError, ReconcilePending, subprocess.CalledProcessError) as exc:
        print(exc, file=sys.stderr)
        return 2 if isinstance(exc, ReconcilePending) else 1


if __name__ == "__main__":
    raise SystemExit(main())
