# Distributed-systems learning lab for the Talos homelab — research report

Scope: web research only, primary sources where possible (release pages, project docs, k8s blog). Nothing on the cluster was touched. Claims I could not confirm are tagged **[unverified]**.

## 0. Cluster-specific ground rules that shape every pick

- **Pod Security**: Talos enforces PSA `baseline` on every namespace except `kube-system` (`privileged`). Anything needing `privileged`, `hostPID`, or hostPath must live in a namespace labelled `pod-security.kubernetes.io/enforce=privileged` ([Talos docs](https://www.talos.dev/v1.10/kubernetes-guides/configuration/pod-security/)). This is the main "Talos caveat" for chaos tooling.
- **Sleeping workers + Kueue**: anything long-running (DB clusters, Jepsen runs) must be a Kueue-admitted Job/Pod with explicit requests, or it blocks host sleep. Prefer time-boxed Jobs (Argo Workflows already installed) over Deployments. The control-plane VM (2 vCPU/5 GiB, Wi-Fi) must not host experiments.
- **Talos 1.14 relevant bits**: Kubernetes 1.37.0, containerd 2.3.4, Linux 6.18.48, NTS enabled by default for time sync, Secure Boot images drop `lockdown=confidentiality` "improving eBPF tooling compatibility", new `VethConfig`/`VXLANConfig` documents, NRI enabled by default ([v1.14.0 release](https://github.com/siderolabs/talos/releases/tag/v1.14.0)). Note that Cilium on Talos 1.12/kernel 6.18 had a repeatable eBPF verifier issue ([talos#12726](https://github.com/siderolabs/talos/issues/12726)) — check status before adding more eBPF loaders.

## 1. Ranked shortlist (12)

### 1. Maelstrom + Gossip Glomers (write your own Raft/CRDT/log, checked by Jepsen)
- **Teaches**: message passing, gossip, unique IDs, G-counters (CRDTs), Kafka-style totally ordered logs, totally-available transactions; linearizability checking via Knossos/Elle. Maelstrom workloads: lin-kv, txn, CRDT sets/counters, broadcast, kafka, unique-ids ([Maelstrom](https://github.com/jepsen-io/maelstrom)).
- **Experiments**: the six Fly.io challenges (Echo → Unique ID → Broadcast → G-Counter → Kafka log → Txn KV) ([fly.io/dist-sys](https://fly.io/dist-sys/)). Run each as an Argo/Kueue Job that executes `maelstrom test -w broadcast --nemesis partition ...`; measure messages/op, latency percentiles, and the checker's `:valid?` result under partition/latency nemeses. Stretch: implement Raft for `lin-kv` and diff against MIT lab tests.
- **Talos/K8s**: none. Single-process JVM; ~1-2 GiB. Perfectly Kueue-shaped (batch, finite).
- **Maturity**: Maelstrom 0.2.4 (Dec 2024, bundles Jepsen 0.3.7); Jepsen 0.3.14 (Sep 2024) ([releases](https://github.com/jepsen-io/maelstrom/releases), [jepsen releases](https://github.com/jepsen-io/jepsen/releases)). Slow but stable. Effort: 2-6 weekends for all six.

### 2. MIT 6.5840 labs (Raft → KV → sharded KV) run as cluster Jobs
- **Teaches**: leader election, log replication, persistence, snapshots, linearizable KV, reconfiguration/sharding — the canonical curriculum ([Spring 2026 Raft lab](https://pdos.csail.mit.edu/6.824/labs/lab-raft1.html)).
- **Experiments**: run `go test -race -count=100` fan-out as a Kueue Job array on the big workers (cheap parallelism the laptop lacks); collect flaky-test rates per lab; then re-run the same Raft binary as real pods (challenge 1's Maelstrom harness) to compare simulated vs. real network.
- **Talos/K8s**: none. Footprint: CPU-bound bursts, fits sleep model well.
- **Maturity**: actively taught (Spring 2026). Effort: high (weeks) but highest learning density.

### 3. Chaos Mesh (fault injection layer for everything below)
- **Teaches**: partitions, packet loss/delay/reorder, pod/container kill, CPU/memory stress, clock skew (TimeChaos), IO latency/faults; observable failure detection and timeouts.
- **Experiments**: NetworkChaos `partition` between an etcd/NATS/CNPG minority and majority; measure leader-election time, client error window, and Prometheus `*_leader_changes_seen_total`; TimeChaos +500 ms on one CockroachDB/etcd member and watch clock-offset alarms.
- **Talos/K8s caveats**: chaos-daemon is a privileged DaemonSet with hostPID/hostPath (namespace must be PSA privileged). Set `chaosDaemon.runtime=containerd` and `socketPath` to Talos's CRI socket (`/run/containerd/containerd.sock` is the Chaos Mesh default; **[unverified]** that Talos exposes the kubelet CRI containerd at exactly that path — verify on one node before trusting pod-kill). TimeChaos uses ptrace on PID 1 of the container; KernelChaos needs `CONFIG_BPF_KPROBE_OVERRIDE` and bpfki — **[unverified]** on Talos's kernel; treat KernelChaos as unavailable ([Chaos Mesh kernel docs](https://chaos-mesh.org/docs/simulate-kernel-chaos-on-kubernetes/)). Because the daemon runs on every worker, it wakes/keeps nothing awake by itself, but experiments targeting sleeping workers will hang until Kueue wakes them — schedule chaos from inside the same Kueue-admitted workflow.
- **Maturity**: v2.8.4 (Aug 2026), e2e tested to K8s 1.35.2 — not yet 1.36/1.37 ([releases](https://github.com/chaos-mesh/chaos-mesh/releases)). CNCF incubating. Effort: 1 weekend to install and scope. Alternative: LitmusChaos 3.30.x, monthly releases through H1 2026 ([CNCF update](https://www.cncf.io/blog/2026/08/06/litmuschaos-q1-q2-2026-update-community-contributions-and-project-progress/)) — heavier UI/DB stack; Chaos Mesh is the leaner pick.

### 4. Lab etcd cluster + its own robustness/linearizability framework
- **Teaches**: Raft in a real system, linearizability vs. serializability of reads, watch guarantees, lease/TTL semantics, learner members, defrag/compaction.
- **Experiments**: 3-5 member etcd StatefulSet in `lab-etcd`; drive `etcd/tests/robustness` (traffic + failpoints + linearizability + watch-guarantee check, "inspired by Jepsen") ([README](https://github.com/etcd-io/etcd/blob/main/tests/robustness/README.md)); overlay Chaos Mesh partitions; measure `etcd_server_leader_changes_seen_total`, `etcd_disk_wal_fsync_duration_seconds`, and stale reads with `--consistency=s`. Note the etcd project ran 830 wall-clock hours in Antithesis simulating ~4.5 years and found new bugs ([etcd blog](https://etcd.io/blog/2025/autonomus_testing_with_antithesis/)).
- **Talos/K8s**: none privileged. Storage: local-path is fine; deliberately place one member on the slow RAID-cache-failed host and measure fsync tail latency — a genuine lesson. Footprint small (<2 GiB). Must not be the Talos control-plane etcd.
- **Maturity**: etcd 3.6 GA (May 2025), 3.7.x ships in Talos 1.14. Effort: 1-2 weekends.

### 5. NATS JetStream (Raft-replicated streams, freshly Jepsen-tested)
- **Teaches**: replicated logs, stream/consumer Raft groups, at-least-once vs. exactly-once semantics, catch-up after stable-storage loss.
- **Experiments**: 3-node JetStream with R3 streams; NetworkChaos partition the leader; measure publish ack latency, duplicate/lost messages with a sequence-checking client; then read [Jepsen: NATS 2.12.1](https://jepsen.io/analyses/nats-2.12.1) and try to reproduce a reported anomaly. 2.12 added "empty votes" for nodes that lost stable storage ([2.12 release](https://nats.io/blog/nats-server-2.12-release/)); 2.12.12 stopped Raft nodes voting after write errors — inject IOChaos and observe.
- **Talos/K8s**: Helm chart, no privileges, <1 GiB. Six-month release cadence, Apache-2.0.
- **Effort**: 1 weekend. (Alternative: Redpanda Community — BSL source-available, heavier; Kafka-API learning if desired ([licensing](https://docs.redpanda.com/current/get-started/licensing/overview/)).)

### 6. CloudNativePG lab instance (replication, failover, split-brain avoidance)
- **Teaches**: async vs. sync replication, WAL shipping, failover/promotion, fencing, replication lag as a consistency knob.
- **Experiments**: separate 3-instance CNPG cluster in `lab-pg` (not the platform one); partition primary from replicas and from the operator; measure `cnpg_pg_replication_lag`, time-to-promote, and whether a writer connected through the old primary loses commits under `synchronous_commit=off` vs `on`.
- **Talos/K8s**: already installed; zero new privileges; ~2-3 GiB. Excellent first "real" system.

### 7. CockroachDB (Enterprise Free) — ranges, Raft per range, HLC, clock skew
- **Teaches**: multi-Raft, range splits/rebalancing, hybrid logical clocks, serializable isolation, read-timestamp uncertainty windows.
- **Experiments**: 3-node cluster with local-path PVs; TimeChaos +/- 300 ms on one node and watch it self-eject on `--max-offset` violation; kill a node and time range up-replication; run a Jepsen-style bank workload (Maelstrom `txn` client or `cockroach workload bank`) under partitions.
- **Caveats**: licence is source-available "CockroachDB Software License", free under $10M revenue, telemetry cannot be disabled on free tier ([licensing FAQ](https://www.cockroachlabs.com/docs/stable/licensing-faqs)). Needs several GiB RAM; fine on the big workers, must be Kueue-registered.
- **Effort**: 1-2 weekends. (FoundationDB via operator v2.37.0, Sept 2026 ([release](https://github.com/FoundationDB/fdb-kubernetes-operator/releases/tag/v2.37.0)) is the deeper alternative but heavier to operate.)

### 8. Formal specs: TLA+ (TLC/Apalache) and FizzBee, for the protocols you implement
- **Teaches**: safety vs. liveness, invariants, fairness, model checking as design tool; FizzBee adds implicit fault injection (crashes/message loss) in the checker ([FizzBee](https://github.com/fizzbee-io/fizzbee), [fault injection tutorial](https://fizzbee.io/design/tutorials/fault-injection/)).
- **Experiments**: spec your Gossip-Glomers Raft or 2PC in FizzBee first, find a counterexample, then reproduce that exact trace in Maelstrom with a targeted nemesis. Run TLC/Apalache as CPU-heavy Kueue Jobs on the 38-vCPU workers (TLC scales with workers).
- **Maturity**: Apalache now under the TLA+ Foundation (Linux Foundation); a `model-checker-hardening` differential-testing effort is active in 2026 ([repo](https://github.com/tlaplus/model-checker-hardening)). FizzBee is young, single-process, Apache-licensed. Effort: 2-4 weekends.

### 9. Deterministic simulation testing in Rust: turmoil / madsim / mad-turmoil
- **Teaches**: why DST finds bugs chaos can't: single-threaded simulated hosts, seeded RNG, simulated time, replayable failures (partitions, torn writes).
- **Experiments**: port your Raft to Rust on `turmoil`, seed-sweep 10k seeds as a Kueue Job array; on failure, replay the seed locally. Compare bug-finding rate vs. Chaos Mesh on the same protocol. S2.dev's `mad-turmoil` adds madsim-style libc overrides for time/entropy ([S2 DST post](https://s2.dev/blog/dst), [tokio-rs/turmoil](https://github.com/tokio-rs/turmoil), [madsim](https://github.com/madsim-rs/madsim)).
- **Talos/K8s**: pure compute. Effort: 2-3 weekends. Prerequisite: 1 or 2.

### 10. Scheduling as a distributed-systems topic: KWOK + kube-scheduler-simulator + K8s 1.37 gang scheduling
- **Teaches**: bin-packing, preemption, gang/all-or-nothing scheduling, topology-aware placement, admission vs. scheduling — directly relevant to the operator's own Kueue/power-coordinator design.
- **Experiments**: deploy KWOK in-cluster (Helm; apply `stage-fast.yaml`) to fake 500 nodes/50k pods and stress Kueue quota logic; run kube-scheduler-simulator (v0.4.0, now backed by KWOK, annotates every plugin verdict on the pod) to replay your ClusterQueue policies ([KWOK in-cluster](https://kwok.sigs.k8s.io/docs/user/kwok-in-cluster/), [simulator](https://github.com/kubernetes-sigs/kube-scheduler-simulator)). Try K8s 1.37's beta Workload/PodGroup gang scheduling and Workload-Aware Preemption and compare with Kueue's own gang semantics ([k8s blog 2026-09-08](https://kubernetes.io/blog/2026/09/08/kubernetes-v1-37-advancing-workload-aware-scheduling/)); note v1alpha2 PodGroup manifests must be deleted before 1.37.
- **Caveats**: fake KWOK nodes must carry a taint so real pods (and your power coordinator) never target them; test in a vCluster first. Kueue latest is v0.19.5 (Sep 2026) ([releases](https://github.com/kubernetes-sigs/kueue/releases)). Effort: 1-2 weekends.

### 11. CRDTs and local-first sync: Loro / Automerge behind a partitionable relay
- **Teaches**: convergence without coordination, causal ordering, tombstones, version vectors vs. op-based CRDTs, merge semantics.
- **Experiments**: two or three writer pods editing a Loro doc through a relay pod; NetworkChaos-partition writers for N minutes, keep writing, heal, and assert convergence and encoded-size growth; compare with Maelstrom's `g-set`/`pn-counter` workloads. Loro 1.16.x (Sep 2026) and Automerge are MIT, active ([loro](https://github.com/loro-dev/loro)).
- **Talos/K8s**: none. Tiny footprint. Effort: 1 weekend.

### 12. Observability of distributed behaviour: Hubble + Tetragon + OpenTelemetry tracing
- **Teaches**: seeing partitions, retries, timeouts and leader changes as flows/traces; eBPF-based, no app changes.
- **Experiments**: enable Hubble flow export to Loki; during a Chaos Mesh partition, correlate dropped flows with Raft election metrics in Grafana. Tetragon on Talos ≥1.12 needs `extraHostPathMounts` for `/sys/kernel/tracing` ([Tetragon install](https://tetragon.io/docs/installation/kubernetes/)); trace `connect`/`sendmsg` of etcd pods to watch heartbeat cadence.
- **Caveats**: Tetragon is privileged; extra eBPF on Talos kernel 6.18 — check talos#12726 first. Effort: 1 weekend; multiplies value of every other item.

**Honourable mentions**: Temporal (durable execution, self-host via official Helm; needs Postgres — CNPG lab instance fits), Toxiproxy v2.12.0 (Mar 2025; TCP-level toxics, no privileges, good for app-level timeout experiments), Stateright (Rust actor model checker; low activity in 2026 **[unverified]**), jepsen-k8s (Chaos Mesh-backed Jepsen nemesis for pods; 17 commits, effectively unmaintained — use as a pattern, not a dependency ([repo](https://github.com/scalar-labs/jepsen-k8s))).

## 2. Suggested learning path

1. **Isolation first** (section 3): namespaces, Kueue lab queue, Chaos Mesh scoped to `lab-*`. Half a day.
2. **Maelstrom / Gossip Glomers 1-4** (echo → broadcast → G-counter): messaging, gossip, CRDT basics with a checker telling you when you are wrong.
3. **CloudNativePG lab + Chaos Mesh**: first real replication/failover, first partition, first Grafana panel of a leader change.
4. **etcd lab + robustness tests**: Raft in production code; linearizability checking; fsync tail latency on the degraded RAID host.
5. **MIT Raft lab (3A-3D) then Gossip Glomers 5-6**: build the consensus you have been observing; run tests as Kueue Job arrays.
6. **FizzBee/TLA+ spec of your Raft/2PC**: turn observed failures into counterexamples; learn safety vs. liveness.
7. **NATS JetStream + CockroachDB**: replicated logs, multi-Raft, HLC and clock skew (TimeChaos), transactions under partitions; reproduce a Jepsen finding.
8. **turmoil DST port**: compare deterministic simulation with chaos on the same protocol.
9. **Scheduling track (KWOK, simulator, 1.37 gang scheduling)**: feed back into your Kueue/power-coordinator design.
10. **Observability layer (Hubble/Tetragon/OTel)** woven through steps 3-8; add CRDT relay experiment as dessert.

## 3. Lab isolation setup

- **Namespaces**: `lab-chaos` (privileged PSA, Chaos Mesh only), `lab-*` per experiment (baseline PSA, Kueue-managed). Never label platform namespaces privileged.
- **Chaos scoping**: Chaos Mesh `namespace` filter / `filterNamespace` so selectors cannot match platform namespaces; RBAC-limit chaos CR creation to `lab-*`; optionally a ValidatingAdmissionPolicy rejecting any Chaos CR whose selector namespace is not `lab-*`. Cilium: add a CiliumNetworkPolicy so `lab-*` egress cannot reach platform services (CNPG, Nexus, Loki write) except Prometheus scrape ingress.
- **Kueue**: a `lab` ClusterQueue with its own quota and the power AdmissionCheck; LocalQueues in each `lab-*` namespace; enforce the pod-integration namespace selector so every lab Pod is a Workload (otherwise it blocks sleep). Use Argo Workflows (installed) to sequence "wake → deploy → chaos → measure → teardown" with TTL, so idle labs disappear and workers sleep.
- **Optional vCluster** (v0.37.1, Sep 2026 ([releases](https://github.com/loft-sh/vcluster/releases))) for the scheduling experiments and anything that installs CRDs or needs its own API server (KWOK fake nodes, K8s 1.37 gang-scheduling gates, its own etcd to break). vCluster pods sync into one host namespace, so the same Kueue/PSA rules apply; there is a published pattern for running Chaos Mesh with vCluster ([vcluster blog](https://www.vcluster.com/blog/chaos-mesh-with-vcluster)). Kamaji/kind-in-pod are heavier and need privileged nesting; not recommended here.
- **Storage**: local-path only, label PVCs `lab=true`, and never mount platform PVs. Time-box CockroachDB/FDB clusters; delete PVCs on teardown.
- **Control plane**: taint/affinity so nothing lab-related lands on the 2-vCPU Wi-Fi control-plane VM.

## 4. Wild / frontier (2026)

- **Protocol-aware DST**: TigerBeetle's VOPR now checks safety/liveness invariants inside each replica's consensus and storage layers (Aug 2026 post) and runs 24/7 on 1024 cores ([post](https://tigerbeetle.com/blog/2026-08-20-protocol-aware-dst/), [vopr.md](https://github.com/tigerbeetle/tigerbeetle/blob/main/docs/internals/vopr.md)). Read the simulator source; port one invariant into your turmoil Raft.
- **Antithesis** (deterministic hypervisor; $105M Series A Dec 2025) has no free tier — sales-only, plus an OSS giveaway programme ([blog](https://antithesis.com/blog/2025/oss_pledge_2025/)). The "open-source Antithesis" write-ups ([databases.systems](https://databases.systems/posts/open-source-antithesis-p1)) and Polar Signals' Go-runtime determinism work are the DIY path **[unverified beyond the linked posts]**.
- **Model-guided fuzzing** of distributed systems (arXiv 2410.02307): use a TLA+/FizzBee model to steer Chaos Mesh nemeses instead of random faults.
- **eBPF-native faults**: with Talos 1.14 relaxing lockdown for eBPF, a small bpftrace/Tetragon-driven "drop every Nth Raft heartbeat" injector is feasible without Chaos Mesh's daemon — a fun, scoped project.
- **Talos `VethConfig`/`VXLANConfig`**: build a declarative second overlay purely for a "WAN emulation" lab (netem via Chaos Mesh on that link) — Talos-specific and new in 1.14.
- **K8s 1.37 CompositePodGroup** (hierarchical gang scheduling) and Kueue TAS "mixed" profile: prototype a topology (two Proxmox hosts = two racks) and observe placement decisions.
- **WASM**: run Maelstrom nodes as wasmCloud/Spin components to study cold-start and capability-based isolation **[unverified suitability]**.

Sources used are linked inline; key primary ones: [Talos v1.14.0](https://github.com/siderolabs/talos/releases/tag/v1.14.0), [Talos Pod Security](https://www.talos.dev/v1.10/kubernetes-guides/configuration/pod-security/), [Chaos Mesh releases](https://github.com/chaos-mesh/chaos-mesh/releases), [Maelstrom](https://github.com/jepsen-io/maelstrom), [Fly.io dist-sys](https://fly.io/dist-sys/), [MIT 6.5840](https://pdos.csail.mit.edu/6.824/labs/lab-raft1.html), [etcd robustness](https://github.com/etcd-io/etcd/blob/main/tests/robustness/README.md), [NATS 2.12](https://nats.io/blog/nats-server-2.12-release/), [Jepsen NATS 2.12.1](https://jepsen.io/analyses/nats-2.12.1), [CockroachDB licensing](https://www.cockroachlabs.com/docs/stable/licensing-faqs), [FizzBee](https://github.com/fizzbee-io/fizzbee), [turmoil](https://github.com/tokio-rs/turmoil), [KWOK](https://kwok.sigs.k8s.io/docs/user/kwok-in-cluster/), [k8s 1.37 scheduling](https://kubernetes.io/blog/2026/09/08/kubernetes-v1-37-advancing-workload-aware-scheduling/), [Kueue releases](https://github.com/kubernetes-sigs/kueue/releases), [Tetragon on Talos](https://tetragon.io/docs/installation/kubernetes/), [vCluster releases](https://github.com/loft-sh/vcluster/releases), [TigerBeetle DST](https://tigerbeetle.com/blog/2026-08-20-protocol-aware-dst/).