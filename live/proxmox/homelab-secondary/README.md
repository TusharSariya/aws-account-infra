# Secondary PVE worker

This root manages only `talos-worker-02` on secondary PVE `10.0.0.223`.
Runtime `started` changes are ignored by OpenTofu: the laptop manual sleep/wake
procedure owns power state. New guests start stopped, while host autostart stays enabled.
Its fixed contract is VM 103, 38 vCPUs, 112 GiB RAM without ballooning,
one 320-GiB OS disk (`scsi0` / `/dev/sda`), MAC `02:42:00:00:01:03`,
guest-configured static `10.0.0.225`, QEMU Guest Agent, gVisor and autostart.
The 128-GiB host budget retains 16 GiB for PVE; verify actual usable memory
and pressure before provisioning. Do not use this root's state for primary PVE.

Status on 2026-09-19: VM 103 is provisioned and Kubernetes capacity is active.
Ready, Talos health, resources/extensions, gVisor stateless placement,
bidirectional Cilium Pod/Service/DNS and protected-PVC checks passed.
Temporary test resources were removed. Mocked plans and strict validation pass.
Secondary CacheVault CVPM02 requires replacement: retain protective write-through
and disabled disk cache; do not force write-back. See LOG-0091 through LOG-0094.

The observed PVE node name is `pve`. The live apply used an SSH tunnel and pinned
Linux OpenTofu 1.11.5 with the SSH-verified PVE CA, because macOS provider TLS
did not honor the file-supplied CA. Certificate validation was not disabled.
Local state is ignored by Git and backed up in the private join directory;
restore it before planning against this existing VM. Do not initialize empty
state and attempt to recreate VM 103. Off-site state recovery remains separate
acceptance work.

```sh
tofu -chdir=live/proxmox/homelab-secondary validate
tofu -chdir=live/proxmox/homelab-secondary test \
  -var-file=../../../config/environments/proxmox/homelab/secondary/vms.tfvars
```

Mock tests do not contact PVE. For deployment, supply the observed `node_name`,
trusted `PROXMOX_VE_ENDPOINT` and credentials privately. Keep
`host_readiness_confirmed=false` until the
[join runbook](../../../docs/plans/talos-two-worker-operations.md) checks pass.
Review a secondary-only create plan, preserve recoverable state, check .225
vacancy immediately before creation, and verify maintenance-mode disk identity
before applying worker-02's existing-cluster configuration. Never run etcd
bootstrap again or apply primary bootstrap configurations during this join.

Worker-02 has `homelab.tfdraw.dev/worker-role=secondary` and
`homelab.tfdraw.dev/stateless-compute=true`. It has no local-storage label,
local PV or secondary StorageClass. The 200-GiB secondary Nexus OCI cache
disk and instance, Docker Hub/ECR proxying, registry mirrors, Roles Anywhere
refresher and `cache-registry.homelab.tfdraw.dev` are explicitly deferred.
Preserve worker-01's 1,200-GiB primary-local data disk and the existing Pi-hole,
CNPG/PostgreSQL, Nexus and Nexus PostgreSQL PVC workloads.

Record active capacity only after Ready, unique identity/IP, expected resources
and extensions, Talos health, Cilium pod/Service connectivity, stateless
placement, API VIP continuity and protected-PVC checks pass.
