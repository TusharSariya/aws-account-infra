# Kubernetes-internals learning lab for the Talos homelab

Research date 2026-09-22. Versions verified against primary sources: Kubernetes 1.36 (2026-04-22, 70 enhancements) and 1.37 "Garhwal" (2026-08-26, 67 enhancements); 1.38 is in cycle (enhancements freeze 2026-09-29, GA 2026-12-16). Talos 1.14.0 bundles Kubernetes 1.37.0, containerd 2.3.4, etcd 3.7.1, kernel 6.18, enables NRI by default, and introduces reboot-free `CRICustomizationConfig` documents plus a `sandboxd` PID/mount namespace for the whole CRI/kubelet plane.

## Cross-cutting constraints for this cluster

- **Feature gates on Talos** go in `cluster.apiServer.extraArgs`, `cluster.scheduler.extraArgs`, `cluster.controllerManager.extraArgs` (`feature-gates: "A=true,B=true"`) and `machine.kubelet.extraArgs`/`extraConfig`. Each component only accepts its own gates; an unknown gate makes the API server fail to start. With one control plane, any apiserver arg change is a brief outage, so run gate experiments in a sandbox (section 3).
- **DaemonSets block host sleep.** Every node-level project (DRA driver, NRI plugin, CSI node plugin, runtime shim manager, KubeVirt `virt-handler`) ships a DaemonSet. Pin them with `nodeSelector` to a dedicated **lab worker** (see section 3) so the two production workers still sleep.
- **Pod Security.** Talos namespaces default to restricted; anything needing `hostPath`/privileged needs a namespace with `pod-security.kubernetes.io/enforce=privileged`. Keep such namespaces to the lab node.
- **No node shell.** Use `talosctl` (`etcd snapshot`, `logs kubelet`, `containers`, `read /proc/...`) instead of `kubectl debug node`.

## 1. Ranked shortlist

### 1. Out-of-tree scheduler plugin plus a second profile
- **Teaches:** scheduling framework extension points (PreFilter/Filter/Score/Reserve/Permit/Bind), scheduling vs binding cycles, `KubeSchedulerConfiguration` profiles, how Kueue's admission gates interact with scheduling.
- **Experiment:** fork `kubernetes-sigs/scheduler-plugins` (v0.34.x tracks upstream), write a Score plugin that prefers already-awake workers (read a node label your power coordinator sets) and a Permit plugin that holds pods until the coordinator reports "awake". Deploy as a *second* scheduler (`schedulerName`) so default scheduling is untouched; measure `scheduler_scheduling_attempt_duration_seconds` and plugin latency in Grafana. Compare with the Kueue AdmissionCheck you already have; the interesting finding is where scheduler-level power awareness beats queue-level.
- **Caveats:** none on Talos; a second scheduler is just a Deployment on the control plane node. Footprint tiny.
- **Maturity/effort:** framework GA since 1.19; 1-2 weekends.
- Sources: https://github.com/kubernetes/enhancements/tree/master/keps/sig-scheduling/624-scheduling-framework, https://github.com/kubernetes-sigs/scheduler-plugins

### 2. Native gang scheduling: Workload/PodGroup APIs (beta in 1.37)
- **Teaches:** how upstream is absorbing what Kueue, Volcano and coscheduling did out of tree: `Workload`/`PodGroup` `v1beta1`, all-or-nothing Permit-phase gating with timeout and resource release, workload-aware preemption, shared DRA ResourceClaims per PodGroup.
- **Experiment:** in a 1.37 sandbox enable `GenericWorkload` (replaces the earlier `GangScheduling`/`WorkloadAwarePreemption` gates) on apiserver and scheduler, create a PodGroup of N pods that cannot all fit, watch the scheduler hold, time out and release; then repeat with Kueue's gang semantics and compare events. Alpha 1.37 extras: `CompositePodGroup` (hierarchical groups), `WorkloadWithJob` (Job integration), `TopologyAwareWorkloadScheduling` (1.36 alpha).
- **Caveats:** beta but off by default; needs apiserver+scheduler gates, so sandbox only. Kueue's future integration with the native Workload API is the thing to track.
- **Maturity/effort:** beta; one weekend once the sandbox exists.
- Sources: https://kubernetes.io/blog/2026/09/08/kubernetes-v1-37-advancing-workload-aware-scheduling/, https://github.com/kubernetes/enhancements/blob/master/keps/sig-scheduling/4671-gang-scheduling/README.md

### 3. DRA end to end without hardware
- **Teaches:** ResourceSlice/ResourceClaim/DeviceClass, CEL selectors, structured parameters, kubelet plugin gRPC (NodePrepareResources), device taints (GA 1.37), the extended-resource bridge (GA 1.37, KEP-5004), partitionable devices, `ResourcePoolStatusRequest` (alpha 1.36).
- **Experiment:** deploy `kubernetes-sigs/dra-example-driver` (fake GPUs, 80Gi each) pinned to the lab node; write claims with CEL selectors; taint a device with `DeviceTaintRule` and watch eviction; request the same device via the old `example.com/gpu` extended-resource syntax; then fork the driver to add a NUMA attribute (`resource.kubernetes.io/numaNode`, 1.37). Try `kubernetes-sigs/dra-driver-cpu` to see `DRANativeResources` (1.36 alpha). This is the on-ramp for the future GPU server.
- **Caveats:** kubelet plugin needs `hostPath` under `/var/lib/kubelet/plugins*` and a privileged namespace; DaemonSet -> lab node only. Many sub-features are alpha and need gates (sandbox).
- **Maturity/effort:** core DRA GA since 1.34; 2-3 weekends.
- Sources: https://github.com/kubernetes-sigs/dra-example-driver, https://kubernetes.io/blog/2026/09/03/kubernetes-v1-37-dra-updates/, https://kubernetes.io/blog/2026/05/07/kubernetes-v1-36-dra-136-updates/

### 4. NRI plugins on containerd (Talos 1.14 enables NRI by default)
- **Teaches:** the CRI/OCI seam below the kubelet: NRI lifecycle hooks (RunPodSandbox, CreateContainer, UpdateContainer), OCI spec adjustment, cgroups v2 knobs, CPU/memory topology policies.
- **Experiment:** deploy `containers/nri-plugins` balloons or topology-aware policy on the lab node and watch `cpuset` pinning change with `talosctl read /sys/fs/cgroup/...`; then write a 100-line Go NRI plugin that injects an env var or a memory `low` limit based on a pod annotation. Compare with the kubelet's Memory QoS (beta 1.37) and Pod-Level Resource Managers (beta 1.37).
- **Caveats:** needs `/var/run/nri/nri.sock` via hostPath (privileged namespace). Talos 1.13 has NRI disabled; 1.14 enables it, and a `CRICustomizationConfig` toggles it without reboot. DaemonSet -> lab node.
- **Maturity/effort:** NRI stable in containerd 2.x; nri-plugins v0.14; one weekend.
- Sources: https://docs.siderolabs.com/talos/v1.14/configure-your-talos-cluster/images-container-runtime/containerd, https://github.com/containerd/nri, https://github.com/containers/nri-plugins

### 5. etcd storage and watch internals via talosctl
- **Teaches:** the `/registry` key layout, protobuf envelope encoding, resourceVersion and watch bookmarks, watch cache initialisation, storage-version migration and encryption at rest.
- **Experiment:** `talosctl etcd snapshot` the real control plane, open it offline with `etcdctl`+`etcd-io/auger decode`; find a Kueue Workload and inspect its stored version. Then, in the real cluster (safe, read-only): run `kubectl get --watch --output-watch-events` with `resourceVersion=0` vs a stale RV and observe `410 Gone`, bookmarks, and `apiserver_watch_cache_*`/`etcd_request_duration_seconds` in Grafana. Storage Version Migration is GA in 1.37: rotate an encryption key in the sandbox and trigger a `StorageVersionMigration` object. 1.37 also adds etcd `RangeStream` for lower-memory watch-cache init: compare apiserver RSS at restart between 1.36 and 1.37 sandboxes.
- **Caveats:** none; talosctl exposes snapshots without a shell. Never restore into the real cluster (`talosctl bootstrap --recover-from` is destructive).
- **Maturity/effort:** stable tooling; one weekend.
- Sources: https://github.com/etcd-io/auger, https://docs.siderolabs.com/talos/v1.11/build-and-extend-talos/cluster-operations-and-maintenance/disaster-recovery, https://kubernetes.io/blog/2026/08/26/kubernetes-v1-37-release/

### 6. In-process admission: CEL Validating and Mutating policies (Mutating GA in 1.36)
- **Teaches:** admission chain ordering, CEL cost budgets, `ApplyConfiguration` vs `JSONPatch` mutation, params/bindings, how policies remove the webhook network hop.
- **Experiment:** directly useful: a `ValidatingAdmissionPolicy` that rejects any Pod in a compute namespace lacking `kueue.x-k8s.io/queue-name` and explicit requests (the "unregistered pod blocks host sleep" rule), and a `MutatingAdmissionPolicy` that injects the queue label by namespace param. Compare `apiserver_admission_*` latency against an equivalent kyverno/webhook. Alpha 1.36 `ManifestBasedAdmissionControlConfig` (policies loaded from files before the apiserver starts) is a sandbox-only follow-up.
- **Caveats:** none; the real cluster on 1.36+ supports this today. Use `failurePolicy: Ignore` and audit mode first.
- **Maturity/effort:** GA; one evening to a weekend.
- Sources: https://kubernetes.io/docs/reference/kubernetes-api/admissionregistration/mutating-admission-policy-v1/, https://kubernetes.io/docs/tutorials/cluster-management/admission-policies/

### 7. Aggregated API server vs CRD
- **Teaches:** kube-aggregator proxying, `APIService` objects, discovery merging, front-proxy client certs (`requestheader-*`), why metrics-server is built this way, and the CRD trade-offs (Declarative Validation GA in 1.36).
- **Experiment:** deploy `kubernetes/sample-apiserver` (or a `k8s.io/apiserver`-based one) that serves a `PowerBudget` resource backed by its own storage; register an `APIService`; trace a request through the aggregator with `--v=8` on kubectl and apiserver audit logs. Then implement the same type as a CRD with CEL validation and compare storage, RBAC and discovery behaviour.
- **Caveats:** Talos already passes the aggregation front-proxy flags; nothing to change. Runs on control plane.
- **Maturity/effort:** stable; 1-2 weekends (Go).
- Sources: https://kubernetes.io/docs/tasks/extend-kubernetes/configure-aggregation-layer/, https://kubernetes.io/docs/concepts/extend-kubernetes/api-extension/apiserver-aggregation/

### 8. A controller that speaks Node Lifecycle Conditions (alpha 1.37)
- **Teaches:** controller-runtime/kubebuilder v4 (controller-runtime 0.25.x), informers and shared caches, workqueues, status conditions, leader election, and the new `NodeLifecycleConditions` gate (`MaintenancePlanned`, `DrainInProgress`, `Drained`, `GracefulNodeShutdownInProgress`...).
- **Experiment:** write a `NodePower` operator that mirrors your power coordinator's state into those conditions, and reads them back to decide wake/sleep. In 1.37 the gate is effectively a no-op (nothing in core reads the conditions; RBAC restriction and in-tree consumers are planned for 1.38 beta), so the real cluster can carry the conditions today with no gate. Add `StaleControllerConsistency`/`GracefulLeaderTransition` (alpha 1.36) in the sandbox to see informer staleness mitigation and leader handoff without restart.
- **Caveats:** none. Also the cleanest path to eventually replace the custom coordinator.
- **Maturity/effort:** framework stable, conditions alpha; 2 weekends.
- Sources: https://kubernetes.io/blog/2026/09/09/kubernetes-v1-37-node-lifecycle-conditions/, https://github.com/kubernetes-sigs/kubebuilder/releases

### 9. Hosted control planes: vCluster and Kamaji (with CloudNativePG as datastore)
- **Teaches:** what a control plane really is (apiserver+etcd/kine+controller-manager+scheduler as Pods), syncer vs real nodes, Konnectivity, kubelet bootstrap/join, certificate chains.
- **Experiment:** (a) `vcluster create` (v0.37.x, k8s distro, supports 1.34-1.36 tenants, 1.37 likely) on the real cluster, no privileged needs; inspect the syncer translating names. (b) Kamaji (26.9.x edge, adds 1.37 tenants) with a `kine` datastore on your CloudNativePG PostgreSQL; join a disposable Proxmox Talos VM as a tenant worker through Konnectivity. This is where feature-gate experiments live.
- **Caveats:** vCluster shares host CNI/kubelet, so it cannot test CNIs, runtimes or kubelet gates; Kamaji tenants with real Talos workers can. Kamaji release is "edge"; production artifacts are commercial.
- **Maturity/effort:** vCluster CNCF-certified, Kamaji CNCF-conformant; one weekend each.
- Sources: https://www.vcluster.com/docs/vcluster/manage/upgrade/supported_versions, https://github.com/clastix/kamaji

### 10. Cluster API with the community Talos providers
- **Teaches:** the Cluster API contract (v1beta2), bootstrap vs control-plane vs infrastructure providers, machine health checks, rolling upgrades, and how Node Lifecycle Conditions are meant to feed MachineHealthCheck.
- **Experiment:** run CAPI on the real cluster as management plane; use `sidero-community/cluster-api-control-plane-provider-talos` v0.8/0.9 (community-maintained after Sidero stopped development) plus the Proxmox infrastructure provider [unverified which CAPMOX release supports Talos images] or the KubeVirt provider (project 13) to stamp disposable lab clusters. Upgrade Kubernetes 1.36 -> 1.37 through CAPI and watch machine replacement.
- **Caveats:** management components run on the control plane; workload clusters on sleeping Proxmox hosts keep those hosts awake while they exist.
- **Maturity/effort:** CAPI stable; Talos providers community-maintained; 2 weekends.
- Sources: https://github.com/sidero-community/cluster-api-control-plane-provider-talos/releases/tag/v0.9.0, https://github.com/siderolabs/cluster-api-bootstrap-provider-talos

### 11. RuntimeClass zoo: gVisor and Kata on Talos
- **Teaches:** CRI runtime handlers, containerd shim v2, syscall interception (gVisor) vs micro-VM (Kata, cloud-hypervisor or `kata-qemu`), what "privileged" and hostPath mean under each.
- **Experiment:** build a Talos boot asset with `siderolabs/extensions` `gvisor` and `kata-containers` for the lab node only; add `RuntimeClass` objects; run the same benchmark (syscall-heavy, network-heavy) under runc/runsc/kata and compare; try `kata-container-snp` docs to understand confidential computing even without SEV.
- **Caveats:** gVisor needs `user.max_user_namespaces` sysctl raised in machine config; Kata needs KVM, so nested virtualisation must be enabled on the Proxmox VM (`cpu: host`). Extensions require a node upgrade/reboot; do it only on the lab node.
- **Maturity/effort:** both extensions maintained in the official repo; one weekend.
- Sources: https://github.com/siderolabs/extensions, https://github.com/siderolabs/extensions/tree/main/container-runtime/gvisor

### 12. WASM workloads: Spin extension + SpinKube
- **Teaches:** runwasi shim model, `RuntimeClass` handler `spin`, cold-start economics vs containers, how the kubelet is oblivious to what a "container" is.
- **Experiment:** add the `spin` extension (ghcr.io/siderolabs/spin), deploy Spin Operator, run an HTTP app and compare startup time and memory to an equivalent Go container; scale to hundreds of replicas on the lab node.
- **Caveats:** past Talos-specific runwasi failures (`/etc/hostname` on read-only fs, fixed in runwasi PR #327; extension issue #450) mean you should pin the extension version to your Talos release. DaemonSet-based Runtime Class Manager is unnecessary on Talos; the extension supplies the shim.
- **Maturity/effort:** SpinKube CNCF sandbox; one evening.
- Sources: https://github.com/containerd/runwasi, https://github.com/siderolabs/extensions/issues/450

### 13. KubeVirt on Talos, then a nested Talos cluster inside VMs
- **Teaches:** VMs as Pods (`virt-launcher`), CDI image import, live migration, Multus/bridge networking, and (with CAPK) the full "Kubernetes provisioning Kubernetes" loop.
- **Experiment:** follow the Sidero KubeVirt guide (local-path for CDI scratch; NFS with `nolock` because Talos has no `rpc.statd`); boot a Talos VM inside KubeVirt; then use `cluster-api-provider-kubevirt` to create a nested 1.37 cluster you can break freely.
- **Caveats:** nested virt on Proxmox required; `virt-handler` DaemonSet -> lab node; heavy RAM. Note Sidero's upcoming **Talos Hypervisor** (alpha demo TalosCon 15-16 Oct 2026, GA targeted Dec 2026, MPL-2.0 core) may make KubeVirt optional on Talos; worth watching but not yet usable.
- **Maturity/effort:** KubeVirt CNCF incubating; 2-3 weekends.
- Sources: https://docs.siderolabs.com/talos/v1.13/advanced-guides/install-kubevirt, https://www.siderolabs.com/talos-hypervisor, https://github.com/kubernetes-sigs/cluster-api-provider-kubevirt

### 14. Kubelet resource internals: in-place resize, pod-level resources, PSI, Pods API
- **Teaches:** the `/resize` subresource (GA 1.35), pod-level resources with in-place vertical scaling (GA 1.36), Memory QoS and Pod-Level Resource Managers (beta 1.37), PSI metrics (GA 1.36), the kubelet Pods gRPC API (`/var/lib/kubelet/pods/kubelet.sock`, beta 1.37), `CRIListStreaming` (alpha 1.36).
- **Experiment:** on the real cluster, resize a running Ollama pod's CPU without restart and watch cgroup values via `talosctl read`; enable `SchedulerPreemptionForPodResize` (alpha 1.37) in the sandbox and observe preemption for a resize; write a tiny client for the kubelet Pods API from a privileged lab pod; graph PSI pressure in Grafana during a Kueue burst.
- **Caveats:** `KubeletInUserNamespace` (rootless kubelet, beta 1.37) is not testable on Talos because Talos owns the kubelet [unverified whether Talos exposes it].
- **Maturity/effort:** mostly GA/beta; one weekend.
- Sources: https://kubernetes.io/blog/2025/12/19/kubernetes-v1-35-in-place-pod-resize-ga, https://kubernetes.io/docs/reference/node/kubelet-pods-api/, https://palark.com/blog/kubernetes-1-37-release-features/

### 15. (Sandbox-only) CNI/datapath swaps: Cilium native routing, kube-proxy replacement, netkit
- **Teaches:** eBPF service load balancing vs kube-proxy nftables (1.37 alpha moves kube-proxy default to nftables), VXLAN vs native routing, veth vs netkit devices, strict WireGuard (Cilium 1.19), Gateway API TCPRoute/UDPRoute (Cilium 1.20, Sept 2026).
- **Experiment:** in a disposable Talos cluster, install Cilium with `kubeProxyReplacement=true`, native routing, and `netkit` device mode; measure pod-to-pod throughput vs your VXLAN baseline.
- **Caveats:** Cilium 1.19.3/1.19.4 with kube-proxy replacement broke Talos host networking on 1.13.2 (issue #46010, unresolved at last check); Talos 1.14 ships kernel 6.18 so netkit should be available [unverified that CONFIG_NETKIT is enabled]. Never do this on the real cluster.
- Sources: https://github.com/cilium/cilium/issues/46010, https://www.cncf.io/blog/2026/09/14/cilium-1-20-gateway-api-externalauth-tcproute-udproute-eni-ipam-for-ipv6-and-more/

## 2. Suggested learning path

1. **Build the sandbox first** (section 3): `talosctl cluster create docker` on the laptop plus a "lab" Talos worker VM on one Proxmox host.
2. **Storage and watch internals** (project 5) on the real cluster: read-only, no risk, grounds everything else.
3. **CEL admission** (6): ships a real guardrail for the Kueue registration rule.
4. **Operator + Node Lifecycle Conditions** (8): informers, controllers, and the beginning of a Kubernetes-native power coordinator.
5. **Scheduler plugin** (1) then **native gang scheduling** (2) in the sandbox: compare against Kueue.
6. **DRA** (3) and **NRI** (4) on the lab node: the node-resource stack from apiserver to cgroup.
7. **Hosted control planes** (9): vCluster, then Kamaji with kine on CloudNativePG.
8. **Aggregated API server** (7): the last apiserver extension mechanism.
9. **Runtimes** (11, 12): gVisor, Kata, Spin on the lab node.
10. **VMs and CAPI** (13, 10, 15): nested clusters, CNI swaps, and the big-picture "Kubernetes managing Kubernetes".

## 3. Isolation strategy

| Layer | Tool | What it isolates | Limits |
|---|---|---|---|
| Control-plane flags, feature gates, admission, scheduler configs | `talosctl cluster create docker` (Talos in Docker on the laptop; 2 CPU/4 GiB minimum) or a Kamaji tenant control plane | apiserver/scheduler/KCM gates, etcd, upgrades 1.36->1.37 | Shares host kernel; no kubelet/CNI/runtime experiments |
| API-level multi-tenancy | vCluster on the real cluster | CRDs, RBAC, controllers, second schedulers, admission policies | Uses host CNI/kubelet; no DaemonSet/hostPath experiments |
| Node-level: DRA, NRI, CSI, runtimes, extensions | A dedicated **lab Talos worker VM** on Proxmox, tainted `lab=true:NoSchedule`, labelled `role=lab`, excluded from the power coordinator (or started only for lab sessions) | Everything needing hostPath, extensions, reboots | Keeps its Proxmox host awake while running; stop the VM when done |
| CNI/kube-proxy swaps, kubelet gates, KubeVirt nesting | Disposable full Talos cluster on Proxmox (OpenTofu + Talos provider, or CAPI) | Whole datapath and node stack | Highest footprint; both hosts may stay awake |

Practical rules: apply feature gates via machine-config patches to the sandbox only; keep lab namespaces out of Kueue but pinned to the lab node so they never touch sleeping workers; snapshot etcd (`talosctl etcd snapshot`) before any control-plane experiment even in the sandbox to practise recovery.

## 4. Frontier (late 2026)

- **1.37 alpha to watch:** `PodLevelCheckpointRestore` (KEP-5823, pod snapshots), `DRADeviceCompatibilityGroups` and `DRADerivedAttributes` (CEL-derived co-allocation keys), `SchedulerPreemptionForPodResize`, `CompositePodGroup`, `DefaultPodSysctls`, `APIServerWebhookAuthenticationToken` (apiserver authenticates to webhooks with short-lived JWTs), `CSIVolumeHealth`, kube-proxy nftables default (KEP-5343).
- **1.36 alpha still maturing:** `ShardedListAndWatch` (KEP-5866, targeting beta in 1.38: controllers receive only their hash-range of a collection), `PodInfoAPI` (beta 1.37), `CRIListStreaming`, `HPAScaleToZero` (beta 1.37), CBOR serialization (KEP-4222).
- **1.38 targets** (tracking board, subject to change): Node Lifecycle Conditions beta with RBAC and in-tree consumers; DRA Consumable Capacity alpha, Shared Consumable Capacity beta, Node Allocatable Capacity Reservation alpha (KEP-6352); Node System Partition alpha (KEP-5894); insecure UID/GID warnings (KEP-2172); CCM informer-based route controller (KEP-5237).
- **Ecosystem:** Talos Hypervisor (native VMs, alpha Oct 2026, GA Dec 2026) after Sidero's acquisition by Yardi; Talos 1.14 `sandboxd` isolation of the CRI plane; Cilium 1.20 (Gateway API ExternalAuth, TCP/UDPRoute); vCluster 0.37 with cross-cluster snapshot APIs; Kamaji 26.9 edge with 1.37 tenants.

Unverified items are marked inline; everything else was checked against the kubernetes.io release blogs, KEP repo, Talos 1.14 release notes and docs, and the respective project repositories.