# Homelab power adapter

Bounded status and idempotent wake for registered IMM2 hosts. **No off/reset/raw-command API.** The default transport is pyghmi1.6.19 over IPMI, live-tested from the always-on Ubuntu laptop against both IMM2 controllers. OpenSSH operator access remains available; the optional Paramiko4.0.0 transport also passed live status/idempotent-wake checks. Paramiko5 removed the legacy RSA signature algorithm these controllers require; it is not a drop-in upgrade for this hardware.

```bash
uv sync
uv run homelab-power status secondary --config /private/path/hosts.json
uv run homelab-power ensure-on secondary --config /private/path/hosts.json
```

The local configuration contains an allowlisted `hosts` map, a private `lock_dir`, and (for SSH) `known_hosts`. Each IPMI host supplies `address`, `username`, `transport: ipmi` and `password_file`. That file contains a JSON `password`, must be inaccessible to group/others, and is provisioned outside Git. Each SSH host instead supplies `key_file` and an explicit `legacy_rsa_signature` switch. Unknown SSH host keys are rejected.

On the laptop, configuration and credentials are under `~/.config/homelab-capacity/`; code/runtime under `~/.local/share/homelab-capacity/`. Dedicated IMM account `capacity` is slot2 on each controller with `custom:pr` (power/restart access). It has a laptop-generated SSH key and a separately stored generated IPMI password. Mac operator keys are not copied. The BMC role necessarily grants more power actions than this adapter exposes; it is the narrow supported IMM role, not a hardware-enforced on-only permission.

Every ensure-on obtains a local per-host lock, observes state, sends only `on` if off, then observes again. Unknown/unreachable/error is never off. Subprocess deadlines bound the complete transport operation and isolate pyghmi sessions; a timed-out write is not blindly retried. A subsequent reconcile observes actual state before considering another write. This lock coordinates processes on this laptop, not independent controllers on other machines; use one authoritative coordinator.

IPMI replies are validated as structured power states. SSH responses are parsed strictly because IMM2 may return an error body with exit status zero. Logs do not expose credential contents. Wake acknowledgement is not Proxmox, Kubernetes or application readiness.

Validation: `python -m pytest` from this directory. Tests cover observed replies, ambiguous/error states, idempotence, per-host locking, uncertain writes, and IPMI result validation. Live proof observed both running hosts and returned `changed:false` for ensure-on. No live off/reset or library-driven off-to-on transition was performed; the previous authorized off-to-on proof used OpenSSH.

Sources: [pyghmi](https://opendev.org/x/pyghmi), [Paramiko changes](https://www.paramiko.org/changelog.html), [IMM2 IPMI](https://pubs.lenovo.com/imm2/dw1lm_t_managingtheimmwithipmi).
