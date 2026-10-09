**Start with controllers, API/watch behavior, and a real scheduler plugin.** These offer the most Kubernetes learning per weekend. Use disposable Talos VMs for experiments that reach the kubelet, runtime, storage mounts, or network datapath.

Research date: **2026-09-22**. Primary sources confirm [Kubernetes 1.37’s release](https://kubernetes.io/releases/1.37/) and [Talos 1.14’s release](https://github.com/siderolabs/talos/releases/tag/v1.14.0). Kubernetes 1.38 remains upcoming.

## Lab arrangement and isolation

Use your Proxmox hardware, but create **separate lab VMs, credentials, disks, and networks**. Keep the laptop’s 5-GiB control plane out of experimental load tests.

| Environment | Best use | Important boundary |
|---|---|---|
| **kind inside a disposable Linux VM** | Controllers, admission, API-server flags, scheduler builds, feature gates | Supports `featureGates`, `runtimeConfig`, kubeadm patches, and alternative CNIs. Nodes share the VM kernel. [Configuration](https://kind.sigs.k8s.io/docs/user/configuration/) |
| **Disposable Talos VMs** | Kubelet, CNI/eBPF, CSI, extensions, runtimes | Best match to your real environment. Allocate distinct virtual disks; snapshot before changing machine configuration. |
| **Talos-in-Docker inside that Linux VM** | Talos configuration and bootstrap exploration | Containerized Talos shares its host kernel; use full VMs for kernel/boot experiments. [Talos Docker guide](https://docs.siderolabs.com/talos/v1.13/platform-specific-installations/local-platforms/docker) |
| **vCluster on a disposable management cluster** | CRDs, controllers, admission, resource synchronization | Shared-node mode retains underlying kubelets/CNI/kernel and normally uses the host scheduler. Select etcd explicitly for etcd experiments; default storage is SQLite. [Architecture](https://www.vcluster.com/docs/vcluster/introduction/architecture/) |
| **Kamaji plus disposable tenant workers** | Hosted control planes, independent versions, multi-cluster lifecycle | Tenant control planes are Pods; workers join their tenant cluster separately. Start with Linux/kubeadm workers; Talos-worker integration is **[unverified]**. [Architecture](https://kamaji.clastix.io/concepts/) |

**Talos gates:** On 1.13, configure relevant control-plane components through their `extraArgs`, and kubelet configuration through machine config. On 1.14, prefer the new `KubeAPIServerConfig`, `KubeControllerManagerConfig`, and `KubeSchedulerConfig` documents. Enable only named gates on every required component, plus any required API version. Avoid blanket `AllAlpha`/`AllBeta`. [1.13 reference](https://docs.siderolabs.com/talos/v1.13/reference/configuration/v1alpha1/config), [1.14 changes](https://github.com/siderolabs/talos/releases/tag/v1.14.0).

**Power accounting:** Separate Proxmox VMs are invisible to your Kubernetes coordinator. Establish a bounded host-awake reservation before starting them. If experiments ever run on the real workers, every controller, translated vCluster Pod, helper Pod, and DaemonSet needs explicit accounting; a namespace or parent Job does not automatically provide it. Teardown must include infrastructure Pods before releasing the reservation. These are design implications of your supplied setup.

## Ranked shortlist

All experiments below target those isolated environments. Footprints are **additional to the lab control plane**. CPU/RAM budgets and solo effort are planning estimates **[unverified]**, not measured requirements. Third-party compatibility with your exact component versions is **[unverified]** unless specifically noted.

### 1. Build a controller that survives stale observations

**Learn:** informer caches, workqueues, reconciliation, optimistic concurrency, finalizers, ownership, and status.

**Experiment:** Extend `sample-controller` with a finalizer and status conditions. Delay event processing, kill it between child creation and status updates, and create concurrent writers. Measure duplicate actions, conflict retries, queue depth, and convergence time. Compare cached reads with direct reads.

**Fit:** kind or vCluster; no privilege or Talos extension. One controller, roughly 0.5 CPU/512 MiB. Controller and children require power accounting.

**Maturity/effort:** Established machinery; 2–4 days. [Sample controller](https://github.com/kubernetes/sample-controller), [1.36 staleness mitigation](https://kubernetes.io/blog/2026/04/28/kubernetes-v1-36-staleness-mitigation-for-controllers/).

### 2. Build a LIST/WATCH laboratory

**Learn:** resource versions, watch history, relisting, bookmarks, watch cache, and server-side partitioning.

**Experiment:** Generate synthetic objects; compare paginated LIST, streaming initialization, and ordinary watches. Disconnect a client until its version expires; verify recovery from `410 Gone`. Partition two informers using sharded LIST/WATCH; measure transferred bytes, client memory, API-server memory, and missed/duplicate reconciliation.

**Fit:** Dedicated kind API server; no node privilege. Budget 2 CPU/2–4 GiB; cap object count. Load generators are finite Jobs.

**Maturity/effort:** Core semantics established; `ShardedListAndWatch` alpha since 1.36; 2–4 days. [API concepts](https://kubernetes.io/docs/reference/using-api/api-concepts/), [KEP-5866 introduction](https://kubernetes.io/blog/2026/05/06/kubernetes-v1-36-server-side-sharded-list-and-watch/).

### 3. Admission: CEL policies versus webhooks

**Learn:** mutation/validation ordering, matching, parameter resources, failure policy, and admission’s place before persistence.

**Experiment:** Implement the same label/defaulting rule using a webhook and `MutatingAdmissionPolicy`. Add validation; deliberately time out the webhook and submit conflicting mutations. Compare accepted objects, errors, and request latency.

**Fit:** kind/vCluster; one small HTTPS service, no privilege. Restrict policies to lab resources. A webhook left on a sleeping worker becomes an admission dependency.

**Maturity/effort:** MutatingAdmissionPolicy stable in 1.36; 1–2 days. [Policy documentation](https://kubernetes.io/docs/reference/access-authn-authz/mutating-admission-policy/).

### 4. Write an actual scheduler-framework plugin

**Learn:** Filter/Score, Reserve/Unreserve, Permit, binding, scheduling queues, and rollback.

**Experiment:** Build a second scheduler with an artificial scarce-slot reservation plugin. Reject selected Permit requests; prove reservations are released. Introduce competing Pods and compare scores, scheduling latency, and starvation.

**Fit:** Two lab workers; explicit `schedulerName`; compile against the chosen Kubernetes version. No host privilege. Budget 1 CPU/1 GiB. Scheduler infrastructure stays awake; workload admission remains separate from placement.

**Maturity/effort:** Framework stable; custom Go interfaces require version matching; 4–7 days. [Scheduling framework](https://kubernetes.io/docs/concepts/scheduling-eviction/scheduling-framework/).

### 5. DRA without buying a GPU

**Learn:** DeviceClass, ResourceSlice, ResourceClaim, scheduler allocation, and kubelet preparation.

**Experiment:** Fork the example driver’s fake-device profile. Publish heterogeneous devices, request CEL-selected devices, share claims, exhaust capacity, and fail preparation. Trace claim allocation through Pod startup; measure allocation and cleanup latency.

**Fit:** kind first, disposable Talos second. Node plugin needs kubelet/CDI integration and host mounts. Budget 1 CPU/1 GiB plus tiny consumers. Driver DaemonSets require continuous accounting.

**Maturity/effort:** Core DRA stable since 1.34; individual extensions vary; 3–5 days. [Example driver](https://github.com/kubernetes-sigs/dra-example-driver), [1.37 DRA updates](https://kubernetes.io/blog/2026/09/03/kubernetes-v1-37-dra-updates/).

### 6. Native workload-aware scheduling versus independent Pods

**Learn:** native Workload/PodGroup APIs, gang scheduling, group preemption, and topology.

**Experiment:** On 1.37, submit a group that barely cannot fit. Compare independent scheduling with gang behavior, then introduce higher-priority groups. Record partial starts, victims, and placement decisions.

**Fit:** Two small lab workers; roughly 2 CPU/2 GiB of test workloads. `GenericWorkload` is beta **but disabled by default**; enable across required components. Native Workload is distinct from Kueue’s CRD. Test Kueue interoperability separately.

**Maturity/effort:** Core group scheduling/preemption beta in 1.37; 2–4 days. [Release-specific guide](https://kubernetes.io/blog/2026/09/08/kubernetes-v1-37-advancing-workload-aware-scheduling/).

### 7. CRD conversion and storage-version archaeology

**Learn:** served versus stored versions, conversion webhooks, schema evolution, and persistence.

**Experiment:** Store v1alpha1 objects, introduce v1beta1 with renamed fields, then migrate storage. Inspect only the disposable API server’s etcd records. Break conversion and observe LIST/update failures; demonstrate why changing the storage version does not rewrite existing objects automatically.

**Fit:** kind with etcd; one conversion service, about 1 CPU/1 GiB. No host extension. Conversion service must remain available until teardown.

**Maturity/effort:** CRD versioning established; in-tree storage migration stable in 1.37; 2–3 days. [CRD versioning](https://kubernetes.io/docs/tasks/extend-kubernetes/custom-resources/custom-resource-definition-versioning/), [migration graduation](https://kubernetes.io/blog/2026/08/31/kubernetes-v1-37-storage-version-migration-ga/).

### 8. Implement an aggregated API server

**Learn:** APIService discovery, front-proxy trust, delegated authorization, and extension storage.

**Experiment:** Run `sample-apiserver`, register a resource, and compare its request path with a CRD. Break its serving certificate, delegation RBAC, and backend availability. Observe APIService conditions, discovery behavior, and request failures.

**Fit:** kind or hosted control plane; separate extension datastore; about 1 CPU/1–2 GiB. No node privilege. Extension server/datastore are persistent sleep blockers.

**Maturity/effort:** Established extension mechanism; sample is educational; 3–5 days. [Sample](https://github.com/kubernetes/sample-apiserver), [aggregation authentication](https://kubernetes.io/docs/tasks/extend-kubernetes/configure-aggregation-layer/).

### 9. CSI lifecycle fault laboratory

**Learn:** provisioning versus node mounting, sidecars, retries, snapshots, and deletion ordering.

**Experiment:** Use the sample host-path CSI driver. Interrupt provisioning and node publishing, restart plugins, then inspect retries and orphan cleanup. Snapshot/restore a tiny dataset and compare contents.

**Fit:** Disposable Talos worker with scratch disk. Requires privileged mounts and kubelet-directory access; budget 1–2 CPU/2 GiB. Existing local-path provisioner is not a substitute for this CSI experiment. Node plugins and sidecars block sleep.

**Maturity/effort:** CSI established; this driver explicitly non-production; 3–5 days. [SIG Storage sample driver](https://github.com/kubernetes-csi/csi-driver-host-path).

### 10. Kubelet resource enforcement and NRI

**Learn:** requested resources versus cgroup enforcement, CRI lifecycle, and runtime-side adjustment.

**Experiment:** First compare memory pressure with MemoryQoS reservation/throttling settings. Then write an NRI plugin that logs lifecycle callbacks and injects a harmless environment variable. Compare PodSpec with effective container configuration and measure startup overhead.

**Fit:** Disposable VM; cgroup inspection and runtime socket access required. Talos NRI enablement for your exact image is **[unverified]**; begin in Linux/kind. Budget 2 CPU/4 GiB; plugin stays accounted.

**Maturity/effort:** MemoryQoS beta in 1.37; gate enabled does **not** activate reservation/throttling by itself. NRI is containerd extensibility; 4–7 days. [MemoryQoS](https://kubernetes.io/blog/2026/09/14/kubernetes-v1-37-memory-qos-graduates-to-beta/), [NRI](https://github.com/containerd/nri).

### 11. Reconstruct the Service datapath

**Learn:** CNI versus Service routing, EndpointSlice reconciliation, conntrack, NAT, and eBPF service maps.

**Experiment:** Recreate three disposable configurations: kube-proxy iptables, nftables, and Cilium replacement. Remove endpoints during persistent connections; compare new connections, existing flows, source addresses, rules/maps, and recovery time.

**Fit:** Two Talos VMs; 1–2 CPU/2 GiB overhead. Cilium needs capabilities and Talos’s existing cgroup mount. Follow its documented bootstrap settings. Networking DaemonSets remain until cluster destruction.

**Maturity/effort:** Established implementations; 3–5 days. [Cilium on Talos](https://docs.cilium.io/en/stable/installation/k8s-install-helm/), [kind network configuration](https://kind.sigs.k8s.io/docs/user/configuration/).

### 12. Compare virtual and hosted control planes

**Learn:** resource translation, control-plane ownership, tenant storage, and multi-cluster failure boundaries.

**Experiment:** Create two vClusters, inspect translated Pods, and stop one syncer. Then host two Kamaji tenants and restart one control plane. Measure which workloads continue and which API operations stop.

**Fit:** Disposable management cluster; roughly 4–8 CPU/8–16 GiB total. Choose dedicated lab datastores. Management Pods, tenant workers, and translated Pods all need an awake window.

**Maturity/effort:** Maintained projects; integration exercise, 4–7 days. [vCluster architecture](https://www.vcluster.com/docs/vcluster/introduction/architecture/), [Kamaji datastore model](https://kamaji.clastix.io/concepts/datastore/).

### 13. KubeVirt: follow a VM through Kubernetes

**Learn:** VM/VMI reconciliation, virt-launcher Pods, device allocation, storage, and migration eligibility.

**Experiment:** Boot a tiny VM, delete its launcher, inspect recovery, then examine why a local-PVC VM cannot use ordinary shared-storage migration. Attempt migration only after satisfying documented prerequisites.

**Fit:** Disposable Talos VMs; expose nested KVM through Proxmox. Budget 4 CPU/8 GiB plus disks. Prefer the healthy storage host. Virt-handler and guest Pods require accounting.

**Maturity/effort:** Established project with Talos documentation; 3–5 days. [Talos guide](https://docs.siderolabs.com/talos/v1.13/advanced-guides/install-kubevirt), [migration limitations](https://kubevirt.io/user-guide/compute/live_migration/).

### 14. RuntimeClass and sandbox lifecycle

**Learn:** runtime-handler selection, sandbox startup, syscall compatibility, and controller-managed allocation.

**Experiment:** Run identical small workloads under runc and gVisor; compare startup, filesystem behavior, and unsupported operations. Add Agent Sandbox and inspect claim adoption and warm-pool replenishment.

**Fit:** Disposable Talos with its gVisor extension; roughly 2 CPU/2–4 GiB. Start with zero warm-pool capacity: prewarmed Pods conflict directly with idle sleep.

**Maturity/effort:** Established RuntimeClass/gVisor; newer Agent Sandbox project; 2–4 days. [Talos extensions](https://github.com/siderolabs/extensions/blob/main/README.md), [Agent Sandbox](https://github.com/kubernetes-sigs/agent-sandbox).

### 15. WASM through containerd’s CRI path

**Learn:** OCI packaging, containerd shims, RuntimeClass, and kubelet assumptions about containers.

**Experiment:** Run a finite WASI program through runwasi, then a Linux equivalent. Compare image size, startup, logs, exit status, and resource reporting; intentionally select a missing runtime handler.

**Fit:** Linux/kind first; custom Talos shim extension compatibility **[unverified]**. Budget 1 CPU/1 GiB. Keep workloads finite and remove runtime helpers afterward.

**Maturity/effort:** Emerging containerd subproject; 2–4 days in kind, longer for Talos packaging. [Architecture](https://runwasi.dev/developer/architecture.html), [Kubernetes quickstart](https://runwasi.dev/getting-started/quickstart.html).

## Suggested learning path

1. Establish disposable VM templates and bounded host-awake sessions.
2. Build the controller in **#1**.
3. Explain its observations using **#2**, then persistence using **#7**.
4. Add admission **#3** and aggregation **#8**.
5. Implement scheduler **#4**, then native groups **#6**.
6. Follow allocation onto nodes with DRA **#5** and CSI **#9**.
7. Explore enforcement/datapaths through **#10–11**.
8. Finish with control-plane tenancy **#12**, then choose VM, sandbox, or WASM **#13–15**.

## Frontier to track

- **1.37 scheduling:** CompositePodGroup **KEP-6012** and resize preemption **KEP-5836** are alpha. Extend #6 with hierarchical groups or resizing that requires preemption. [KEP index](https://www.kubernetes.dev/resources/keps/)
- **1.37 DRA:** shared consumable capacity **KEP-5941**, device compatibility groups **KEP-5963**, and derived attributes **KEP-6080** are alpha; useful fake-device extensions to #5. [DRA update](https://kubernetes.io/blog/2026/09/03/kubernetes-v1-37-dra-updates/)
- **1.38 targets:** pod checkpoint/restore **KEP-5823**, per-Pod PID limits **KEP-6063**, and CRI list streaming **KEP-5825** appear with 1.38 milestones. These are tracking targets; eventual shipment is **[unverified]**. [Upstream KEP index](https://www.kubernetes.dev/resources/keps/)
- **Emerging combination:** Agent Sandbox lifecycle controllers plus alternative runtimes expose a useful architectural split: Kubernetes allocates and reconciles sandboxes; the runtime supplies execution isolation. [Project](https://github.com/kubernetes-sigs/agent-sandbox)