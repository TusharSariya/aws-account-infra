"""Deterministic main-cluster manifests. No host identities or credentials."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
NS = "monitoring"
SIZES = {
    "prometheus": "10Gi",
    "loki": "10Gi",
    "grafana": "2Gi",
    "alloy": "1Gi",
    "alertmanager": "1Gi",
}
PORTS = {
    "prometheus": 9090,
    "loki": 3100,
    "grafana": 3000,
    "alloy": 12345,
    "alertmanager": 9093,
}
BUDGETS = {
    "prometheus": (250, 512, 1536),
    "loki": (200, 256, 1024),
    "grafana": (100, 256, 512),
    "alloy": (100, 128, 384),
    "alertmanager": (50, 64, 128),
}


def render():
    images = json.loads((ROOT / "images.json").read_text())
    objects = []

    def add(kind, name, spec=None, **extra):
        api = {
            "Deployment": "apps/v1",
            "NetworkPolicy": "networking.k8s.io/v1",
            "ClusterRole": "rbac.authorization.k8s.io/v1",
            "ClusterRoleBinding": "rbac.authorization.k8s.io/v1",
            "Role": "rbac.authorization.k8s.io/v1",
            "RoleBinding": "rbac.authorization.k8s.io/v1",
        }.get(kind, "v1")
        obj = {"apiVersion": api, "kind": kind, "metadata": {"name": name}}
        if kind not in ("Namespace", "ClusterRole", "ClusterRoleBinding"):
            obj["metadata"]["namespace"] = NS
        if spec is not None:
            obj["spec"] = spec
        obj.update(extra)
        objects.append(obj)
        return obj

    add("Namespace", NS)["metadata"]["labels"] = {
        "pod-security.kubernetes.io/enforce": "restricted"
    }
    args = {
        "prometheus": [
            "--config.file=/etc/monitoring/prometheus.yml",
            "--storage.tsdb.path=/data",
            "--storage.tsdb.retention.time=48h",
            "--storage.tsdb.retention.size=8GB",
        ],
        "loki": ["-config.file=/etc/monitoring/loki.yml"],
        "alloy": [
            "run",
            "--server.http.listen-addr=0.0.0.0:12345",
            "--storage.path=/data",
            "/etc/monitoring/alloy.alloy",
        ],
        "alertmanager": [
            "--config.file=/etc/monitoring/alertmanager.yml",
            "--storage.path=/data",
            "--data.retention=48h",
            "--cluster.listen-address=",
        ],
        "grafana": [],
    }
    files = {
        "prometheus": ["prometheus.yml", "alerts.yml"],
        "loki": ["loki.yml"],
        "alloy": ["alloy.alloy"],
        "alertmanager": ["alertmanager.yml"],
        "grafana": ["datasources.yml", "dashboards.yml", "dashboard.json"],
    }
    for name, size in SIZES.items():
        add("ServiceAccount", name, automountServiceAccountToken=False)
        add(
            "ConfigMap",
            name,
            data={f: (ROOT / "config" / f).read_text() for f in files[name]},
        )
        add(
            "PersistentVolumeClaim",
            name,
            {
                "accessModes": ["ReadWriteOnce"],
                "storageClassName": "local-primary",
                "resources": {"requests": {"storage": size}},
            },
        )
        port = PORTS[name]
        add(
            "Service",
            name,
            {
                "type": "ClusterIP",
                "selector": {"app": name},
                "ports": [{"name": "http", "port": port, "targetPort": port}],
            },
        )
        cpu, mem, limit = BUDGETS[name]
        mounts = [
            {"name": "data", "mountPath": "/data"},
            {"name": "config", "mountPath": "/etc/monitoring", "readOnly": True},
            {"name": "tmp", "mountPath": "/tmp"},
        ]
        ready = {"grafana": "/api/health", "loki": "/ready"}.get(name, "/-/ready")
        live = {"grafana": "/api/health", "loki": "/ready"}.get(name, "/-/healthy")
        container = {
            "name": name,
            "image": images[name]["image"],
            "args": args[name],
            "ports": [{"containerPort": port}],
            "resources": {
                "requests": {"cpu": f"{cpu}m", "memory": f"{mem}Mi"},
                "limits": {"cpu": "2", "memory": f"{limit}Mi"},
            },
            "securityContext": {
                "allowPrivilegeEscalation": False,
                "readOnlyRootFilesystem": True,
                "capabilities": {"drop": ["ALL"]},
            },
            "volumeMounts": mounts,
            "readinessProbe": {
                "httpGet": {"path": ready, "port": port},
                "periodSeconds": 10,
            },
            "livenessProbe": {
                "httpGet": {"path": live, "port": port},
                "periodSeconds": 20,
                "failureThreshold": 6,
            },
            "startupProbe": {
                "httpGet": {"path": ready, "port": port},
                "periodSeconds": 5,
                "failureThreshold": 60,
            },
        }
        if name == "grafana":
            for filename, folder in [
                ("datasources.yml", "datasources"),
                ("dashboards.yml", "dashboards"),
            ]:
                mounts.append(
                    {
                        "name": "config",
                        "mountPath": f"/etc/grafana/provisioning/{folder}/main.yml",
                        "subPath": filename,
                        "readOnly": True,
                    }
                )
            container["env"] = [
                {"name": k, "value": v}
                for k, v in {
                    "GF_PATHS_DATA": "/data",
                    "GF_PATHS_LOGS": "/data/logs",
                    "GF_PATHS_PLUGINS": "/data/plugins",
                    "GF_ANALYTICS_REPORTING_ENABLED": "false",
                    "GF_ANALYTICS_CHECK_FOR_UPDATES": "false",
                    "GF_PLUGINS_PREINSTALL_DISABLED": "true",
                    "GF_USERS_ALLOW_SIGN_UP": "false",
                    "GF_AUTH_ANONYMOUS_ENABLED": "false",
                    "GF_METRICS_ENABLED": "true",
                }.items()
            ]
            container["env"].append(
                {
                    "name": "GF_SECURITY_ADMIN_PASSWORD",
                    "valueFrom": {
                        "secretKeyRef": {"name": "grafana-admin", "key": "password"}
                    },
                }
            )
        add(
            "Deployment",
            name,
            {
                "replicas": 1,
                "strategy": {"type": "Recreate"},
                "selector": {"matchLabels": {"app": name}},
                "template": {
                    "metadata": {"labels": {"app": name}},
                    "spec": {
                        "serviceAccountName": name,
                        "automountServiceAccountToken": name in ("alloy", "prometheus"),
                        "nodeSelector": {
                            "homelab.tfdraw.dev/worker-role": "primary",
                            "homelab.tfdraw.dev/storage": "local-primary",
                        },
                        "securityContext": {
                            "runAsNonRoot": True,
                            "runAsUser": 65534,
                            "runAsGroup": 65534,
                            "fsGroup": 65534,
                            "fsGroupChangePolicy": "OnRootMismatch",
                            "seccompProfile": {"type": "RuntimeDefault"},
                        },
                        "containers": [container],
                        "volumes": [
                            {
                                "name": "data",
                                "persistentVolumeClaim": {"claimName": name},
                            },
                            {"name": "config", "configMap": {"name": name}},
                            {"name": "tmp", "emptyDir": {"sizeLimit": "64Mi"}},
                        ],
                    },
                },
            },
        )
    add(
        "Role",
        "scoped-log-reader",
        rules=[
            {
                "apiGroups": [""],
                "resources": ["pods", "pods/log"],
                "verbs": ["get", "list", "watch"],
            },
        ],
    )
    add(
        "RoleBinding",
        "scoped-log-reader",
        subjects=[{"kind": "ServiceAccount", "name": "alloy", "namespace": NS}],
        roleRef={
            "apiGroup": "rbac.authorization.k8s.io",
            "kind": "Role",
            "name": "scoped-log-reader",
        },
    )
    # Metrics access cannot read node proxy endpoints or workload Secrets.
    add(
        "ClusterRole",
        "main-node-metrics",
        rules=[
            {
                "apiGroups": [""],
                "resources": ["nodes/metrics"],
                "verbs": ["get"],
                "resourceNames": ["talos-cp-01", "talos-worker-01", "talos-worker-02"],
            },
            {
                "apiGroups": [""],
                "resources": ["nodes"],
                "verbs": ["get", "list", "watch"],
            },
        ],
    )
    add(
        "ClusterRoleBinding",
        "main-node-metrics",
        subjects=[{"kind": "ServiceAccount", "name": "prometheus", "namespace": NS}],
        roleRef={
            "apiGroup": "rbac.authorization.k8s.io",
            "kind": "ClusterRole",
            "name": "main-node-metrics",
        },
    )
    add(
        "NetworkPolicy",
        "private-monitoring",
        {
            "podSelector": {},
            "policyTypes": ["Ingress", "Egress"],
            "ingress": [{"from": [{"podSelector": {}}]}],
            "egress": [
                {"to": [{"podSelector": {}}]},
                {
                    "to": [
                        {
                            "namespaceSelector": {
                                "matchLabels": {
                                    "kubernetes.io/metadata.name": "kube-system"
                                }
                            },
                            "podSelector": {"matchLabels": {"k8s-app": "kube-dns"}},
                        }
                    ],
                    "ports": [
                        {"protocol": "UDP", "port": 53},
                        {"protocol": "TCP", "port": 53},
                    ],
                },
                {
                    "to": [
                        {"ipBlock": {"cidr": ip + "/32"}}
                        for ip in ["10.96.0.1", "10.0.0.221", "10.0.0.231"]
                    ],
                    "ports": [{"port": 443}, {"port": 6443}],
                },
                {
                    "to": [
                        {"ipBlock": {"cidr": ip + "/32"}}
                        for ip in ["10.0.0.221", "10.0.0.222", "10.0.0.225"]
                    ],
                    "ports": [{"port": 10250}],
                },
            ],
        },
    )
    return {"apiVersion": "v1", "kind": "List", "items": objects}


if __name__ == "__main__":
    (ROOT / "resources.json").write_text(json.dumps(render(), indent=2) + "\n")
