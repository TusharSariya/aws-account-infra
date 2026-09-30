# Retained application-server power

The live installation uses automatic mode with a five-minute idle threshold. New
installations remain in observation until their private acceptance gates pass. The laptop owns the original control-plane
VM, DNS, access proxies, submission controllers, and power coordinator. Worker VMs
102 and 103 and all application disks are retained across physical power cycles.

| Location | Services |
|---|---|
| Ubuntu laptop | Main VM, retained-host coordinator, direct IMM/Proxmox management |
| Laptop control-plane VM | Kubernetes API/etcd, CoreDNS, node networking, Cilium operator, Pi-hole, Tailscale operator/proxies, wake gateways, AI lifecycle, Kueue, ARC controller/listeners, Argo Workflows controller/server |
| Worker 01 | PostgreSQL/CNPG, Nexus/database, local storage provisioner, backups, capacity collectors, monitoring, Argo CD, preferred job/runner and AI compute |
| Worker 02 | Eligible overflow job/runner compute and node networking while awake |

Run these commands over `ssh laptop-dell-studio`, independently of application DNS:

```sh
powerctl="$HOME/.local/share/homelab-capacity/retained/.venv/bin/powerctl"
config="$HOME/.config/homelab-capacity/coordinator.json"
"$powerctl" --config "$config" status primary
"$powerctl" --config "$config" wake primary
"$powerctl" --config "$config" shutdown secondary
```

Normal shutdown leaves demand-driven wake armed. `pause HOST` persists maintenance
intent and prevents a new wake; `resume HOST` clears it. Pause before physical work,
then request shutdown. An already committed orderly shutdown finishes before wake.
Active work is never cancelled to satisfy a shutdown request.

The configured idle period is currently **five minutes**. Change
`config.idleTimeoutSeconds` in
`config/environments/kubernetes/homelab/lifecycle-values.yaml`, apply the management
Helm root, and regenerate the coordinator configuration with
`platform/automatic-power/render-config.py`. Its `idle_seconds` value is reloadable
without restarting the service. Preserve the intended rollout modes when installing
a regenerated configuration: the renderer deliberately defaults to observation.
Idle changes start a fresh window; they never interrupt an in-progress recovery.

Only continuous, complete observations count as idle. Active requests, streaming
connections, user jobs, backups, maintenance holds, and unknown workloads block
retirement. The two registered housekeeping monitors must finish before retirement,
but do not restart the application-idle clock or wake a sleeping host. AI's verified idle window uses the same setting. After that window,
applications stop gracefully, then Talos shuts down, and finally Proxmox powers off.
This adds shutdown time to the configured idle period.

The existing private application URLs terminate on laptop gateways. A cold request
gets HTTP 503 with `Retry-After: 10`; browser GET requests may refresh automatically.
Uploads and API writes are never replayed. Retry them after startup. Existing
authentication passes through unchanged. Health probes do not wake an application.
Kueue chooses primary capacity first and secondary capacity for eligible overflow;
secondary CI also waits for primary Nexus. Monitoring and Argo CD remain unavailable
while primary sleeps, but their retained volumes survive.

For administrative access that also holds primary awake:

```sh
"$powerctl" --config "$config" forward primary --service grafana --local-port 3000 \
  --admin-kubeconfig "$HOME/.local/share/main-control-plane/private/kubeconfig"
```

Forwarding explicitly uses the operator credential; the power coordinator credential
cannot open administrative port forwards. The listener binds only to localhost on the laptop. Use SSH port forwarding from
your workstation and the service's existing login. Exiting normally releases that
forward's hold. A crashed client can leave a durable hold, visible in `status`;
release only its recorded token after confirming the operation has ended.

CI infrastructure operations use named Kubernetes Lease holds through
`scripts/homelab-power-hold.py`. Holds do not expire silently after runner failure.
An interrupted CI run may therefore keep a host awake until its hold is reviewed
and explicitly released. Read-only management plans do not require a worker wake.

Recovery uses the laptop's private journals under
`~/.local/share/homelab-capacity/main/`. Inspect `observations.json`, `HOST.json`,
`HOST-platform.json`, `HOST-transition.json`, and `journalctl --user -u homelab-coordinator.service` before
resuming a blocked transition. Restoration checks resource UIDs and storage bindings
and clears only its own cordon. Never delete a journal to make a blocked transition
proceed. Never start retired VM100, replace worker disks, or force BMC power off.

`commission-sleep.py` is a manual first-cycle validation tool, requiring a stopped
coordinator and explicit observe mode. It does not create an automatic-shutdown
acceptance receipt. Once commissioning is complete, use `powerctl` for normal work.

## Recovery after management races

The coordinator reobserves transient transport errors and Kubernetes conflicts
within a bounded recovery window. New demand detected in the final pre-shutdown
check cancels retirement and restores services. Proxmox autostart and the
coordinator can both attempt VM startup; a failed start is accepted only when a
fresh direct query proves the worker is running.

On coordinator restart, platform restoration/quiescing resumes from its existing
snapshot with fresh identity and ownership checks. A possibly committed shutdown
is observed, never blindly repeated. If completion cannot be proved within the
recovery window, status remains blocked for explicit inspection. Restart does not
clear an existing identity/storage block.

`HOST-transition.json` and the service journal retain the action, operation number,
outcome phase and sanitized failure category. Captured API object bodies, private
configuration and raw SSH output are not logged.

For a legacy blocked start, first verify the registered VM identity and current
state, inspect the platform snapshot and protected storage, and confirm no
conflicting operator maintenance. Then use `powerctl --config PRIVATE.json resume
primary`. Observe restoration and demand processing to completion; a successful
command submission alone is not proof of recovery. Never delete the journal.
