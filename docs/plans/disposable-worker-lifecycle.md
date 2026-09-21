# Disposable worker VM lifecycle

User decision, 2026-09-20, for the Wayfinder placement discussion: create and delete Talos worker VMs during routine scaling rather than parking and restarting fixed worker VMs. This supersedes the earlier reusable-worker assumption and changes the autoscaler-provider comparison.

## Agreed behavior

- The laptop remains the always-on management host with the control plane, demand listeners and scaling controllers.
- Each physical server has one fixed-size main worker slot. Its VM is disposable compute; CI runner Pods remain disposable as well. No bootstrap management VM is planned.
- Prefer eligible awake capacity; create additional capacity only when demand requires it. Pack and consolidate work to permit a physical host to sleep.
- Per-app configuration governs runtime policy, relocation, restart permission, active sessions and completion. Persistent runtime does not make a VM permanently owned by an app; removal must respect that app's policy and storage requirements.
- New demand cancels shutdown before its irreversible point. Once shutdown is committed, preserve demand and wake capacity again.
- Routine autoscaler-managed worker deletion is authorized in the target design. This does not authorize deleting existing production workers now or destructive recovery of application data.
- Backup/restore proof, failure drills and redundancy remain deferred.

## Agreed storage boundary

The user accepts durable data tied to one physical host and reattached to replacement workers there. VM-owned OS disks, image caches and scratch are disposable. Durable application data must have a lifecycle independent of worker deletion. This is an ordinary storage architecture requirement, not a request to resume deferred redundancy or restore work.

The current local-path provisioner and cache PVs are tied to talos-worker-01; PostgreSQL placement is also tied to that worker. Those existing volumes and identities cannot be treated as autoscaler-owned disposable resources. The storage access and reattachment model must be selected before migrating those apps.

## Provider selection

The first prototype recommendation is upstream Cluster Autoscaler with an external gRPC adapter for the two independent Proxmox endpoints. Its justification is endpoint topology and the two fixed worker slots, not retaining VMs. Cluster API + Proxmox/Talos providers remain alternatives pending topology and controller-ownership compatibility. Physical-host wake, shutdown coordination and power-aware host selection remain separate requirements. No provider or production deployment is selected by this note.

## Tracker and evidence

GitHub synchronization completed: map92 and placement97 record the superseding create/delete decision; research104 marks its retained-worker recommendation obsolete. Storage proof105 passed and is closed. [IMM2 startup and SSH enrollment](imm2-power-control.md) are verified; automatic power/provisioning integration remains to be built.

Technical mechanics and ownership: [IaC autoscaling plan](homelab-autoscaling-iac.md).
