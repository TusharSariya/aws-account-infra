# Initial control-plane installation and bootstrap

The control plane is now managed by the [Talos OpenTofu root](../../talos/homelab/README.md).
Routine configuration changes use its GitHub CI path. The CLI sequence below
records the initial installation and is not the current deployment procedure.

Prerequisites: reviewed machine configuration and independently retained Talos
secrets; running maintenance VM 100 with MAC 02:42:00:00:01:00 at 10.42.0.220;
verified blank OS disk /dev/sda of 100 GiB; pinned Talos v1.13.9 CLI; accepted
Tailscale subnet route. This sequence has already been executed on the live
control plane. Do not replay initial bootstrap against it.

On a replacement or first-build administration Mac, recover the private inputs
outside Git, then use the pinned CLI (or its verified platform equivalent):

```bash
TALOSCTL="$HOME/.cache/aws-account-infra/talos/talosctl-darwin-arm64-v1.13.9"
TALOS_DIR="$HOME/.config/aws-account-infra/talos/homelab/two-vm-20260912"
export TALOSCONFIG="$TALOS_DIR/talosconfig"
"$TALOSCTL" -n 10.42.0.220 get machinestatus --insecure
"$TALOSCTL" -n 10.42.0.220 get disks sda --insecure
"$TALOSCTL" validate --config "$TALOS_DIR/talos-cp-01.machineconfig.yaml" --mode metal --strict
```

Only for the verified initial installation target:

```bash
"$TALOSCTL" apply-config --insecure -n 10.42.0.220 \
  --file "$TALOS_DIR/talos-cp-01.machineconfig.yaml"
```

Wait for installation and reboot. Verify authenticated `version`, `get
machinestatus` and `get volumestatus` using the same CLI without `--insecure`.
The initial observed reboot stalled after kexec preparation/disk sync with a
virtnet_poll RCU stall. One pre-bootstrap `qm reset 100` on pve recovered normal
disk boot. Inspect the actual console and state before deciding any recovery;
do not automatically reset a stateful control plane or infer every outage is
this failure. The underlying soft-reboot issue is not yet resolved.

For a new cluster only, issue bootstrap exactly once:

```bash
"$TALOSCTL" -n 10.42.0.220 bootstrap
```

Then wait for etcd and Kubernetes to start. A refused API connection during
startup is not a reason to rerun bootstrap. Inspect `service etcd` and `etcd
members` through authenticated Talos instead.

```bash
umask 077
"$TALOSCTL" -n 10.42.0.220 kubeconfig "$TALOS_DIR/kubeconfig" --merge=false
kubectl --kubeconfig "$TALOS_DIR/kubeconfig" --request-timeout=10s get --raw='/readyz'
kubectl --kubeconfig "$TALOS_DIR/kubeconfig" --request-timeout=10s get nodes -o wide
```

The kubeconfig is private and recoverable through Talos; never commit its
contents. The API endpoint is the control-plane VIP 10.42.0.224:6443, while
Talos administration uses the node address .220. Before the worker and Cilium
are installed, expect a registered NotReady control plane (CNI not initialized)
and Pending CoreDNS. Verify the control-plane NoSchedule taint remains present.
Existing-cluster recovery uses the separate etcd backup/recovery procedure;
initial bootstrap is not a restore command.
