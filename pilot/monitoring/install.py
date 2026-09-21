"""Install isolated, checksum-pinned systemd user services on the pilot laptop."""

import argparse
import base64
import hashlib
import json
import os
import platform
import secrets
import shutil
import tarfile
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path

from common import BASE, ROOT, get, identity, kubectl, memory, run

LIMITS = {
    "prometheus": 384,
    "loki": 384,
    "alloy": 256,
    "exporter": 96,
    "grafana": 512,
    "alertmanager": 96,
}


def apply(value):
    identity(admin=True)
    kubectl("apply", "-f", "-", admin=True, data=json.dumps(value))


def ensure_reader_namespaces():
    """Leave existing namespace policy and ownership untouched during renewal."""
    existing = {n["metadata"]["name"] for n in get("namespaces", admin=True)["items"]}
    for ns in ["pilot-monitoring", "pilot-app"]:
        if ns in existing:
            continue
        apply(
            {
                "apiVersion": "v1",
                "kind": "Namespace",
                "metadata": {
                    "name": ns,
                    "labels": {
                        "monitoring.homelab/owner": "pilot-monitoring",
                        "pod-security.kubernetes.io/enforce": "restricted",
                    },
                },
            }
        )


def reader():
    """Dedicated client certificate: no secrets, exec, writes or general log access."""
    private = BASE / "private"
    private.mkdir(mode=0o700, exist_ok=True)
    ensure_reader_namespaces()
    rules = [
        {"apiGroups": [""], "resources": ["nodes"], "verbs": ["get", "list", "watch"]},
        {
            "apiGroups": [""],
            "resources": ["namespaces"],
            "resourceNames": ["kube-system"],
            "verbs": ["get"],
        },
    ]
    apply(
        {
            "apiVersion": "rbac.authorization.k8s.io/v1",
            "kind": "ClusterRole",
            "metadata": {"name": "pilot-monitoring-reader"},
            "rules": rules,
        }
    )
    apply(
        {
            "apiVersion": "rbac.authorization.k8s.io/v1",
            "kind": "ClusterRoleBinding",
            "metadata": {"name": "pilot-monitoring-reader"},
            "roleRef": {
                "apiGroup": "rbac.authorization.k8s.io",
                "kind": "ClusterRole",
                "name": "pilot-monitoring-reader",
            },
            "subjects": [
                {
                    "kind": "User",
                    "name": "pilot-monitoring-reader",
                    "apiGroup": "rbac.authorization.k8s.io",
                }
            ],
        }
    )
    for ns in ["prototype-slot", "pilot-app"]:
        apply(
            {
                "apiVersion": "rbac.authorization.k8s.io/v1",
                "kind": "Role",
                "metadata": {"name": "pilot-monitoring-reader", "namespace": ns},
                "rules": [
                    {
                        "apiGroups": [""],
                        "resources": ["pods", "pods/log"],
                        "verbs": ["get", "list", "watch"],
                    },
                    {
                        "apiGroups": ["kueue.x-k8s.io"],
                        "resources": ["workloads"],
                        "verbs": ["get", "list", "watch"],
                    },
                ],
            }
        )
        apply(
            {
                "apiVersion": "rbac.authorization.k8s.io/v1",
                "kind": "RoleBinding",
                "metadata": {"name": "pilot-monitoring-reader", "namespace": ns},
                "roleRef": {
                    "apiGroup": "rbac.authorization.k8s.io",
                    "kind": "Role",
                    "name": "pilot-monitoring-reader",
                },
                "subjects": [
                    {
                        "kind": "User",
                        "name": "pilot-monitoring-reader",
                        "apiGroup": "rbac.authorization.k8s.io",
                    }
                ],
            }
        )
    apply(
        {
            "apiVersion": "rbac.authorization.k8s.io/v1",
            "kind": "Role",
            "metadata": {"name": "pilot-metrics-proxy", "namespace": "pilot-app"},
            "rules": [
                {
                    "apiGroups": [""],
                    "resources": ["services/proxy"],
                    "resourceNames": ["http:pilot-http:8080"],
                    "verbs": ["get"],
                }
            ],
        }
    )
    apply(
        {
            "apiVersion": "rbac.authorization.k8s.io/v1",
            "kind": "RoleBinding",
            "metadata": {"name": "pilot-metrics-proxy", "namespace": "pilot-app"},
            "roleRef": {
                "apiGroup": "rbac.authorization.k8s.io",
                "kind": "Role",
                "name": "pilot-metrics-proxy",
            },
            "subjects": [
                {
                    "kind": "User",
                    "name": "pilot-monitoring-reader",
                    "apiGroup": "rbac.authorization.k8s.io",
                }
            ],
        }
    )
    for ns, names in [
        ("kueue-system", ["prototype-kueue-controller-manager"]),
        ("prototype-slot", ["prototype-binpack", "prototype-slot-ca"]),
    ]:
        apply(
            {
                "apiVersion": "rbac.authorization.k8s.io/v1",
                "kind": "Role",
                "metadata": {"name": "pilot-controller-health", "namespace": ns},
                "rules": [
                    {
                        "apiGroups": ["apps"],
                        "resources": ["deployments"],
                        "resourceNames": names,
                        "verbs": ["get"],
                    }
                ],
            }
        )
        apply(
            {
                "apiVersion": "rbac.authorization.k8s.io/v1",
                "kind": "RoleBinding",
                "metadata": {"name": "pilot-controller-health", "namespace": ns},
                "roleRef": {
                    "apiGroup": "rbac.authorization.k8s.io",
                    "kind": "Role",
                    "name": "pilot-controller-health",
                },
                "subjects": [
                    {
                        "kind": "User",
                        "name": "pilot-monitoring-reader",
                        "apiGroup": "rbac.authorization.k8s.io",
                    }
                ],
            }
        )
    cert = private / "reader.crt"
    if (
        cert.exists()
        and (private / "reader.kubeconfig").exists()
        and (private / "reader.key").exists()
    ):
        try:
            run(["openssl", "x509", "-checkend", "86400", "-noout", "-in", str(cert)])
            if not (private / "ca.crt").exists():
                cfg = json.loads(
                    kubectl(
                        "config", "view", "--minify", "--raw", "-o", "json", admin=True
                    )
                )
                ca = cfg["clusters"][0]["cluster"]
                if "certificate-authority-data" in ca:
                    (private / "ca.crt").write_bytes(
                        base64.b64decode(ca["certificate-authority-data"])
                    )
                else:
                    shutil.copy2(ca["certificate-authority"], private / "ca.crt")
            return
        except Exception:
            pass
    key, csr = private / "reader.key", private / "reader.csr"
    run(
        [
            "openssl",
            "req",
            "-new",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-keyout",
            str(key),
            "-out",
            str(csr),
            "-subj",
            "/CN=pilot-monitoring-reader",
        ]
    )
    name = "pilot-monitoring-" + secrets.token_hex(5)
    apply(
        {
            "apiVersion": "certificates.k8s.io/v1",
            "kind": "CertificateSigningRequest",
            "metadata": {"name": name},
            "spec": {
                "request": base64.b64encode(csr.read_bytes()).decode(),
                "signerName": "kubernetes.io/kube-apiserver-client",
                "expirationSeconds": 2592000,
                "usages": ["client auth"],
            },
        }
    )
    identity(admin=True)
    kubectl("certificate", "approve", name, admin=True)
    for _ in range(30):
        signed = get("csr", name, admin=True).get("status", {}).get("certificate")
        if signed:
            cert.write_bytes(base64.b64decode(signed))
            break
        time.sleep(1)
    else:
        raise RuntimeError("Reader certificate signing timed out")
    cfg = json.loads(
        kubectl("config", "view", "--minify", "--raw", "-o", "json", admin=True)
    )
    ca = cfg["clusters"][0]["cluster"]
    if "certificate-authority-data" in ca:
        (private / "ca.crt").write_bytes(
            base64.b64decode(ca["certificate-authority-data"])
        )
    else:
        shutil.copy2(ca["certificate-authority"], private / "ca.crt")
    cfg["users"] = [
        {
            "name": "reader",
            "user": {"client-certificate": str(cert), "client-key": str(key)},
        }
    ]
    cfg["contexts"][0]["context"]["user"] = "reader"
    (private / "reader.kubeconfig").write_text(json.dumps(cfg))
    identity(admin=True)
    kubectl("delete", "csr", name, admin=True)


def release(name):
    spec = json.loads((ROOT / "releases.json").read_text())[name]
    dest = BASE / "releases" / (name + "-" + spec["version"])
    if (dest / ".verified").exists():
        if (dest / ".verified").read_text() != spec["sha256"]:
            raise RuntimeError("Installed release lock mismatch")
        return dest
    dest.mkdir(parents=True, exist_ok=True)
    print("Downloading", name, spec["version"], flush=True)
    with tempfile.TemporaryFile() as download:
        digest = hashlib.sha256()
        with urllib.request.urlopen(spec["url"], timeout=120) as response:
            while chunk := response.read(1024 * 1024):
                download.write(chunk)
                digest.update(chunk)
        if digest.hexdigest() != spec["sha256"]:
            raise RuntimeError("Release checksum mismatch: " + name)
        download.seek(0)
        if spec["url"].endswith(".zip"):
            with zipfile.ZipFile(download) as archive:
                for member in archive.namelist():
                    if "/" not in member:
                        with (
                            archive.open(member) as source,
                            (dest / member).open("wb") as target,
                        ):
                            shutil.copyfileobj(source, target)
                        (dest / member).chmod(0o755)
        else:
            with tarfile.open(fileobj=download, mode="r:gz") as archive:
                archive.extractall(dest, filter="data")
    (dest / ".verified").write_text(spec["sha256"])
    return dest


def binary(name, filename=None):
    folder = release(name)
    return next(p for p in folder.rglob(filename or name) if p.is_file())


def unit(name, command, extra=""):
    dest = Path.home() / ".config/systemd/user" / ("pilot-" + name + ".service")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(f"""[Unit]
Description=Isolated pilot {name}
After=network-online.target

[Service]
ExecStart={command}
WorkingDirectory={BASE}
Restart=on-failure
RestartSec=10
MemoryHigh={int(LIMITS[name] * (0.9 if name == "grafana" else 0.8))}M
MemoryMax={LIMITS[name]}M
MemorySwapMax=0
CPUQuota=100%
TasksMax=128
NoNewPrivileges=yes
UMask=0077
Environment=GOMEMLIMIT={int(LIMITS[name] * 0.7)}MiB
{extra}
[Install]
WantedBy=default.target
""")


def install(stage):
    os.umask(0o077)
    if platform.system() != "Linux" or platform.machine() != "x86_64":
        raise RuntimeError("Installer requires the Linux amd64 pilot laptop")
    identity(admin=True)
    selected = (
        ["prometheus", "loki", "alloy", "exporter"]
        if stage == "metrics"
        else ["grafana", "alertmanager"]
    )
    required = (512 + sum(LIMITS[name] for name in selected)) * 1024**2
    if memory()["MemAvailable"] < required:
        raise RuntimeError(
            "Insufficient available RAM for this stage plus 512 MiB reserve"
        )
    if shutil.disk_usage(Path.home()).free < 10 * 1024**3:
        raise RuntimeError("Less than 10 GiB free disk")
    BASE.mkdir(parents=True, exist_ok=True)
    (BASE / "config").mkdir(exist_ok=True)
    (BASE / "config/proofs").mkdir(exist_ok=True)
    (BASE / "source").mkdir(exist_ok=True)
    for src in ROOT.glob("*.py"):
        shutil.copy2(src, BASE / "source" / src.name)
    shutil.copy2(ROOT / "profile.json", BASE / "source/profile.json")
    for name in LIMITS:
        (BASE / "data" / name).mkdir(parents=True, exist_ok=True)
    for src in (ROOT / "config").iterdir():
        if src.is_file():
            (BASE / "config" / src.name).write_text(
                src.read_text().replace("@BASE@", str(BASE))
            )
    if stage == "metrics":
        reader()
        prom = binary("prometheus")
        loki = binary("loki", "loki-linux-amd64")
        alloy = binary("alloy", "alloy-linux-amd64")
        run(
            [
                str(prom.parent / "promtool"),
                "check",
                "config",
                str(BASE / "config/prometheus.yml"),
            ]
        )
        run(
            [
                str(loki),
                "-config.file=" + str(BASE / "config/loki.yml"),
                "-verify-config=true",
            ]
        )
        run([str(alloy), "validate", str(BASE / "config/alloy.alloy")])
        unit(
            "prometheus",
            f"{prom} --config.file={BASE}/config/prometheus.yml --storage.tsdb.path={BASE}/data/prometheus --storage.tsdb.retention.time=48h --storage.tsdb.retention.size=1GB --web.listen-address=127.0.0.1:9090",
        )
        unit("loki", f"{loki} -config.file={BASE}/config/loki.yml")
        unit(
            "alloy",
            f"{alloy} run --server.http.listen-addr=127.0.0.1:12345 --storage.path={BASE}/data/alloy {BASE}/config/alloy.alloy",
        )
        unit("exporter", f"/usr/bin/python3 {BASE}/source/exporter.py")
        names = ["exporter", "prometheus", "loki", "alloy"]
    else:
        report = json.loads((BASE / "measurement.json").read_text())
        if not report["passed"] or time.time() - report["ended"] > 86400:
            raise RuntimeError(
                "Dashboard stage requires a passing recent bounded-load measurement"
            )
        grafana = binary("grafana", "grafana")
        am = binary("alertmanager")
        run(
            [
                str(am.parent / "amtool"),
                "check-config",
                str(BASE / "config/alertmanager.yml"),
            ]
        )
        provision = BASE / "config/provisioning"
        for child in ["datasources", "dashboards"]:
            (provision / child).mkdir(parents=True, exist_ok=True)
        (provision / "datasources/pilot.yml").write_text("""apiVersion: 1
datasources:
  - name: Pilot Prometheus
    uid: pilot-prometheus
    type: prometheus
    access: proxy
    url: http://127.0.0.1:9090
    isDefault: true
    editable: false
  - name: Pilot Loki
    uid: pilot-loki
    type: loki
    access: proxy
    url: http://127.0.0.1:3100
    editable: false
""")
        (BASE / "config/dashboards").mkdir(exist_ok=True)
        shutil.copy2(
            BASE / "config/dashboard.json", BASE / "config/dashboards/pilot.json"
        )
        (provision / "dashboards/pilot.yml").write_text(f"""apiVersion: 1
providers:
  - name: pilot
    type: file
    orgId: 1
    disableDeletion: true
    editable: false
    options:
      path: {BASE}/config/dashboards
""")
        password = BASE / "private/grafana-password"
        if not password.exists():
            password.write_text(secrets.token_urlsafe(24))
        (BASE / "config/grafana.ini").write_text(f"""[server]
http_addr = 127.0.0.1
http_port = 3000
[paths]
data = {BASE}/data/grafana
logs = {BASE}/data/grafana/logs
plugins = {BASE}/data/grafana/plugins
provisioning = {provision}
[security]
admin_password = $__file{{{password}}}
[users]
allow_sign_up = false
[analytics]
reporting_enabled = false
check_for_updates = false
[plugins]
preinstall_disabled = true
[log]
mode = console
""")
        unit(
            "grafana",
            f"{grafana} server --homepath={grafana.parent.parent} --config={BASE}/config/grafana.ini",
        )
        unit(
            "alertmanager",
            f"{am} --config.file={BASE}/config/alertmanager.yml --storage.path={BASE}/data/alertmanager --data.retention=48h --web.listen-address=127.0.0.1:9093 --cluster.listen-address=",
        )
        names = ["grafana", "alertmanager"]
    run(["systemctl", "--user", "daemon-reload"])
    for name in names:
        run(["systemctl", "--user", "enable", "pilot-" + name])
        run(["systemctl", "--user", "restart", "pilot-" + name])
    print("Installed:", ", ".join(names))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=["metrics", "dashboards"])
    install(parser.parse_args().stage)
