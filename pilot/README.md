# Pilot VM: deployment and recovery

Implementation targets the **existing** `laptop-wifi-PROTOTYPE` cluster.
The VM is running at **3 vCPUs / 6 GiB with monitoring in Kubernetes**. Monitoring
passed bounded load, log/alert checks, Pod replacement and VM-restart persistence.
Argo core installed after its headroom gate passed, but full-stack acceptance failed
sustained host paging (102 seconds above the 64 KiB/s threshold). Argo was removed,
retaining verified monitoring. The post-removal capacity recheck passed, with
594.82 MiB minimum available on Ubuntu, no sustained paging, and no OOMs or
unhealthy sampled Pods/controllers. Historical data and final service state were
verified again. A private recovery backup was saved and checksummed on the laptop
at `~/pilot-recovery-20260921T232957Z`.
Argo CRDs remain, but no Argo workloads, Applications or repository credentials do.
The repository contains the VM recipe and recovery instructions; private disks and
cluster recovery state remain outside Git. No VM export was created.
See [migration verification status](monitoring/evidence/portable-preflight.md).
Existing host service data is kept for rollback; none was imported into the new
monitoring volumes.

The VM remains `10.0.2.15`, MAC `52:54:00:77:03:01`, node `talos-v93-t3u`, with
kube-system UID `507117e6-f7ed-4307-a016-4ecc9a28b519`. Launch configuration in
[vm/launch.sh](vm/launch.sh) retains the original system disk and uses 3 vCPUs,
6144 MiB RAM and a new sparse 8 GiB qcow2 disk, serial `PILOT-MONITORING-01`.
The system disk has explicit boot priority, and the original ISO remains attached.
Virtio free-page reporting returns unused guest RAM to Ubuntu without changing
the 6 GiB guest allocation; both the Talos driver and QEMU must support it.
The secondary stays intentionally paused. Storage-proof PVs keep their identities.

## Deployment and budgets

[Kustomize manifests](monitoring/kubernetes/kustomization.yaml) use single replicas,
control-plane node affinity/tolerations, non-root containers, health probes,
ClusterIP services and ingress/egress network policies. Images are locked to real
registry digests matching the existing releases in [images.json](monitoring/kubernetes/images.json).
Prometheus and Alloy use in-cluster service accounts. Alloy has scoped Pod/log read
access in only `prototype-slot` and `pilot-app`; Prometheus can read metrics only
from the named management kubelet. No administrative kubeconfig goes into a Pod. Cilium-specific policies allow only
Alloy's API connection and Prometheus's local kubelet metrics connection; Cilium's
CIDR rules do not match node identities. The control-plane kubelet uses a
cluster-signed serving certificate. Explicit maintenance verification approves only
a CSR authenticated as that node, with its exact DNS/IP SANs and serving usages.
No automatic certificate approver or elevated Pod identity is deployed.

| Component | CPU request | Memory request / limit | Retained local volume |
| --- | ---: | ---: | ---: |
| Prometheus | 150m | 128 / 384 MiB | 2 GiB |
| Loki | 100m | 128 / 384 MiB | 2 GiB |
| Grafana | 100m | 256 / 512 MiB | 1 GiB |
| Alloy | 100m | 64 / 256 MiB | 512 MiB |
| Alertmanager | 50m | 32 / 96 MiB | 256 MiB |

[Talos volumes](vm/user-volumes.yaml) select only the monitoring disk serial, use
ext4 (including the small Alertmanager volume), and mount under `/var/mnt/pilot-*`.
Static PVs are prebound, management-node-only, and `Retain`. Disk alerts use actual
filesystem capacity from the kubelet rather than the old host directories.
Prometheus, Loki and Alertmanager retain 48 hours; Prometheus also caps TSDB
retention at 1 GB. Retention is not a hard filesystem quota.

The small exporter and the four existing lifecycle services stay on Ubuntu.
The exporter preserves worker pause/desired/observed distinctions, reads only its
existing restricted reader identity, and sends **only sanitized fixed state words**
from lifecycle journals to Loki via a localhost service forward. Pods labelled
`monitoring.homelab/pilot-logs=true` contribute only `pilot-observe TOKEN` markers;
ordinary logs and payloads are dropped. The exporter listens on the private bridge
`10.0.2.2:9810` with verified TLS and a generated bearer token. Alert receipts remain
sanitized and bounded. Host private files and Kubernetes Secrets hold credentials.
The reader certificate still needs renewal through the legacy `reader()` helper
before its 30-day expiry; the bridge certificate needs renewal within one year.

## Rollout

Copy the pilot directory to the laptop (already staged during implementation):

```sh
rsync -az --exclude __pycache__ pilot/ laptop-dell-studio:~/pilot-platform/
```

One interactive step is necessary because `/dev/kvm` access requires sudo.
The user runs the prepared helper through SSH; no password is collected by the agent:

```sh
ssh -t laptop-dell-studio 'bash ~/pilot-platform/vm/prepare-wizard.sh'
```

The helper temporarily stops the desktop and restores KVM access through the pilot user's private group ACL. A rule under
`/run/udev/rules.d` reapplies that ACL on device events until Ubuntu reboots.
It does not change `graphical.target`, grant broad sudo rights, or run user code
as root. The remaining steps run as `tushar`, without sudo:

```sh
python3 ~/pilot-platform/monitoring/kubernetes/validate.py --native
python3 ~/pilot-platform/vm/migrate.py resize
python3 ~/pilot-platform/monitoring/kubernetes/install.py
python3 ~/pilot-platform/monitoring/measure.py
python3 ~/pilot-platform/monitoring/acceptance.py logs
python3 ~/pilot-platform/monitoring/acceptance.py dashboards
python3 ~/pilot-platform/monitoring/acceptance.py alerts
```

The resize saves private checkpoint files in `~/.local/share/pilot-monitoring/migration`,
including the original launch/network configuration, worker/controller state,
storage-proof identities and an etcd snapshot. It stops host monitoring and the
four reconcilers, shuts Talos down gracefully, retains the system disk, creates the
new disk and restarts. Original cluster/worker/PV identities and Kubernetes
controllers must recover before the previously active reconcilers resume. Pause
markers and desired-state files are never rewritten. Do not rerun `resize` after a
checkpoint exists: inspect the checkpoint and use the documented recovery paths.
After a completed rollback, `migrate.py retry` pauses services and gracefully
restarts the larger VM using the retained disk and original checkpoint. It never
recreates either disk.
For a stopped VM after a launch permission failure, `migrate.py resume` verifies
both disks offline and resumes the checkpointed resize without recreating disks.
The preparation wizard does this automatically when that checkpoint is present.

The bounded smoke, 4/8/16 bursts and four-Job ten-minute suite samples both host
and guest. Require at least 512 MiB available on both, no sustained host swapping,
healthy controllers and Pods, and no monitoring OOMs. Sustained swapping means at
least 64 KiB/s of combined swap-in/out traffic continuously for 60 seconds. Samples
more than 45 seconds apart or reset counters fail closed. All swap deltas remain
reported; isolated reclaim bursts are not sustained paging. This supersedes the
initial stricter zero-I/O rule and does not retroactively pass old evidence.
Failure stops advancement.
Only after monitoring passes:

```sh
# install runs the capacity check before changing resources
python3 ~/pilot-platform/argocd/bootstrap.py install
python3 ~/pilot-platform/monitoring/kubernetes/accept.py
```

Argo's gate requires a fresh Kubernetes-mode passing measurement, five management
samples over a minute, 2 GiB available VM memory and 900m CPU headroom, plus request
and host reserves. Core install uses the existing non-HA pinned release, management
placement, a closed default AppProject and the restricted pilot project. It needs
**no Git credentials** and creates **no Application**. No public ingress, automatic
sync, pruning or Git delivery is enabled. `accept.py` repeats the full bounded load
with Argo, proves log search after deletion, dashboard metrics, firing/resolved
alerts, replacement of every monitoring Pod and persistence of prior log/metric
samples and PVC mappings across a graceful VM restart. Only after success are the
five old monitoring units disabled; their old directories remain intact.

## Recovery

If monitoring or its acceptance fails and the API responds:

```sh
python3 ~/pilot-platform/vm/migrate.py rollback
```

This scales the new workloads to zero, waits for their Pods to stop, shuts down,
restores the original 2-vCPU/4-GiB launch file, restarts, verifies identity, restores
the original exporter code and host monitoring, and disables new port-forwards.
It removes only the five monitoring mount declarations, preserves all monitoring
and storage-proof data, saves failed gate evidence, and waits for host service health.
Never delete retained PVs to retry. If QEMU failed to launch and is **confirmed stopped**, use
`migrate.py restore-stopped` to restore the original launch file, then `rollback`
after the API returns to complete host-service restoration. If QEMU is running but
Talos cannot shut down, investigate its serial log; do not force-kill or copy a live
disk. A resize verification failure intentionally leaves reconciliation paused.

If only Argo fails, retain verified monitoring and remove only this Argo install:

```sh
K=~/talos-wifi-prototype/kubectl
C=~/talos-wifi-prototype/private/kubeconfig
$K --kubeconfig "$C" delete -f ~/pilot-platform/argocd/access.yaml --ignore-not-found
$K --kubeconfig "$C" delete namespace pilot-argocd --wait=true
```

Leave Argo CRDs intact. Run the monitoring capacity and acceptance checks again.
When Argo is absent, `monitoring/kubernetes/accept.py --monitoring-only` uses a fresh
passing Kubernetes-mode load report to verify monitoring logs, alerts, Pod
replacement and VM-restart persistence. It writes a separate
`monitoring-acceptance.json` with `argocd_included: false`; it cannot certify Argo
and refuses to run if the Argo namespace exists. A monitoring-only deployment is
useful but is not complete-stack acceptance.

## Private access and recovery

The installer creates supervised `pilot-forward-*` user units bound to `127.0.0.1`
for Prometheus 9090, Loki 3100, Alloy 12345, Grafana 3000 and Alertmanager 9093.
SSH forwards those ports to your workstation. Grafana uses username `admin` and the
existing private `~/.local/share/pilot-monitoring/private/grafana-password`.
For Argo, use a temporary `kubectl -n pilot-argocd port-forward --address=127.0.0.1
service/argocd-server 8443:443` with the pilot kubeconfig and an SSH tunnel.

The [creation and restore guide](vm/CREATE-RESTORE.md) is the supported recovery
path. `vm/prepare_disks.py` prepares empty disks and checksum-pinned public artifacts
in a new directory; `vm/recovery.py backup` saves private cluster metadata and
credentials without VM disks or an archive. The guide explains what can be recreated
from Git and which state still needs a private backup. No VM image upload, archive,
or publishing of private cluster state is included. The older `vm/export.py` and
`vm/IMPORT.md` remain unused historical tooling.

A fresh-disk recovery drill and an off-host backup location are still required
before calling disaster recovery proven. A normal VM restart is not that drill.

Restoring the desktop or rebooting Ubuntu requires the full capacity recheck.
Graphical startup remains unchanged; the temporary network and KVM ACL may also
need restoration after a host reboot.

## Next stage and local validation

Private repository credentials, image publication, the first Application and
Git-revert deployment/rollback proof remain next-stage work. Configure repository
access explicitly with `argocd/bootstrap.py repository --repository-token-file PATH`
using a private 0600 read-only token file. Only later apply
[argocd/application.yaml](argocd/application.yaml) after publishing/reviewing the
image and Git manifests. Existing application scripts/workflows remain unchanged.

```sh
python3 -m unittest discover -s pilot/monitoring/tests -v
python3 pilot/monitoring/kubernetes/render.py
python3 pilot/monitoring/kubernetes/validate.py
kubectl kustomize pilot/monitoring/kubernetes
uvx ruff@0.12.12 check pilot --exclude vendor
uvx ruff@0.12.12 format --check pilot --exclude vendor
```

Sources: [Talos user volumes](https://www.talos.dev/v1.12/talos-guides/configuration/disk-management/user/),
[live Talos 1.13 filesystem schema](https://docs.siderolabs.com/talos/v1.13/reference/configuration/block/uservolumeconfig),
and [Kubernetes volume metrics](https://kubernetes.io/docs/reference/instrumentation/metrics/).
The [legacy host guide](HOST-LEGACY.md) is historical rollback context,
not the current installation path.
