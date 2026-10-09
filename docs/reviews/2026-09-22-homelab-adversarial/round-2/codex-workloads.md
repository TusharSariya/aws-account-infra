1. **Verdict**

At commit `000bb81`, this is a carefully guarded, fixed two-worker CPU homelab, but it does not yet meet the workload flexibility in the operator goal. Admission and power coordination are substantive implementations; latency-sensitive admission, persistent AI service operation, GPU scheduling, and heterogeneous expansion remain gaps. The aggregate AI deployment also couples substantial compute and local storage to one worker. These conclusions come from repository inspection only; no commands contacted infrastructure or the network, and no prior reviews were read.

2. **Findings**

**F1 — Interactive AI has no admission protection against batch work.**

- **Severity:** High
- **Claim:** Shared FIFO admission and disabled preemption allow batch workloads to delay interactive AI indefinitely.
- **Evidence:** `config/environments/kubernetes/homelab-ci/pool-values.yaml:8` selects `StrictFIFO`; `charts/homelab-queue/templates/queue.yaml:45` disables preemption; `charts/homelab-queue/templates/admission.yaml:45` requires equal workload priority, and line 60 prohibits a nonempty Pod priority class. The AI container requests 29.5 CPU plus 1.75 CPU for companions: `charts/homelab-ai/values.yaml:2`.
- **Status:** IMPLEMENTED-BUT-FLAWED
- **Failure scenario:** A long-running runner occupies primary-worker quota when an inference request arrives. AI needs the entire 31.25-CPU primary budget and cannot preempt the runner or use secondary storage. The user waits for batch completion regardless of urgency.
- **Fix:** Give interactive services reserved capacity and a separate admission class. Define bounded batch execution and explicit preemption rules for interruptible work; permit the corresponding priorities through admission.
- **Confidence:** High

**F2 — GPU execution is absent from the deployed workload contract.**

- **Severity:** High
- **Claim:** The current AI and queue templates do not provide a GPU resource or Talos GPU deployment path.
- **Evidence:** `charts/homelab-ai/templates/_pod.tpl:80` requests only CPU, memory, and ephemeral storage for Ollama. `charts/homelab-queue/templates/queue.yaml:49` covers the same three resources. `docs/plans/talos-system-extensions.md:86` explicitly excludes NVIDIA extensions and places the GPU on a conventional Ubuntu worker.
- **Status:** MISSING
- **Failure scenario:** Adding GPU hardware or a GPU-equipped Talos worker does not make the current Ollama deployment request that device; AI remains CPU-configured and primary-pinned.
- **Fix:** Add a tested GPU worker profile covering hardware exposure, compatible Talos driver extensions, container runtime integration, device advertisement, GPU resource requests, and GPU-aware Kueue flavors/quotas. Validate inference before enabling automatic power retirement.
- **Confidence:** High

**F3 — Persistent AI operation has no supported lifecycle mode.**

- **Severity:** Medium
- **Claim:** Every healthy, idle AI runtime is automatically stopped, including one an operator wants to keep continuously available.
- **Evidence:** `apps/platform/lifecycle/state.py:23` accepts only `start`, `stop`, and `force-stop`; line 154 computes idleness without a persistence override, and line 160 changes desired state to off. `config/environments/kubernetes/homelab/lifecycle-values.yaml:3` sets 300 seconds.
- **Status:** MISSING
- **Failure scenario:** An operator starts inference for a latency-sensitive service. After five quiet minutes, the runtime stops; its next request incurs startup and admission delay.
- **Fix:** Add a durable `persistent` versus `on-demand` lifecycle policy, with explicit resource reservation and power-controller integration. Preserve deliberate stop and storage-pressure handling.
- **Confidence:** High

**F4 — AI services share one oversized scheduling and storage boundary.**

- **Severity:** Medium
- **Claim:** Bundling inference, workspace, vector storage, and search into one primary-pinned Pod prevents independent scaling and relocation.
- **Evidence:** `charts/homelab-ai/templates/_pod.tpl:29` pins the Pod; lines 62, 97, 143, and 166 define its four containers. `charts/homelab-ai/values.yaml:3` assigns Ollama 29.5 CPU. `charts/homelab-ai/templates/resources.yaml:16` uses local volumes with node affinity at line 21.
- **Status:** IMPLEMENTED-BUT-FLAWED
- **Failure scenario:** A workspace or search-only session reserves the full inference footprint. Moving inference to a future GPU node also requires disentangling or migrating workspace and vector data; secondary cannot take over when primary is unavailable.
- **Fix:** Separate inference from workspace/search/vector services, with explicit service dependencies and individual lifecycle budgets. Keep model caches local where useful, while defining independent placement and recovery for durable application data.
- **Confidence:** High

**F5 — Worker expansion requires coordinated code changes rather than inventory configuration.**

- **Severity:** Medium
- **Claim:** Capacity coordination and queue construction encode two fixed hosts and identical budgets, preventing straightforward heterogeneous onboarding.
- **Evidence:** `controllers/homelab-capacity/src/homelab_capacity/config.py:6` hardcodes both host identities; line 35 requires rollout modes to match that inventory exactly. `controllers/homelab-capacity/src/homelab_capacity/kueue.py:7` hardcodes flavor mappings and line 28 rejects unknown flavors. `charts/homelab-queue/templates/queue.yaml:60` gives secondary the same quota values as primary.
- **Status:** IMPLEMENTED-BUT-FLAWED
- **Failure scenario:** An operator introduces a differently sized GPU worker and its ResourceFlavor. The power controller rejects the unregistered flavor, and the chart cannot express that host’s independent budget through the existing two-host structure.
- **Fix:** Generate queue flavors and controller mappings from one validated inventory containing per-host resources, capabilities, dependencies, and power adapters. Retain explicit identity enrollment and commissioning gates.
- **Confidence:** High

**F6 — Resource budgeting does not provide CPU/NUMA isolation.**

- **Severity:** Medium
- **Claim:** The configured CPU budgets lack the placement controls needed to isolate latency-sensitive execution from shared-worker contention.
- **Evidence:** `config/environments/proxmox/homelab/talos/patches/common.yaml:2` configures kubelet TLS without CPU/topology policies; `live/proxmox/homelab/main.tf:24` exposes one virtual socket without CPU affinity. `charts/homelab-ai/values.yaml:3` uses a fractional 29.5-CPU inference allocation; `config/environments/kubernetes/homelab-ci/pool-values.yaml:11` expresses platform reserve as budget values.
- **Status:** MISSING
- **Failure scenario:** Inference runs alongside platform services on shared CPUs, producing variable tail latency despite staying within queue quotas.
- **Fix:** Create a measured latency-oriented node profile with host CPU placement, kubelet reservations, static CPU allocation for eligible integer-CPU Guaranteed workloads, and topology alignment where hardware requires it. Benchmark under concurrent platform load.
- **Confidence:** Medium

3. **Strengths**

- Admission requires explicit resource requests and restricts gate removal to Kueue (`charts/homelab-queue/templates/admission.yaml:47`).
- Power admission tracks secondary CI’s primary-host dependency (`controllers/homelab-capacity/src/homelab_capacity/kueue.py:34`).
- AI shutdown requires verified activity observations and resets idle tracking across observation gaps (`apps/platform/lifecycle/state.py:132`).
- Lifecycle owns runtime replicas explicitly, avoiding Helm ownership conflicts (`charts/homelab-ai/templates/resources.yaml:43`).
- Argo CD’s inactive application ownership is documented clearly, avoiding accidental dual management (`kubernetes/platform/main/README.md:77`).