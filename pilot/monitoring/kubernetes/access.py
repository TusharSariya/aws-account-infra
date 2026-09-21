"""Local-only systemd forwards shared by deployment and host recovery."""

from pathlib import Path
from common import PROFILE, run

PORTS = {
    "prometheus": 9090,
    "loki": 3100,
    "alloy": 12345,
    "grafana": 3000,
    "alertmanager": 9093,
}
SERVICES = list(PORTS)


def configure_forwards():
    unit_dir = Path.home() / ".config/systemd/user"
    unit_dir.mkdir(parents=True, exist_ok=True)
    for name, port in PORTS.items():
        (unit_dir / f"pilot-forward-{name}.service").write_text(f"""[Unit]
Description=Private pilot {name} Kubernetes service forward
[Service]
ExecStart={Path(PROFILE["kubectl"]).expanduser()} --kubeconfig={Path(PROFILE["kubeconfig"]).expanduser()} -n pilot-monitoring port-forward --address=127.0.0.1 service/{name} {port}:{port}
Restart=always
RestartSec=3
NoNewPrivileges=true
MemoryMax=64M
[Install]
WantedBy=default.target
""")
    run(["systemctl", "--user", "daemon-reload"])
    run(
        [
            "systemctl",
            "--user",
            "enable",
            "--now",
            *["pilot-forward-" + n for n in SERVICES],
        ]
    )
