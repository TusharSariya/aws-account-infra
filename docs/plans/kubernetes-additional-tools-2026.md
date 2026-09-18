# Additional Kubernetes Tooling for 2026

## Status

Research and decision record as of August 25, 2026. This document catalogs
useful Kubernetes projects that are not part of the current active homelab
stack and decides where, if anywhere, they fit.

This document does not authorize deployment. Every adopted component requires
a pinned version, support-matrix review, resource budget, threat-model review,
backup plan, monitoring, and removal procedure.

## Executive decision

The homelab already has a broad target platform: Talos, Cilium, Istio Gateway
API, Argo CD, Kyverno, Authentik, OpenFGA, External Secrets Operator,
Prometheus, Loki, Tetragon, CloudNativePG, a separate NAS, and a local OCI
registry. Additional tools should provide a missing abstraction rather than a
second implementation of an existing responsibility.

The strongest candidates are:

1. Kubernetes Agent Sandbox for broker-managed, stateful agent environments.
2. Kueue when batch or GPU workloads compete for finite capacity.
3. Argo Workflows when a real workload needs a multi-step DAG.
4. One ephemeral vCluster for trusted Kubernetes and operator experiments.
5. Headlamp and Inspektor Gadget for operator experience and diagnosis.
6. A chaos-testing tool after recovery and observability are stable.

Do not install these simultaneously. Introduce one experiment at a time, prove
its value and failure behavior, and remove it if it does not become part of a
real workflow.

## Decision criteria

Adopt another controller only when all of the following are true:

- A concrete workload cannot be handled cleanly by an existing component.
- The new controller has one clear owner and does not create competing desired
  state.
- Its CRDs, webhooks, RBAC, network access, storage, and failure mode are
  understood.
- It works during the intended seven-day WAN partition or fails in a documented
  safe state.
- Its persistent state is either reconstructible or included in tested backup
  and restore procedures.
- Prometheus metrics, logs, alerts, and upgrade compatibility are available.
- Its CPU and memory cost fits the fixed Proxmox capacity.

## Agent and tenant environments

### Kubernetes Agent Sandbox

Kubernetes SIG Apps is developing Agent Sandbox for isolated, stateful,
singleton agent runtimes. A `Sandbox` represents the execution environment and
can provide:

- gVisor or Kata-backed isolation for untrusted code.
- Persistent workspace state.
- Stable network identity.
- Suspension and resumption for mostly idle agents.
- Claims and warm pools for lower startup latency.

This is closer to the workspace broker's ordinary agent-run requirement than a
virtual Kubernetes cluster. It could eventually replace some custom lifecycle
code that creates and coordinates a Pod, Service, PVC, stable identity, and
idle cleanup for every agent.

Agent Sandbox is still developing quickly. Evaluate it only on the sandbox
worker and keep the broker's typed NAS operations, OpenFGA checks, Kyverno
policy, gVisor requirement, quotas, and network isolation authoritative. Do not
make the recovery path depend on its API until a stable version survives create,
suspend, resume, expire, node reboot, and restore tests.

See [Running Agents on Kubernetes with Agent Sandbox](https://kubernetes.io/blog/2026/03/20/running-agents-on-kubernetes-with-agent-sandbox/).

### vCluster

vCluster gives each tenant a separate Kubernetes API server, controller
manager, RBAC domain, CRD set, and cluster-administration experience while
synchronizing selected workloads onto a host cluster.

Use an ephemeral vCluster when a trusted user or agent must:

- Install and test CRDs or operators.
- Exercise cluster-admin workflows without host cluster-admin.
- Test Helm charts that assume ownership of a cluster.
- Rehearse Kubernetes or controller upgrades.
- Receive a disposable preview cluster rather than a namespace.

Do not use a vCluster for an ordinary agent that only needs a code-execution
environment. Agent Sandbox or a broker-created Job is simpler.

Shared-node vClusters isolate the Kubernetes control plane, not the kernel,
physical node, host CNI, or storage system. The project's current guidance
positions shared nodes for trusted internal tenants. Host-level Cilium,
Kyverno, ResourceQuota, storage restrictions, node placement, and runtime
isolation must still apply to synchronized workloads. A hostile tenant needing
cluster-admin requires a dedicated VM or private worker nodes, not merely a
shared-node vCluster.

The first experiment should create one vCluster at a time in a quota-limited
sandbox namespace. Do not deploy the commercial management platform or rely on
automatic sleep until the open-source virtual-cluster use case is proven.

See [What is vCluster](https://www.vcluster.com/docs/vcluster/introduction/what-are-virtual-clusters/)
and its [shared-node guidance](https://www.vcluster.com/docs/vcluster/quick-start/shared-nodes).

### Capsule and Kamaji

These are alternative multi-tenancy directions rather than additions to
vCluster:

- Capsule delegates groups of namespaces and their quotas, policies, and
  ownership to tenants. It overlaps with the repository's catalog vending,
  RBAC, ResourceQuota, and Kyverno design.
- Kamaji hosts multiple Kubernetes control planes while workloads run on
  separate worker pools. It becomes relevant only if the homelab operates a
  real cluster fleet.

Do not add Capsule while the existing brokered namespace model remains
sufficient. Do not add Kamaji for a single cluster.

See [Capsule](https://projectcapsule.dev/) and [Kamaji](https://kamaji.clastix.io/).

## Batch, queues, and workflows

### Kueue

Kueue controls when Kubernetes batch workloads may consume finite compute. It
adds cluster and local queues, resource flavors, quotas, priority, fair sharing,
preemption, all-or-nothing admission, and support for GPU and Dynamic Resource
Allocation resources.

Kueue does not store application task payloads and does not replace PostgreSQL
Queues, KEDA, the Kubernetes scheduler, or Kyverno:

```text
PostgreSQL Queue    What work needs doing?
KEDA                How many workers or Jobs should exist?
Kueue               Which Jobs may consume capacity now?
kube-scheduler      Which node should run each admitted Pod?
Kyverno             Is the workload allowed and correctly isolated?
```

Do not add Kueue while fixed workers, ResourceQuota, and ordinary Jobs provide
enough concurrency control. Add it when agent or GPU Jobs regularly wait for
capacity, projects need fair sharing or priority, jobs have very different
resource sizes, or a distributed job must start as a complete group.

Initial queue design:

| Queue | Eligible capacity | Workloads |
|---|---|---|
| `sandbox-agents` | Sandbox CPU and memory under gVisor | Untrusted agent runs |
| `trusted-batch` | Trusted-worker CPU and memory | Controlled builds and data processing |
| `gpu-batch` | Approved GPU resources | Inference, embeddings, and training |

Only the platform administrator may create or change cluster queues and
resource flavors. Project namespaces receive restricted local queues. Kyverno
must prevent a workload from changing its queue, priority, runtime, resource
request, or node placement outside its grant.

Defer MultiKueue, topology-aware scheduling, and distributed training
integrations until independent physical compute nodes exist.

See the [Kueue overview](https://kueue.sigs.k8s.io/docs/overview/) and
[Kueue concepts](https://kueue.sigs.k8s.io/docs/concepts/).

### Argo Workflows

Argo CD reconciles application desired state. Argo Workflows executes finite
step or DAG-based container workflows.

Add Argo Workflows only when a real process requires dependencies, fan-out,
fan-in, retries, artifacts, and an execution history, for example:

```text
prepare data -> parallel processing -> validate -> publish artifact
```

Candidate uses include database restore exercises, model pipelines, batch data
transformation, NAS recovery verification, and multi-stage agent publication.
Kueue may admit the workflow's compute, but it does not replace workflow
semantics.

Do not use Argo Workflows for a single Kubernetes Job or as a second GitOps
controller. See [Argo Workflows](https://argoproj.github.io/argo-workflows/).

### KEDA, PostgreSQL Queues, and workflow engines

- Retain PostgreSQL/Supabase Queues for durable application messages,
  visibility timeouts, retries, and archival.
- Use KEDA when event or queue depth should scale a worker Deployment or create
  Jobs.
- Use Kueue only for cluster-resource admission after Jobs exist.
- Use Argo Workflows only for Kubernetes-native DAG execution.
- Consider Temporal or Conductor only when application-level, long-running
  business workflows must survive across systems and Kubernetes clusters.

Do not add all of these to one workload. Choose the smallest combination that
owns each required state machine exactly once.

## Platform engineering and cluster lifecycle

### Crossplane

Crossplane builds Kubernetes-style APIs that compose Kubernetes and external
resources. It becomes useful if the platform deliberately exposes a stable
self-service API such as:

```yaml
apiVersion: platform.homelab.example/v1
kind: Application
spec:
  database: postgres
  storage: 20Gi
  exposure: private
```

Today the service catalog, broker, Helm charts, and OpenTofu already own those
responsibilities. Adding Crossplane now would create competing state ownership
and place powerful AWS permissions inside the cluster. Keep OpenTofu as the AWS
account authority. Reconsider Crossplane only when a specific self-service API
and its ownership boundary have been designed.

See [What is Crossplane](https://docs.crossplane.io/latest/whats-crossplane/).

### Cluster API

Cluster API provides declarative creation, scaling, upgrade, and deletion of
Kubernetes clusters and their infrastructure. It is valuable for a fleet of
repeatable clusters, not one statically sized Proxmox cluster.

Reconsider it when the homelab needs several persistent or disposable Talos
clusters and a separate management cluster. Until then, the Talos API,
OpenTofu, and Talos are simpler and avoid a management-cluster bootstrap
dependency. See [Cluster API](https://cluster-api.sigs.k8s.io/).

### Developer portals and platform products

| Tool | Purpose | Decision |
|---|---|---|
| Backstage | Catalog, ownership, templates, documentation, and portal plugins | Already planned after the catalog workflow is stable |
| Kratix | Platform promises and workload APIs | Defer; overlaps with the catalog and possible future Crossplane APIs |
| OpenFeature with flagd | Vendor-neutral feature-flag contract | Add only when an application has a real flag lifecycle |
| Headlamp | RBAC-aware Kubernetes operational UI | Useful after OIDC and least-privilege roles work |

Headlamp must authenticate through the existing OIDC/RBAC path. Do not give its
ServiceAccount cluster-admin or use it as an authorization layer.

## AI and GPU platform tools

| Tool | Capability | Adoption gate |
|---|---|---|
| KServe | Declarative model serving across vLLM, Triton, Hugging Face, and other runtimes | Several durable model endpoints need common rollout and serving APIs |
| KubeRay | Distributed Python, Ray jobs, clusters, and serving | A workload genuinely requires distributed Python execution |
| JobSet | Groups coordinated Kubernetes Jobs | A distributed batch workload has multiple job roles |
| LeaderWorkerSet | Leader and worker topology for distributed AI | Multi-node or multi-GPU models require it |
| Gateway API Inference Extension | Model-aware, priority-aware, accelerator-aware request routing | Sandbox experiment only while the API remains alpha |
| Kubeflow | Full ML platform, training operators, pipelines, and notebooks | Learning or operating Kubeflow is itself a goal |
| JupyterHub | Multi-user notebooks | Multiple users need governed interactive data-science sessions |

KServe is preferable to installing all of Kubeflow when the only requirement is
model serving. The Gateway API Inference Extension aligns with the existing
Istio Gateway API choice, but its current documentation labels it experimental
and not production-ready. Do not add it until local model endpoints and routing
objectives exist.

See [KServe](https://kserve.github.io/website/docs/admin-guide/overview) and the
[Gateway API Inference Extension](https://gateway-api-inference-extension.sigs.k8s.io/).

## Operations, recovery, and diagnosis

| Tool | Capability | Decision |
|---|---|---|
| Headlamp | Kubernetes resource UI honoring Kubernetes RBAC | Add as a private, read-mostly operator interface if desired |
| Inspektor Gadget | On-demand eBPF-based cluster and container diagnosis | Useful operator tool; restrict its highly privileged access |
| Stakater Reloader | Restarts workloads after Secret or ConfigMap changes | Evaluate for catalog entries with `restart_on_rotation: true` |
| Goldilocks | Presents VPA sizing recommendations | Optional after VPA recommendation mode is operational |
| Node Problem Detector | Reports kernel, runtime, and node conditions | Add only for signals Talos does not already expose |
| Kepler | Workload energy estimation | Optional homelab efficiency experiment |
| Sloth or Pyrra | Generates Prometheus rules from SLO definitions | Add after two or more services have defined SLOs |
| Velero | Kubernetes object backup and supported CSI snapshots | Add only after Talos etcd and application-native restores work |
| Descheduler | Corrects unsuitable Pod placement over time | Add only after measured multi-node placement imbalance |

Inspektor Gadget and Headlamp improve operator experience but do not become
security authorities. Velero complements rather than replaces Talos etcd
snapshots, CloudNativePG backups, and NAS S3 recovery.

## Resilience and chaos testing

Choose one of Chaos Mesh or Litmus only after monitoring, backup, and restore
are reliable. Begin with reversible experiments in disposable namespaces:

- Kill an application Pod and controller replica.
- Inject DNS and WAN failure.
- Delay or reject Supabase, AWS, and ECR traffic.
- Restart Cilium, CoreDNS, External Secrets, and the local registry one at a
  time.
- Fill a quota-limited scratch volume.
- Drain or reboot a worker VM.

Do not begin with control-plane corruption, disk destruction, or experiments on
the NAS. Every experiment requires a steady-state assertion, maximum duration,
automatic rollback, and email alert expectation.

See [Chaos Mesh](https://chaos-mesh.org/) and [LitmusChaos](https://litmuschaos.io/).

## Data and event platforms

| Tool | Capability | Decision |
|---|---|---|
| Strimzi | Operates Apache Kafka on Kubernetes | Add only for a demonstrated streaming requirement |
| Redpanda Operator | Operates a Kafka-compatible Redpanda cluster | Lighter Kafka alternative, still a new stateful platform |
| Conduktor | Kafka UI, governance, proxy, masking, and policy | No role until Kafka or Redpanda exists |
| Dapr | Application runtime APIs for pub/sub, state, and service invocation | Add only if applications adopt its programming model deliberately |
| Knative Serving/Eventing | Scale-to-zero services and event delivery | Defer while KEDA and ordinary workloads satisfy the need |

Conduktor is not a general Kubernetes management or scheduling tool. It sits
above an existing Kafka-compatible platform. Do not install it merely to add a
data UI.

## Mutually exclusive or redundant choices

| Existing or selected component | Do not add simultaneously without replacing it |
|---|---|
| Argo CD | Flux |
| Kyverno | OPA Gatekeeper |
| Cilium | Calico |
| Istio | Linkerd |
| Tetragon | Falco or KubeArmor |
| Kueue | Volcano |
| AWS Secrets Manager and ESO | Vault, Sealed Secrets, or another runtime secret authority |
| External NAS | Longhorn, Rook/Ceph, or OpenEBS merely to claim storage redundancy |
| Prometheus, Loki, and Grafana | Mimir, Thanos, VictoriaMetrics, Elasticsearch, or OpenSearch without a measured need |
| Argo Rollouts | Flagger |
| GitHub Actions | Tekton without an in-cluster CI requirement |

Alternatives are valuable for comparison, but simultaneously operating two
controllers for the same responsibility increases privileged RBAC, webhook and
CRD count, upgrade risk, resource use, and incident ambiguity.

## Recommended experiment order

1. Complete the Talos, GitOps, identity, admission, network, secrets,
   observability, registry, and recovery baseline.
2. Evaluate Agent Sandbox for one broker-managed agent run on the sandbox
   worker.
3. Add Kueue only after batch or GPU contention is measured.
4. Add Argo Workflows only for one real DAG-shaped workflow.
5. Create one disposable vCluster for trusted CRD or operator experimentation.
6. Add Headlamp or Inspektor Gadget if they improve real operational tasks.
7. Run reversible chaos experiments against the documented partition and
   restore objectives.
8. Evaluate the AI-serving tools only after a model-serving workload exists.

## Acceptance requirements for any new tool

- Installation and removal are declarative and tested.
- Images are digest-pinned, mirrored locally, scanned, and signature-verified.
- RBAC contains no unexplained wildcard, Secret, `nodes/proxy`, impersonation,
  privilege-escalation, or host access.
- The tool runs under Pod Security Admission and receives explicit Cilium
  network policy.
- Persistent state has a documented backup and restore path.
- Prometheus metrics, structured logs, health probes, and email alerts cover
  failure and reconciliation lag.
- Upgrade and rollback are tested against the selected Kubernetes release.
- WAN loss does not silently disable a security boundary or delete retained
  state.
- Its CPU, memory, storage, CRDs, webhooks, and API availability cost are
  recorded.
- The experiment has a removal decision date and a named unmet requirement it
  is expected to solve.

## Assumptions

- The homelab remains one physical Proxmox failure domain.
- Open-source-first and practical hardening remain preferred over product
  breadth.
- Agents use brokered storage, OpenFGA resource authorization, Kyverno policy,
  and gVisor regardless of higher-level orchestration.
- New cluster tools do not receive live secrets during documentation or
  evaluation planning.
- Experimental APIs remain confined to sandbox namespaces and are not recovery
  dependencies.
