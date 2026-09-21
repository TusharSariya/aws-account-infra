"""Render the exact existing pilot, with no credentials in generated manifests."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CONFIG = ROOT.parent / "config"
NS = "pilot-monitoring"
NODE = "talos-v93-t3u"
SIZES = {
    "prometheus": "2Gi",
    "loki": "2Gi",
    "grafana": "1Gi",
    "alloy": "512Mi",
    "alertmanager": "256Mi",
}
PORTS = {
    "prometheus": 9090,
    "loki": 3100,
    "grafana": 3000,
    "alloy": 12345,
    "alertmanager": 9093,
}


def render():
    images = json.loads((ROOT / "images.json").read_text())
    objects = []

    def add(kind, name, spec=None, **extra):
        api = {
            "Deployment": "apps/v1",
            "NetworkPolicy": "networking.k8s.io/v1",
            "Role": "rbac.authorization.k8s.io/v1",
            "RoleBinding": "rbac.authorization.k8s.io/v1",
            "ClusterRole": "rbac.authorization.k8s.io/v1",
            "ClusterRoleBinding": "rbac.authorization.k8s.io/v1",
        }.get(kind, "v1")
        obj = {"apiVersion": api, "kind": kind, "metadata": {"name": name}}
        if kind not in [
            "Namespace",
            "PersistentVolume",
            "ClusterRole",
            "ClusterRoleBinding",
        ]:
            obj["metadata"]["namespace"] = NS
        if spec is not None:
            obj["spec"] = spec
        obj.update(extra)
        objects.append(obj)
        return obj

    add("Namespace", NS)["metadata"]["labels"] = {
        "pod-security.kubernetes.io/enforce": "restricted"
    }
    limits = {
        "prometheus": 384,
        "loki": 384,
        "grafana": 512,
        "alloy": 256,
        "alertmanager": 96,
    }
    requests = {
        "prometheus": (150, 128),
        "loki": (100, 128),
        "grafana": (100, 256),
        "alloy": (100, 64),
        "alertmanager": (50, 32),
    }
    args = {
        "prometheus": [
            "--config.file=/etc/pilot/prometheus.yml",
            "--storage.tsdb.path=/data",
            "--storage.tsdb.retention.time=48h",
            "--storage.tsdb.retention.size=1GB",
            "--web.enable-lifecycle",
        ],
        "loki": ["-config.file=/etc/pilot/loki.yml"],
        "alloy": [
            "run",
            "--server.http.listen-addr=0.0.0.0:12345",
            "--storage.path=/data",
            "/etc/pilot/alloy.alloy",
        ],
        "grafana": [],
        "alertmanager": [
            "--config.file=/etc/pilot/alertmanager.yml",
            "--storage.path=/data",
            "--data.retention=48h",
            "--cluster.listen-address=",
        ],
    }
    configs = {}
    prom = (
        (CONFIG / "prometheus.yml")
        .read_text()
        .replace("'@BASE@/config/alerts.yml'", "'/etc/pilot/alerts.yml'")
        .replace("'@BASE@/config/proofs/*.yml'", "'/etc/proofs/*.yml'")
    )
    for name, port in PORTS.items():
        prom = prom.replace(f"127.0.0.1:{port}", f"{name}:{port}")
    prom = (
        prom[: prom.index("  - job_name: pilot-http")]
        + """  - job_name: pilot-http
    sample_limit: 100
    static_configs:
      - targets: ['pilot-http.pilot-app.svc:8080']
  - job_name: volume-metrics
    metric_relabel_configs:
      - source_labels: [__name__, namespace]
        regex: 'kubelet_volume_stats_.*;pilot-monitoring'
        action: keep
    scheme: https
    metrics_path: /metrics
    authorization:
      credentials_file: /var/run/secrets/kubernetes.io/serviceaccount/token
    tls_config:
      ca_file: /var/run/secrets/kubernetes.io/serviceaccount/ca.crt
    static_configs:
      - targets: ['10.0.2.15:10250']
"""
    )
    prom = prom.replace(
        "  - job_name: pilot\n",
        """  - job_name: pilot
    scheme: https
    authorization:
      credentials_file: /etc/host/token
    tls_config:
      ca_file: /etc/host/ca.crt
""",
    ).replace("127.0.0.1:9810", "10.0.2.2:9810")
    alerts = (
        (CONFIG / "alerts.yml")
        .read_text()
        .replace(
            'pilot_data_bytes{service="loki"} > 1610612736 or pilot_host_disk_free_bytes < 10737418240',
            '(kubelet_volume_stats_available_bytes{namespace="pilot-monitoring"} / kubelet_volume_stats_capacity_bytes{namespace="pilot-monitoring"}) < 0.2 or pilot_host_disk_free_bytes < 5368709120',
        )
        .replace(
            'pilot_monitoring_up{unit=~"pilot-(loki|alloy|prometheus|exporter)"} == 0',
            'up{job=~"loki|alloy|prometheus|pilot"} == 0',
        )
    )
    prom += "  - job_name: grafana\n    static_configs:\n      - targets: ['grafana:3000']\n  - job_name: alertmanager\n    static_configs:\n      - targets: ['alertmanager:9093']\n"
    configs["prometheus"] = {"prometheus.yml": prom, "alerts.yml": alerts}
    configs["loki"] = {
        "loki.yml": (CONFIG / "loki.yml")
        .read_text()
        .replace("'@BASE@/data/loki", "'/data")
        .replace("http_listen_address: 127.0.0.1", "http_listen_address: 0.0.0.0")
    }
    alloy = (CONFIG / "alloy.alloy").read_text()
    alloy = (
        alloy[: alloy.index("loki.source.journal")]
        + alloy[alloy.index('loki.write "local"') :]
    )
    alloy = (
        alloy.replace('  kubeconfig_file = "@BASE@/private/reader.kubeconfig"\n', "")
        .replace("  client {\n    }\n", "")
        .replace("127.0.0.1:3100", "loki:3100")
    )
    configs["alloy"] = {"alloy.alloy": alloy}
    configs["alertmanager"] = {
        "alertmanager.yml": (CONFIG / "alertmanager.yml")
        .read_text()
        .replace("http://127.0.0.1:9810", "https://10.0.2.2:9810")
        + """        http_config:
          authorization:
            credentials_file: /etc/host/token
          tls_config:
            ca_file: /etc/host/ca.crt
"""
    }
    configs["grafana"] = {
        "datasources.yml": """apiVersion: 1
datasources:
  - name: Pilot Prometheus
    uid: pilot-prometheus
    type: prometheus
    access: proxy
    url: http://prometheus:9090
    isDefault: true
    editable: false
  - name: Pilot Loki
    uid: pilot-loki
    type: loki
    access: proxy
    url: http://loki:3100
    editable: false
""",
        "dashboards.yml": """apiVersion: 1
providers:
  - name: pilot
    type: file
    orgId: 1
    disableDeletion: true
    editable: false
    options:
      path: /etc/pilot
""",
        "dashboard.json": (CONFIG / "dashboard.json").read_text(),
    }
    dashboard = json.loads(configs["grafana"]["dashboard.json"])
    for panel in dashboard["panels"]:
        if panel["title"] == "Monitoring memory (systemd cgroups)":
            panel["title"] = "Monitoring process memory"
        for target in panel.get("targets", []):
            expr = target.get("expr", "")
            expr = expr.replace(
                "pilot_data_bytes",
                'kubelet_volume_stats_used_bytes{namespace="pilot-monitoring"}',
            )
            expr = expr.replace(
                "pilot_monitoring_memory_bytes",
                'process_resident_memory_bytes{job=~"prometheus|loki|alloy|grafana|alertmanager"}',
            )
            expr = expr.replace(
                "pilot_monitoring_cpu_seconds_total",
                'process_cpu_seconds_total{job=~"prometheus|loki|alloy|grafana|alertmanager"}',
            )
            target["expr"] = expr
    configs["grafana"]["dashboard.json"] = json.dumps(dashboard, indent=2)
    add("ConfigMap", "delivery-proof", data={"delivery.yml": '{"groups": []}'})
    for name, size in SIZES.items():
        add("ServiceAccount", name, automountServiceAccountToken=False)
        add("ConfigMap", name, data=configs[name])
        add(
            "PersistentVolume",
            "pilot-monitoring-" + name,
            {
                "capacity": {"storage": size},
                "volumeMode": "Filesystem",
                "accessModes": ["ReadWriteOnce"],
                "persistentVolumeReclaimPolicy": "Retain",
                "storageClassName": "",
                "claimRef": {"namespace": NS, "name": name},
                "local": {"path": "/var/mnt/pilot-" + name},
                "nodeAffinity": {
                    "required": {
                        "nodeSelectorTerms": [
                            {
                                "matchExpressions": [
                                    {
                                        "key": "kubernetes.io/hostname",
                                        "operator": "In",
                                        "values": [NODE],
                                    }
                                ]
                            }
                        ]
                    }
                },
            },
        )
        add(
            "PersistentVolumeClaim",
            name,
            {
                "accessModes": ["ReadWriteOnce"],
                "storageClassName": "",
                "volumeName": "pilot-monitoring-" + name,
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
        mounts = [
            {"name": "data", "mountPath": "/data"},
            {"name": "config", "mountPath": "/etc/pilot", "readOnly": True},
            {"name": "tmp", "mountPath": "/tmp"},
        ]
        volumes = [
            {"name": "data", "persistentVolumeClaim": {"claimName": name}},
            {"name": "config", "configMap": {"name": name}},
            {"name": "tmp", "emptyDir": {"sizeLimit": "32Mi"}},
        ]
        if name in ["prometheus", "alertmanager"]:
            mounts.append({"name": "host", "mountPath": "/etc/host", "readOnly": True})
            volumes.append({"name": "host", "secret": {"secretName": "host-telemetry"}})
        if name == "prometheus":
            mounts.append(
                {"name": "proofs", "mountPath": "/etc/proofs", "readOnly": True}
            )
            volumes.append({"name": "proofs", "configMap": {"name": "delivery-proof"}})
        cpu, mem = requests[name]
        ready = {"loki": "/ready", "grafana": "/api/health", "alloy": "/-/ready"}.get(
            name, "/-/ready"
        )
        live = {"loki": "/ready", "grafana": "/api/health", "alloy": "/-/healthy"}.get(
            name, "/-/healthy"
        )
        container = {
            "name": name,
            "image": images[name]["image"],
            "args": args[name],
            "ports": [{"containerPort": port}],
            "resources": {
                "requests": {"cpu": f"{cpu}m", "memory": f"{mem}Mi"},
                "limits": {"cpu": "1", "memory": f"{limits[name]}Mi"},
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
            for filename, path in [
                ("datasources.yml", "/etc/grafana/provisioning/datasources/pilot.yml"),
                ("dashboards.yml", "/etc/grafana/provisioning/dashboards/pilot.yml"),
            ]:
                mounts.append(
                    {
                        "name": "config",
                        "mountPath": path,
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
                    "GF_METRICS_ENABLED": "true",
                }.items()
            ] + [
                {
                    "name": "GF_SECURITY_ADMIN_PASSWORD",
                    "valueFrom": {
                        "secretKeyRef": {"name": "grafana-admin", "key": "password"}
                    },
                }
            ]
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
                        "automountServiceAccountToken": name in ["alloy", "prometheus"],
                        "nodeSelector": {
                            "kubernetes.io/hostname": NODE,
                            "node-role.kubernetes.io/control-plane": "",
                        },
                        "tolerations": [
                            {
                                "key": "node-role.kubernetes.io/control-plane",
                                "operator": "Exists",
                                "effect": "NoSchedule",
                            }
                        ],
                        "securityContext": {
                            "runAsNonRoot": True,
                            "runAsUser": 65534,
                            "runAsGroup": 65534,
                            "fsGroup": 65534,
                            "fsGroupChangePolicy": "OnRootMismatch",
                            "seccompProfile": {"type": "RuntimeDefault"},
                        },
                        "containers": [container],
                        "volumes": volumes,
                    },
                },
            },
        )
    add(
        "Role",
        "pilot-host-health",
        rules=[{"apiGroups": [""], "resources": ["pods"], "verbs": ["get", "list"]}],
    )
    add(
        "RoleBinding",
        "pilot-host-health",
        subjects=[
            {
                "kind": "User",
                "name": "pilot-monitoring-reader",
                "apiGroup": "rbac.authorization.k8s.io",
            }
        ],
        roleRef={
            "apiGroup": "rbac.authorization.k8s.io",
            "kind": "Role",
            "name": "pilot-host-health",
        },
    )
    for namespace in ["prototype-slot", "pilot-app"]:
        role = add(
            "Role",
            "pilot-log-reader",
            rules=[
                {
                    "apiGroups": [""],
                    "resources": ["pods", "pods/log"],
                    "verbs": ["get", "list", "watch"],
                }
            ],
        )
        role["metadata"]["namespace"] = namespace
        binding = add(
            "RoleBinding",
            "pilot-log-reader",
            subjects=[{"kind": "ServiceAccount", "name": "alloy", "namespace": NS}],
            roleRef={
                "apiGroup": "rbac.authorization.k8s.io",
                "kind": "Role",
                "name": "pilot-log-reader",
            },
        )
        binding["metadata"]["namespace"] = namespace
    add(
        "ClusterRole",
        "pilot-volume-metrics",
        rules=[
            {
                "apiGroups": [""],
                "resources": ["nodes/metrics"],
                "resourceNames": [NODE],
                "verbs": ["get"],
            }
        ],
    )
    add(
        "ClusterRoleBinding",
        "pilot-volume-metrics",
        subjects=[{"kind": "ServiceAccount", "name": "prometheus", "namespace": NS}],
        roleRef={
            "apiGroup": "rbac.authorization.k8s.io",
            "kind": "ClusterRole",
            "name": "pilot-volume-metrics",
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
                {
                    "to": [{"ipBlock": {"cidr": "10.96.0.1/32"}}],
                    "ports": [{"port": 443}],
                },
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
                    "to": [{"ipBlock": {"cidr": "10.0.2.15/32"}}],
                    "ports": [{"port": 6443}, {"port": 10250}],
                },
                {
                    "to": [{"ipBlock": {"cidr": "10.0.2.2/32"}}],
                    "ports": [{"port": 9810}],
                },
                {
                    "to": [
                        {
                            "namespaceSelector": {
                                "matchLabels": {
                                    "kubernetes.io/metadata.name": "pilot-app"
                                }
                            },
                            "podSelector": {"matchLabels": {"app": "pilot-http"}},
                        }
                    ],
                    "ports": [{"port": 8080}],
                },
            ],
        },
    )
    # Cilium CIDR peers exclude cluster node identities; use explicit entities.
    for name, app, entity, ports in [
        ("alloy-api", "alloy", "kube-apiserver", ["443", "6443"]),
        ("prometheus-kubelet", "prometheus", "host", ["10250"]),
    ]:
        objects.append(
            {
                "apiVersion": "cilium.io/v2",
                "kind": "CiliumNetworkPolicy",
                "metadata": {"name": name, "namespace": NS},
                "spec": {
                    "endpointSelector": {"matchLabels": {"app": app}},
                    "egress": [
                        {
                            "toEntities": [entity],
                            "toPorts": [
                                {
                                    "ports": [
                                        {"port": port, "protocol": "TCP"}
                                        for port in ports
                                    ]
                                }
                            ],
                        }
                    ],
                },
            }
        )
    return objects


if __name__ == "__main__":
    (ROOT / "resources.json").write_text(
        json.dumps({"apiVersion": "v1", "kind": "List", "items": render()}, indent=2)
        + "\n"
    )
    (ROOT / "kustomization.yaml").write_text(
        "apiVersion: kustomize.config.k8s.io/v1beta1\nkind: Kustomization\nresources:\n  - resources.json\n"
    )
    (ROOT.parent.parent / "vm/user-volumes.yaml").write_text(
        "\n---\n".join(
            f"apiVersion: v1alpha1\nkind: UserVolumeConfig\nname: pilot-{name}\nprovisioning:\n  diskSelector:\n    match: disk.serial == 'PILOT-MONITORING-01' && !system_disk\n  minSize: {size}B\n  maxSize: {size}B\nfilesystem:\n  type: ext4\n"
            for name, size in SIZES.items()
        )
    )
