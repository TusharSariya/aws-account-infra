# Portable pilot implementation preflight - 2026-09-21

## Final retained configuration

**Accepted: 3-vCPU / 6-GiB VM with Kubernetes monitoring. Argo is absent.**
After Argo removal, run `kv-c602f4cdb9325e36` passed smoke, every 4/8/16 burst,
ten-minute sustained load, and cleanup. Its 60 samples over 987.2 seconds had
minimum available memory of 594.82 MiB on Ubuntu and 3153.91 MiB in Talos. Total
paging was 3.02 MiB; peak rate was 23.24 KiB/s, never reaching the sustained-paging
threshold. Every sampled monitoring Pod/controller was healthy, with zero OOMs.
See [final capacity](monitoring-final-20260921.json) and
[final workload report](monitoring-final-20260921.md).

The saved historical log/metric queries, dashboard data and PVC mappings passed
again after Argo removal. All five retired Ubuntu monitoring units are disabled
and inactive, all four lifecycle controllers are active, the secondary remains
paused, and `graphical.target` remains the default. See
[retained configuration](monitoring-retained-20260921.json).
The desktop remains temporarily stopped; starting it or rebooting Ubuntu requires
a capacity recheck. Argo CRDs remain but its workloads, scoped access resources,
Applications and repository configuration are absent.

Fresh private recovery state was captured at
`/home/tushar/pilot-recovery-20260921T232957Z`; all file checksums passed. It contains
etcd/configuration/credentials, not VM disks or PVC contents, and remains only on
the laptop. No archive, upload, Git push or PR was created. Creation/restore tooling
remains local. A fresh-disk/cross-host restore drill remains unverified.

Final offline validation: 27 Python tests, Ruff checks/format, manifest invariants
and ShellCheck passed. The full-stack capacity failure is preserved below; the
monitoring-only result does not certify Argo.

## Complete-stack result and Argo removal

Full-stack run `kv-f603f635f952c698` passed smoke, 4/8/16 bursts, ten-minute sustained
load and cleanup, but **failed capacity acceptance**: combined host paging stayed
at or above 64 KiB/s for 102.30 seconds, exceeding the unchanged 60-second limit.
The 60 samples had minimum available memory of 558.25 MiB on Ubuntu and 1922.04 MiB
in Talos. No monitoring/Argo OOMs or unhealthy sampled Pods/controllers occurred.
Total paging was 50.54 MiB. The final persistence stages were not run with Argo,
because capacity failed first. See [full-stack capacity](full-stack-failed-20260921.json)
and [workload report](full-stack-failed-20260921.md).

The authorized Argo-only fallback removed `access.yaml` resources and namespace
`pilot-argocd`, leaving CRDs intact. Verified monitoring remains on the 3-vCPU/6-GiB
VM. Its post-removal bounded load recheck passed as recorded above. Argo needs additional
host headroom or a separately verified change before another attempt; do not
reinterpret the passing workload suite as passing capacity.

## Continuation: local creation and recovery

VM archive/export and GitHub publishing are no longer requested. The replacement
is [local creation and restore tooling](../../vm/CREATE-RESTORE.md), with private
state backups kept outside Git. Public artifact hashes match upstream checksums;
offline qcow2 geometry and restore-machineconfig validation passed. The private
local recovery state at `~/pilot-recovery-20260921T2156` passed checksum verification.
No off-host copy or fresh-disk restore drill has been performed.

The admission failure reproduced with the original VM and host monitoring in
`kv-b2d2bf3b955ebd75`, and a single-16-Job reproduction also failed. Backoff reduction
alone did not pass. With autoscaler scan interval 2s and provisioning backoff 2s/5s,
`kv-3d21ac677f9577fa` passed all 4/8/16 bursts and cleanup at the unchanged deadline.
The larger VM/monitoring retry `kv-d151ad813cb294db` passed smoke, all 4/8/16 bursts,
ten-minute sustained load and cleanup. Across 60 samples, minimum available memory
was 1256.80 MiB on Ubuntu and 2038.91 MiB in Talos, with healthy Pods/controllers
and no monitoring OOMs. The paging policy passed; 306.72 MiB total paging included
a longest qualifying streak of 50.00 seconds, below the 60-second threshold.
See [capacity samples](monitoring-retry-20260921.json) and
[suite report](monitoring-retry-20260921.md).

The initial Argo gate refused installation: one of five samples had only
2044.66 MiB available, below the unchanged 2048 MiB requirement. No Argo resources
were changed. Monitoring-only acceptance subsequently passed logs after deletion, payload
exclusion, all 15 dashboard panels, firing/resolved alert delivery, replacement of
all five Pods, and a graceful VM restart with historical metrics/logs and PVC
mappings preserved. Identity, existing storage-proof volumes, worker state,
secondary pause state and graphical boot default were verified. All four lifecycle
services resumed; the five retired host monitoring units were disabled with their
data retained. See [monitoring acceptance](monitoring-acceptance-20260921.json).
A transient volume-metric refresh delay after Pod replacement exposed an immediate
assertion in the dashboard check; it now waits up to the existing 120-second bound
for all five claims, and the saved persistence proof passed before restart.
Post-restart Argo capacity passed all five samples, and the four active core
components became Ready. No repositories or Applications exist and all Argo
services are ClusterIP. See [passing Argo gate](argocd-gate-passed-20260921.json).
Complete-stack acceptance then ran as `kv-f603f635f952c698`; its failure and removal are recorded above. See
[initial Argo gate](argocd-gate-initial-20260921.json).

The new capacity policy checks for >=64 KiB/s combined paging continuously for
60 seconds, rather than requiring zero counter movement. All deltas are still
reported, and gaps >45 seconds or counter resets fail closed. Old failed reports
are preserved and are not retroactively passed.

## First migration acceptance result

The 3-vCPU / 6144-MiB migration booted successfully with the original system disk
and a separate 8 GiB monitoring disk. Original cluster, worker, controller and
storage-proof identities were verified. All five monitoring Pods were healthy on
retained local volumes. Log search after Pod deletion, payload exclusion, all 15
dashboard panels, verified TLS volume scraping, and alert firing/resolution passed.

**The bounded acceptance run failed. Rollback restored the original 2-vCPU / 4-GiB
VM, all five host monitoring services and the four lifecycle controllers. Argo was
not installed and no portable archive was created.** The existing gate was not relaxed.

Run `kv-5583ebeeda6e94d9` lasted 976.6 seconds with 60 capacity samples:

- Smoke and four-Job ten-minute sustained load passed, with final cleanup passing.
- The 16-Job burst failed the existing 120-second admission deadline for
  `kv-5583ebeeda6e94d9-burst-3-11` after usable capacity was observed.
- Minimum available memory was 1269.98 MiB on Ubuntu and 2147.06 MiB in Talos.
- All sampled monitoring Pods and controllers were healthy; no monitoring OOMs.
- Ubuntu swap counters increased by 406 pages read and 12812 pages written.
  This fails the existing zero-additional-swap gate, which is stricter than the
  plan's no-sustained-swapping wording. The admission failure independently prevents
  advancement. These observations do not establish the root cause of that timeout.

Evidence: [capacity samples](portable-load-20260921.json) and
[bounded-suite report](portable-load-20260921.md). Full raw observations remain
private on the laptop at `~/kubernetes-validation/runs/kv-5583ebeeda6e94d9`.
Rollback saves gate evidence under `~/.local/share/pilot-monitoring/migration/rollback-evidence-*`
before removing the active acceptance record.

Live fixes are versioned: serial is a virtio device property, the system disk has
explicit boot priority, and virtio free-page reporting lets Ubuntu reclaim unused
guest RAM. Cilium node-entity policies and a cluster-signed kubelet serving certificate
provide verified TLS for volume metrics. KVM private-group access survived a VM
restart. All 14 Python tests, Ruff checks/format and ShellCheck passed.

After rollback, cluster/worker/controller and original storage-proof identities were
verified again. Secondary pause state and `graphical.target` were preserved; the
desktop remains temporarily stopped. New Kubernetes monitoring deployments are
scaled to zero, service forwards disabled, and the five monitoring mount declarations
removed without wiping partitions. The detached monitoring qcow2 passed offline
`qemu-img check`. Host monitoring uses its original retained directories again.
The new disk, PVs/PVCs and versioned manifests remain available for diagnosis/retry.
All five host HTTP health checks returned 200 and `pilot_collection_success` was 1.
A fresh post-rollback smoke run `kv-234fd7556861bb74` passed, including cleanup.
See [recovery state](portable-rollback-20260921.json) and
[recovery smoke report](portable-rollback-smoke-20260921.md).
Talos supports [removing the mount configuration without removing disk data](https://docs.siderolabs.com/talos/v1.13/configure-your-talos-cluster/storage-and-disk-management/disk-management/user#remove-user-volumes).

Monitoring Pod-replacement persistence, final complete-stack restart acceptance,
Argo capacity, archive integrity and cross-host operation remain unverified.

## Earlier live resize attempt

The interactive preparation succeeded and KVM access was initially writable.
The migration saved its checkpoint and etcd snapshot, paused host services, and
shut Talos down cleanly. Before QEMU could restart, the named user ACL on `/dev/kvm`
was removed. Both the new launch and original-launch fallback failed the KVM access
check. **At that point the VM was stopped, with lifecycle reconciliation and host
monitoring paused. This has since been recovered as described above.** Neither disk was lost or overwritten. Offline
`qemu-img check` passed for the original system disk and the new 8 GiB monitoring disk.

The corrected helper grants a named private-group ACL and installs a runtime-only
udev rule to reapply it after device events. It does not change group membership or
graphical startup. Ruff, ShellCheck and all 13 tests passed after this correction.
The staged wizard now runs `migrate.py resume` as the normal user when it finds this
paused resize checkpoint. This validates both disks, starts the intended 3-vCPU /
6-GiB VM and verifies the original identity before resuming controllers.

Recovery command used:

```sh
ssh -t laptop-dell-studio 'bash ~/pilot-platform/vm/prepare-wizard.sh'
```

The remaining text records the earlier preflight, not the current running state.

## Earlier preflight

Status: implementation staged at `laptop-dell-studio:~/pilot-platform/`.
**Live resize, Kubernetes deployment, full-stack acceptance and export are pending.**
No archive has been produced. Previous host-monitoring evidence does not satisfy
the new Kubernetes or full-stack gates.

Read-only live inspection confirmed:

- Existing QEMU uses 2 vCPUs, 4096 MiB and `PROTOTYPE-control-plane.qcow2`.
- Guest MAC is `52:54:00:77:03:01`; API is `https://10.0.2.15:6443`.
- Management node `talos-v93-t3u` and current primary worker were Ready.
- The desktop was inactive; Ubuntu's default target remains `graphical.target`.
- About 2.1 GiB host memory was available before resize, and 65 GiB disk was free.
  These are observations, not proof of capacity with the larger VM.
- The pilot user cannot write `/dev/kvm`; the planned interactive sudo helper is
  required before proceeding. No sudo password was requested or collected.
- All five original host monitoring services and all four lifecycle services were
  still active after preflight. No VM disks or live Kubernetes objects were changed.

Verification completed:

- 13 Python tests passed, including retained storage/placement, resource budgets,
  restricted identities, log scope, and credential-free Argo core installation.
- Ruff check/format and `bash -n` passed; ShellCheck passed for all VM shell helpers.
- Kustomize rendered monitoring and Argo successfully. Existing Argo vendor
  checksums, management placement and 1536 MiB limit budget passed validation.
- Monitoring `kubectl apply --dry-run=server -k ...` passed against the actual
  pilot API, including restricted Pod admission, RBAC, storage and NetworkPolicy.
- The laptop's pinned native Prometheus/promtool, Loki, Alloy and amtool validated
  the new configs. Prometheus alert-rule tests passed against the migrated rules.
- Talos v1.13.9 validated the user-volume patch against the saved private machine
  configuration in a temporary file, without applying it. The patch selects only
  `PILOT-MONITORING-01` and excludes the system disk. ext4 is explicit for all five
  partitions, including Alertmanager's 256 MiB volume.
- Docker Registry manifests were fetched for all five existing release versions;
  their SHA-256 values were checked against registry response digest headers and
  recorded in `monitoring/kubernetes/images.json`.

Next user action:

```sh
ssh -t laptop-dell-studio 'bash ~/pilot-platform/vm/prepare-wizard.sh'
```

This runs only the temporary desktop-stop/KVM-ACL preparation. Then the agent can
continue `vm/migrate.py resize` and the ordered rollout in `pilot/README.md`.
Actual image startup, network-policy enforcement, TLS scraping, volume ownership,
capacity under load, restart persistence and cross-host import have not yet been
verified. Do not label the migration or export complete until the corresponding
live checks pass. Cross-host operation additionally requires a destination.
