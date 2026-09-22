> Raw agent report from the 2026-09-22 homelab adversarial review. It was produced against a local working tree behind `main`; several findings were fixed on `main` (`000bb81`) before filing. See [README.md](README.md) for the re-verified status and issue links.

# Adversarial review, Reviewer A: workload classes, AI/GPU, performance and latency

Scope: I only read files; nothing was run against the cluster. The Talos machine configs are not in the repo (they live in `~/.config/aws-account-infra/talos/...`), so kubelet settings could only be checked indirectly, through `scripts/homelab-config-validate.py`.

## 1. Verdict per goal

1. **Private and public apps: PARTIAL (outside my angle).** No ingress or LoadBalancer is installed. The README says "No ingress or LoadBalancer is installed" (`kubernetes/platform/main/README.md`). Access is only through port-forwards and Tailscale proxies.
2. **AI/GPU workloads that are scheduled, on-demand or persistent: NOT MET.** There is no GPU path in code, no KEDA on the Talos cluster, and no automatic wake. Plain CronJobs work only while the target host is awake. The repo says AI workloads are "dormant".
3. **Security-, performance- and latency-sensitive work: NOT MET on the performance and latency side.** There are no PriorityClasses, no CPU manager or NUMA settings, and no reserved resources. The control plane and CoreDNS run on a laptop over Wi-Fi.
4. **Adding heterogeneous workers: PARTIAL.** Adding a CPU worker is well rehearsed (worker-02 has joined). Adding a GPU or other heterogeneous worker has no working path: the docs point to the retired kubeadm/Ansible stack.
5. **Arbitrary workloads in a production-like way: NOT MET.** There is no admission-enforced workload-class contract, no preemption model, and no automated capacity lifecycle.

## 2. Findings

### Critical

**C1. The "on-invoke" and "scheduled" runtime policies have no implementation. Waking a host is fully manual.**
- **Evidence:**
  - `docs/runbooks/manual-server-sleep.md:4-5`: "no web portal, automatic wake or shutdown trigger, idle timer".
  - `talos-two-worker-operations.md:143-149`: "Do not deploy an IMM2 capacity controller yet."
  - `pilot/monitoring/evidence/tuned-bursts-20260921.md:17`: `app-url-demand | deferred`, `generalized-two-host-lifecycle | deferred`.
  - The cluster-autoscaler / ProvisioningRequest tuning in `pilot/controllers/autoscaler.py` targets only the retired laptop pilot.
- **Failure scenario:**
  - A CronJob marked "scheduled, required deadline" fires while the secondary is off. The Pod stays Pending until a human runs a runbook with about 9 steps each way (IMM power-on, PVE boot, VM start, Talos Ready, restore controllers).
  - Cold start is not measured at all (`performance-gates | deferred`). A realistic estimate is 5-15 minutes of hardware POST plus boot, against a "wake" budget of infinity.
  - The words defined in CONTEXT.md ("Workload runtime policy", "Physical scale-to-zero") have no admission label, controller or SLO behind them.
- **Fix:**
  - Define a required `homelab.tfdraw.dev/runtime-policy` label and enforce it with a ValidatingAdmissionPolicy.
  - Build the wake controller on the always-on host. It should use Kueue's ProvisioningRequest / AdmissionCheck, so that admission waits for "node Ready".
  - Measure cold-start p50/p95 and publish it as the scheduled/on-invoke SLO.

**C2. Kueue and other critical controllers are pinned to the worker that sleeps.**
- **Evidence:**
  - `placement/plan.py:22`: `"kueue-system": {"kueue-controller-manager"}` gets `worker-role: primary`. The same is true for local-path, Argo, CNPG and Tailscale.
  - The runbook step 7 stops Kueue when the primary sleeps.
- **Failure scenario:**
  - Kueue's job webhooks run with `failurePolicy: Fail` by default (upstream chart default; I did not confirm it against the live install). With the primary asleep, the webhook has no endpoint, so creating any `batch/v1` Job fails cluster-wide, including Jobs spawned by CronJobs.
  - So "secondary-only capacity" can't take batch work even though it is up.
  - Monitoring also dies, so alerting is blind (README: "Monitoring and GitOps stop when worker 01 sleeps").
- **Fix:**
  - Put stateless platform controllers (Kueue, admission, capacity controller, Alertmanager) on the always-on tier, or run them with 2 replicas across workers.
  - Alternatively, scope Kueue webhooks with namespace selectors so non-queued namespaces don't depend on them.

**C3. The control plane and CoreDNS run on a 2 vCPU / 4 GiB laptop VM that reaches the workers over Wi-Fi with proxy-ARP.**
- **Evidence:**
  - `platform/main-control-plane/launch.sh:12` (`-smp 2 -m 4096`).
  - `main-control-plane.md:68-70`: "explicit Wi-Fi proxy entries… no Wi-Fi Ethernet bridge".
  - `plan.py:16` pins `coredns` and `cilium-operator` to the control plane.
  - `talos-kubernetes-rebuild.md:146`: "Cilium VXLAN mode".
- **Failure scenario:**
  - Every Pod DNS lookup on either worker makes a VXLAN round trip over Wi-Fi to the laptop. Wi-Fi jitter (often 5-50 ms, with spikes of hundreds of ms under contention) adds directly to tail latency for every latency-sensitive service that resolves names.
  - etcd fsyncs go to the laptop's disk. Kubelet heartbeats and leases cross Wi-Fi, so a short roaming or AP blip marks nodes NotReady and starts evictions.
  - This is the opposite of what "latency-sensitive" needs.
- **Fix, in order of preference:**
  1. Wired Ethernet for the control-plane host, or a USB-Ethernet adapter as a minimum.
  2. Run CoreDNS replicas (or NodeLocal DNSCache) on each worker, so DNS survives a Wi-Fi failure and stays on the local node.
  3. Raise the node-monitor grace period and eviction timeouts to match the Wi-Fi reality.
  4. Measure etcd `wal_fsync` p99.

### High

**H1. GPU readiness is absent in code, and the documented GPU path is incompatible with Talos.**
- **Evidence:**
  - `talos-system-extensions.md:86`: "NVIDIA extensions: the GPU remains attached to the conventional Ubuntu GPU worker."
  - VM `hostpci: []` (secondary state).
  - No device plugin, GPU Operator, `RuntimeClass nvidia`, DRA ResourceClaim or GPU taint exists anywhere under `kubernetes/`.
  - The only GPU tooling is `ansible/roles/nvidia_gpu_host` and `kubernetes_node`, which are kubeadm-era roles.
  - `docs/plans/proxmox-kubernetes-worker.md:215, 316` still describes a kubeadm `k8s-worker-pve01` joining "at the repository-pinned Kubernetes version".
  - The roadmap (`:32-33`) claims "The repository already contains … GPU Operator". That is false for this cluster.
- **Failure scenario:**
  - The operator adds a GPU server and follows the docs, which lead to Ansible/kubeadm.
  - Joining a Talos control plane with kubeadm isn't supported. There is also no Talos worker image with the `nvidia-container-toolkit` and `nvidia-*-kernel-modules` extensions, and no `machine.kernel.modules` config.
  - Nothing does time-slicing or MIG, so one model monopolises the card.
- **Fix:**
  - Decide between a Talos GPU worker (Image Factory schematic with the NVIDIA open kernel modules and container-toolkit extensions, the `nvidia` RuntimeClass, the NVIDIA device plugin or DRA driver, and a `nvidia.com/gpu:NoSchedule` taint plus a capacity-class label) and a documented, supported non-Talos join.
  - Remove the roadmap's claims about Ansible-era components.

**H2. KEDA exists only as a plan for the retired stack.**
- **Evidence:** `docs/plans/keda.md:3` says "implemented as a pinned `cluster_addons` Helmfile release; pending apply". It installs via Ansible alongside "Cilium, MetalLB, Istio". ECR pulls depend on the `kubernetes_node` role installing binaries on nodes (`:58-64`), which is impossible on immutable Talos. Nothing about KEDA appears under `kubernetes/` or `platform/`.
- **Failure scenario:** On-invoke scale-from-zero, the harvester ScaledJobs, and ECR image pulls can't work on the actual cluster. `ecr-credential-provider` is listed as a *deferred* Talos extension.
- **Fix:** Rewrite `keda.md` for Talos and Argo, and prove the ECR credential-provider extension on a disposable node first.

**H3. Kueue is configured with no isolation or preemption model.**
- **Evidence:** `kubernetes/platform/two-worker/kueue.yaml`:
  - There is one ClusterQueue with `namespaceSelector: {}` (any namespace may point a LocalQueue at it).
  - There is no cohort, no `preemption`, no `fairSharing`, no WorkloadPriorityClass and no `waitForPodsReady`.
  - Flavors are ordered primary first, so batch fills the primary, where every protected stateful service and controller lives.
  - The README says "There is intentionally no AI queue", and it is not applied yet ("not installed by this repository").
- **Failure scenario:**
  - Kueue admits 31.5 CPU / 92 GiB of batch onto the primary. That is about 83% of a 38 vCPU / 112 GiB VM, before allocatable is subtracted.
  - Nexus, CNPG and Pi-hole then compete for CPU (no priority classes, so no scheduler preemption protects them).
  - Admitted work on a sleeping secondary sits Pending forever while holding quota.
- **Fix:**
  - Order flavors secondary first for batch.
  - Add a cohort with separate `latency` and `batch` ClusterQueues, plus WorkloadPriorityClasses.
  - Enable `waitForPodsReady` with requeue.
  - Restrict `namespaceSelector` to labelled tenant namespaces.

**H4. There is no resource-isolation layer for latency-sensitive work.**
- **Evidence:**
  - `grep` finds zero `PriorityClass` or `priorityClassName` anywhere in `kubernetes/`, `platform/` or `pilot/`.
  - Nothing sets `cpuManagerPolicy`, `topologyManagerPolicy`, `reservedSystemCPUs`, `systemReserved`/`kubeReserved` or hugepages.
  - `homelab-config-validate.py` checks only node labels.
  - The VMs use `numa=false`, `affinity=""` and 38 cores spread across what are probably two sockets on the IMM2 hardware. `proxmox-kubernetes-worker.md:112` says to "review NUMA", but the state shows it off.
- **Failure scenario:** An inference Pod and a batch build land on the same 38-vCPU VM. With CFS sharing, no pinning, and guest vCPUs spread across both host NUMA nodes without the guest knowing, memory bandwidth and p99 latency swing unpredictably. Under memory pressure, the kubelet evicts Burstable platform Pods before BestEffort batch work that has no priority.
- **Fix:**
  - Add PriorityClasses (platform-critical > latency > default > batch or preemptible).
  - Add Talos `machine.kubelet.extraConfig` with `systemReserved`, `kubeReserved`, `cpuManagerPolicy: static` and `topologyManagerPolicy: single-numa-node` on a dedicated latency node pool.
  - Enable Proxmox `numa=1` and align vCPUs to host sockets.

### Medium

**M1. Storage performance is unfit for model weights and datasets.**
- **Evidence:**
  - Disks are `iothread=false`, `discard=ignore`, `ssd=false`, `cache=none` on `local-lvm` (`live/proxmox/homelab/main.tf:45-55`, secondary state).
  - The secondary RAID CacheVault has failed, forcing write-through with the disk cache disabled (`talos-two-worker-operations.md:19-23`).
  - The secondary has no data disk. Its 320 GiB OS disk has to hold images, emptyDir and Kueue's 200 GiB ephemeral quota.
  - There is no RWX or shared storage, and NFS is excluded.
- **Failure scenario:**
  - A 40-70 GB model image or weight pull fills the secondary's ephemeral storage and triggers DiskPressure evictions of everything on that node.
  - Weights can't be shared between workers, so every cold start re-pulls from ECR over the WAN. SOCI/stargz are deferred.
- **Fix:**
  - Give the secondary a dedicated data or image volume.
  - Turn on `iothread` and `discard`.
  - Pick a weights cache: a local registry mirror (deferred Nexus cache), or a primary-hosted object store over the LAN.
  - Cap the Kueue ephemeral-storage quota well below actual free space.

**M2. The docs describe different topologies (my angle, briefly).**
- **Evidence:**
  - CONTEXT.md:8 says "three Talos virtual machines on Proxmox and one physically separate Ubuntu GPU worker".
  - The ops doc lists `talos-cp-01` on PVE.
  - The code and runbook move the control plane to the laptop.
  - `proxmox-kubernetes-worker.md` describes a 192 GiB kubeadm worker.
  - Nowhere do the Proxmox roots create or delete VMs on demand: `prevent_destroy = true`, and `homelab-secondary/variables.tf:32` hard-pins exactly one VM (38 vCPU / 112 GiB).
- **Failure scenario:** "Disposable worker VM" and "auto scaling" are only vocabulary. An agent or operator following CONTEXT.md will make wrong placement decisions.
- **Fix:** Reconcile CONTEXT.md with reality, and mark `proxmox-kubernetes-worker.md` and `keda.md` as superseded.

**M3. Heterogeneous onboarding has labels but no taints or capacity-class contract.**
- **Evidence:** Only `worker-role`, `stateless-compute` and `storage` labels are validated (`homelab-config-validate.py:77-90`). No taints are defined. The "Expansion worker" capacity class is not modelled in Kueue flavors.
- **Failure scenario:** A new GPU or fast-CPU node joins, and ordinary Pods without constraints fill it immediately.
- **Fix:** Every expansion worker should get a taint, a `capacity-class` label and a matching Kueue ResourceFlavor with tolerations.

### Low

**L1. Two small workers can't host inference and batch together in a production-like way.** The only mitigation is placement preference (`compute-template.yaml`: *prefer* primary). With the primary also the stateful and controller host, and the secondary able to sleep, the platform has no "persistent" capacity without a hard single point of failure.

## 3. Blockers vs nice-to-haves

**Blockers before calling this "production-like":**
- C1: automatic wake with a measured cold-start SLO, and runtime-policy admission.
- C2: platform controllers that stay up when the primary sleeps.
- C3: a wired control-plane link, and DNS kept on each node.
- H1: a chosen, implemented GPU path.
- H3: a Kueue model with priority and preemption.
- H4: PriorityClasses and kubelet reservations.

**Nice-to-haves:** CPU manager/NUMA pinning (needed only for real latency SLOs), SOCI/stargz, a model weight cache, MIG/time-slicing, and DRA.

## 4. Genuinely good

- Stable role labels are used instead of hostnames.
- The Kueue README honestly states the limits ("neither moves local PV data nor powers a PVE host").
- Placement tooling is UID-guarded, supports dry runs, and never touches claims.
- The sleep runbook fails closed (`maintenance.py check`) and forbids forced power-off.
- Talos extensions are digest-pinned, and gVisor is correctly scoped to workers with the user-namespace sysctl documented.
- Evidence files label timings as "no performance gate" instead of overclaiming.