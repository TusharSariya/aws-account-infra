# Local Kubernetes inference across heterogeneous GPU nodes

Research date: 2026-09-01

## Question and scope

This report compares production-oriented ways to serve Gemma 4 and Qwen3-8B-class models on Kubernetes, beginning with one Ubuntu GPU worker and allowing additional, potentially different GPU workers later. It covers architecture choices and constraints but deliberately does not select a final stack.

## Findings

### Separate the system into four layers

A durable design has four independently replaceable layers:

1. **GPU enablement and inventory.** Kubernetes device plugins advertise integer extended resources such as `nvidia.com/gpu`; those resources cannot be overcommitted by Kubernetes itself. NVIDIA GPU Operator can manage the driver, container toolkit, device plugin, GPU Feature Discovery labels, and DCGM monitoring as one stack. On an externally managed Ubuntu worker, the operator can either manage those components or be configured around a host-installed driver, but that choice must be tested against the exact OS, kernel, GPU, and operator support matrix. Sources: [Kubernetes device plugins](https://kubernetes.io/docs/concepts/extend-kubernetes/compute-storage-net/device-plugins/), [NVIDIA GPU Operator overview](https://docs.nvidia.com/datacenter/cloud-native/gpu-operator/latest/).
2. **Placement and admission.** Node labels/affinity and taints/tolerations select a GPU family and keep ordinary workloads off scarce nodes. Kubernetes resource requests provide exclusive whole-device allocation; NVIDIA time-slicing can advertise multiple shared replicas but provides neither memory nor fault isolation. MIG provides hardware memory and fault isolation only on supported GPU models. Kueue adds quotas, priorities, queues, fair sharing, preemption, and `ResourceFlavor` fungibility for batch-style work. Sources: [NVIDIA GPU sharing](https://docs.nvidia.com/datacenter/cloud-native/gpu-operator/latest/gpu-sharing.html), [NVIDIA MIG](https://docs.nvidia.com/datacenter/cloud-native/gpu-operator/latest/gpu-operator-mig.html), [Kueue overview](https://kueue.sigs.k8s.io/docs/overview/).
3. **Inference engine.** vLLM and SGLang are engines. Both are named by Qwen as recommended deployment frameworks for Qwen3; the official Qwen3-8B model card gives launch examples for both. vLLM exposes OpenAI-compatible APIs, health/load endpoints, continuous batching, prefix caching and Prometheus metrics, and has a documented quantization/hardware compatibility matrix. Runtime support for a particular Gemma 4 checkpoint, modality, quantization and GPU generation must be verified before committing to it; a family name alone is not a compatibility guarantee. Sources: [Qwen3 announcement](https://qwenlm.github.io/blog/qwen3/), [Qwen3-8B model card](https://huggingface.co/Qwen/Qwen3-8B), [vLLM online serving](https://docs.vllm.ai/en/latest/serving/openai_compatible_server/), [vLLM quantization](https://docs.vllm.ai/en/stable/features/quantization/).
4. **Serving control plane and gateway.** A plain Kubernetes Deployment around an engine, KServe, or Ray Serve/KubeRay can own lifecycle, routing and scaling. This layer should be kept separate from model/API consumers so it can evolve without changing clients.

This layering is the main hedge against a fast-moving inference ecosystem: standardize the external API and scheduling contract, not an engine's internal flags.

### Viable serving architectures

| Architecture | What it provides | Fit and trade-off |
| --- | --- | --- |
| Engine in a Deployment/StatefulSet plus an API gateway | Lowest controller count; direct ownership of probes, rollout, PVC/local cache, PodDisruptionBudget, Service and engine flags | Best baseline for one GPU and one or two always-warm models. Every concern such as queue bounds, token rate limits, model-aware routing and rollout safety must be assembled explicitly. |
| KServe `InferenceService` / `LLMInferenceService` with vLLM-compatible runtime | Kubernetes CRDs for runtime templates, model lifecycle, local model cache, multi-node LeaderWorkerSet workloads, model-aware scaling and AI-gateway integration | Strong platform abstraction and a natural GitOps API, but adds controllers and alpha APIs. The current `LLMInferenceService` API is `v1alpha1`; treat upgrades and CRD churn as operational cost. KServe's Workload Variant Autoscaler uses queue depth and KV-cache utilization instead of CPU alone. Sources: [KServe configuration](https://kserve.github.io/website/docs/model-serving/generative-inference/llmisvc/llmisvc-configuration), [KServe API](https://kserve.github.io/website/docs/reference/crd-api). |
| Ray Serve LLM through KubeRay | Multi-model and multi-node orchestration, placement groups, request-queue autoscaling, custom/prefix-aware routing, and distributed serving around engines such as vLLM | Appropriate when models span GPUs/nodes or serving patterns become genuinely distributed. It adds a second scheduler/control plane and Ray head/GCS failure semantics. KubeRay `RayService` recovers failed clusters; transient router/replica queues are still lost during failures. Sources: [Ray on Kubernetes](https://docs.ray.io/en/latest/cluster/kubernetes/index.html), [Ray Serve LLM](https://docs.ray.io/en/latest/serve/llm/index.html), [Ray Serve architecture](https://docs.ray.io/en/latest/serve/architecture.html). |

KServe and Ray are not required merely because Kubernetes is “production-like.” With one physical GPU, horizontal replica autoscaling cannot create GPU capacity. It can only queue, reject, reschedule after failure, or replace a stopped workload. Keeping one warm replica and applying bounded admission is more honest than configuring an unreachable replica count.

### Heterogeneous GPU design

Treat each GPU node as a **resource flavor**, not as an interchangeable member of one distributed accelerator:

- Record vendor, product, VRAM, compute capability/architecture, driver/runtime version, supported precisions and sharing mode in discovered and administratively controlled labels. Use affinity against capability classes such as `inference.example.com/class=qwen3-8b-int4`, while retaining vendor labels for diagnostics.
- Maintain runtime images/configuration per vendor and architecture. vLLM's quantization table differs across Volta, Turing, Ampere, Ada, Hopper, AMD, Intel, x86 and Arm. A checkpoint quantized for one kernel path is not automatically portable to another.
- Prefer one complete model replica per compatible GPU. Route between replicas at the gateway. Do not tensor-parallelize one model across mismatched consumer GPUs unless the exact engine/hardware combination is benchmarked and supported; cross-node links and the slowest device become part of every request's critical path.
- Use Kueue `ResourceFlavor`s for queued agent/batch work where a job can accept several compatible accelerator classes. For interactive long-running servers, use ordinary scheduling plus model-aware gateway routing; Kueue's core value is admission of finite workloads rather than per-request HTTP queuing.
- Addition of another GPU desktop should be a node-pool operation: label/taint it, install its vendor stack, run conformance and model benchmarks, warm its model cache, then add it to a routing pool. It should not require changing client endpoints.

NVIDIA time-slicing is useful for low-duty experiments but unsafe as the default isolation mechanism: one pod can exhaust GPU memory and affect every sharer. MIG is preferable where supported and where a model fits a slice. Otherwise, whole-GPU allocation plus inference-engine continuous batching gives the clearest capacity and failure boundary.

### Model storage and cold starts

Model weights are rebuildable cache data, not authoritative NAS state. Keep an immutable model identity (repository plus exact revision and, ideally, digest), credentials at runtime, and a durable upstream/off-host source. Cache weights on each GPU node's fast local disk.

KServe's `LocalModelCache` creates per-node download jobs and exposes node/cache status; its namespace-scoped variant provides a tenancy boundary. It requires enough local capacity and correct scheduling of its node agent. This reduces cold-start time but creates a node-local dependency: a pod must land where the requested revision is cached or wait for download. Source: [KServe Local Model Cache](https://kserve.github.io/website/docs/model-serving/generative-inference/modelcache/localmodel).

Use explicit disk budgets: model files, temporary download space, compiled kernels, container images and at least one previous model revision during rollback. Do not put latency-sensitive model loading on NFS without measurements. Evict caches by policy and alert before disk pressure makes Kubernetes evict inference pods.

### Concurrency, queues and admission

There are two different queues and both must be bounded:

- **Interactive request queue:** at the AI gateway/serving layer, enforce authentication, per-user/agent token budgets, maximum prompt/context/output sizes, request deadlines, maximum queued and ongoing requests, and a clear `429`/`503` overload response. The engine's continuous batching then combines only admitted requests. vLLM publishes request, queue, KV-cache and token metrics at `/metrics`; Ray exposes `max_ongoing_requests` and `max_queued_requests`. Sources: [vLLM production metrics](https://docs.vllm.ai/en/latest/usage/metrics/), [Ray Serve LLM configuration](https://docs.ray.io/en/latest/serve/llm/user-guides/configuration.html).
- **Asynchronous agent/batch queue:** submit finite Kubernetes Jobs (or a supported job abstraction) through Kueue with quotas, priorities and fair sharing. This prevents autonomous agents from starving interactive inference or each other.

Queue depth is not capacity. Alert on oldest queued request/job, rejection rate and deadline misses. Autoscale only after a load test establishes per-replica safe concurrency and only up to the number of compatible GPUs. Scale-to-zero saves idle power but pays model download/load/compile latency; it is unsuitable for an interactive SLO unless cold start is explicitly accepted.

### Observability and failure behavior

Collect three correlated layers:

- **GPU/node:** DCGM Exporter temperature, power, utilization, memory, throttling, ECC/XID and health where hardware supports them, attributed to Kubernetes pods. GPU Operator can manage DCGM Exporter. Source: [DCGM Exporter metrics](https://docs.nvidia.com/datacenter/dcgm/latest/reference/dcgm-exporter-metrics.html).
- **engine/model:** time to first token, time per output token, prompt/generated token throughput, running/waiting requests, KV-cache occupancy, prefix-cache hit rate, model-load time and errors.
- **gateway/user:** request rate, latency percentiles, streaming completion/cancellation, rejection reason, tokens by authenticated principal/model, and trace correlation. Avoid storing prompt or generated content in metrics, logs or traces by default.

Health checks must distinguish process liveness, model readiness and useful capacity. During GPU/node failure, Kubernetes can recreate a pod only on another compatible node with enough free VRAM and model access. In-flight streams and in-memory/KV state are lost and clients need bounded retry rules. A single GPU therefore provides restartability, not serving availability. With a second compatible GPU, two independent replicas plus topology spread and model-aware routing provide node-failure tolerance; they still do not protect against the broader single-Proxmox-host failure domain where applicable.

### Trust and sandbox boundary

Inference servers process untrusted prompts, but they also load large native CUDA/runtime stacks and possess direct devices. Keep them on dedicated trusted GPU nodes/namespaces with restricted service accounts, read-only root filesystems where supported, egress allowlists for model sources/telemetry, network policies, immutable images and no host mounts except narrowly scoped cache paths.

Do not schedule arbitrary agent-generated code in the inference pod or grant sandbox workloads direct access to the model server's credentials/cache. Sandboxed jobs should call a narrow authenticated inference API over policy-controlled networking. Kubernetes `RuntimeClass` can select alternate runtimes, but GPU support is runtime- and vendor-specific. NVIDIA documents Kata/Confidential Container GPU passthrough as a separate node configuration; it is not evidence that the planned gVisor sandbox transparently supports the GPU path. Sources: [Kubernetes RuntimeClass](https://kubernetes.io/docs/reference/kubernetes-api/node/runtime-class-v1/), [NVIDIA confidential-container deployment](https://docs.nvidia.com/datacenter/cloud-native/confidential-containers/latest/confidential-containers-deploy.html).

## Approximate resource envelope

Exact sizing requires the actual GPU model/VRAM, checkpoint, quantization, context limit and concurrency target. A useful lower-bound calculation for dense model weights is:

`weight bytes approximately equal parameter count multiplied by bytes per stored parameter`

Thus Qwen3-8B weights alone are roughly 16 GB at BF16, 8 GB at 8-bit, or 4 GB at 4-bit, before quantization metadata, CUDA graphs/workspaces, framework overhead, multimodal encoders and KV cache. Qwen documents Qwen3-8B as dense with a 128K context limit, but configuring that maximum substantially increases KV-cache demand; production should set the smallest context limit the workload needs. Sources: [Qwen3 model sizes](https://qwenlm.github.io/blog/qwen3/), [vLLM quantization rationale](https://docs.vllm.ai/en/stable/features/quantization/).

Gemma 4 is not one size: Google lists effective 2B/4B edge variants, a 12B unified model, a 26B MoE with 4B active parameters, and a 31B dense model. “Active parameters” affects compute but does not mean only those weights must be stored; checkpoint format and engine support determine actual memory. Google positions 12B and 26B-A4B for desktops/small servers and 31B for large servers/clusters. Source: [Gemma 4 overview](https://ai.google.dev/gemma/docs/core).

For either family, reserve host RAM at least for runtime overhead and model staging, local disk for multiple immutable revisions, and VRAM headroom for KV cache rather than sizing to weights alone. Initial production measurements should sweep context lengths and concurrency and record out-of-memory behavior, TTFT, output-token latency, throughput, power and recovery time. The benchmark result, not parameter count, should define each capability label and admission limit.

## Decisions the later architecture ticket must make

This research leaves these choices intentionally open:

1. Exact current and candidate future GPU models, VRAM and supported sharing modes.
2. Plain engine deployment versus KServe versus KubeRay, with a complexity budget and API maturity policy.
3. vLLM, SGLang or another engine per exact Gemma 4 and Qwen3 checkpoint after compatibility and quality tests.
4. One always-warm model, concurrent models, or demand-driven model swapping.
5. Interactive SLOs, queue limits, context/output ceilings and autonomous-agent quotas.
6. Whole-GPU, time-sliced or MIG allocation per GPU class.
7. Local-cache capacity, source of truth, revision promotion and rollback policy.
8. Whether future nodes are NVIDIA-only or deliberately multi-vendor; multi-vendor support has a meaningful image, metrics and test burden.

## Conclusion

The viable production shape is not a single monolithic “AI stack.” It is a stable authenticated API in front of bounded request admission, a replaceable serving control plane and engine, capability-based placement onto independently managed GPU resource flavors, and per-node immutable model caches. One GPU should run one warm whole-GPU replica with engine-level batching unless measurements justify sharing. Additional nodes should add independent compatible replicas first; distributed multi-node inference is warranted only when a chosen model cannot fit or measured throughput requires it. KServe and KubeRay are credible later control planes, but each adds machinery that a one-GPU starting point does not automatically need.
