# What the batch inference gateway lacks for interactive chat routing

Research updated: 2026-09-26. Supports [Research what the batch inference gateway lacks for interactive chat routing](https://github.com/TusharSariyaOrg/aws-account-infra/issues/238), a child of the model playground map [#237](https://github.com/TusharSariyaOrg/aws-account-infra/issues/237). Source review of `main` at `f80746b` only; no live changes. Line numbers refer to that commit.

## Summary

The gateway in `apps/platform/inference/` is a durable, at-most-one-slot-per-backend job runner for a **fixed, Helm-declared model per backend**. Every property the playground needs is either hard-coded away or structurally absent: the model is a Pod argument, the context is a fixed 4096, the execution deadline is 120 seconds with a 1 MiB result cap, `/v1/models` does not exist, and wake is delegated to Kueue with a 30-second admission window that a sleeping server cannot meet. The decision to build a separate thin router stands; the pieces worth borrowing are the backend profile schema, the ordering and policy vocabulary, the bearer-token auth pattern, the Kubernetes health probe, the wake gateway that already exists elsewhere, and the SQLite transaction discipline (not the schema).

## Gap list

### 1. Dynamic model loading and switching: absent by design

- A backend profile pins exactly one model. The runtime Pod is launched with `--model /models/<modelFile>` and `--alias <model>` baked into the container args (`apps/platform/inference/runtime.py:128-135`), so switching a model means deleting and recreating the Pod, which only reconciliation does.
- `Gateway.validate` rejects any `model` not in the profile set (`gateway.py:36-37`). There is no route that accepts a Hugging Face URL, and no state to record a loaded model per backend.
- The Talos cache init container downloads one checksum-pinned file from `MODEL_URL`/`MODEL_SHA256` and refuses anything over 2 GiB (`cache.py:13-14`, `cache.py:32-33`). The desktop cache is Ansible-owned and not touched by the gateway at all (`runtime.py:175-177`, `platform/gpu-worker/README.md:76-80`).
- Helm requires every backend image and (when enabled) every profile's `acceptedNodeUID` at render time (`charts/homelab-inference/templates/resources.yaml:26-36`), so adding a model is a reviewed Helm change through the `apply` label, not a runtime action.

**Conclusion.** The playground's catalog, on-demand download to the chosen backend, and one-loaded-model-at-a-time switch are entirely the router's to build. The gateway offers nothing here except the checksum-and-atomic-rename discipline in `cache.py:19-42`, which applies only if the playground pins hashes; the map decided on arbitrary Hugging Face URLs, so even that is partial.

### 2. Streaming beyond the 120-second deadline: hard-capped

- Execution starts a `threading.Timer(executionSeconds, interrupt)` that shuts the backend socket (`gateway.py:106-108`), and the stream loop independently raises `TimeoutError` past the same limit (`gateway.py:128-131`). The default is 120 seconds in both code and chart (`charts/homelab-inference/values.yaml:22`).
- The stream is also bounded at 1 MiB total and 64 KiB per chunk (`gateway.py:136-137`); the buffered copy is stored as the durable result (`gateway.py:149`, `store.py:214-216`).
- The client side polls a `queue.Queue(maxsize=64)` for `executionSeconds + 40` seconds then stops (`gateway.py:308`, `gateway.py:338-341`). An interrupted stream closes without `[DONE]` and is never retried (`gateway.py:350`, `store.py:240-242`).
- HTTP request bodies are capped at 64 KiB and `max_tokens` at 4096 (`gateway.py:52-54`, `gateway.py:257`), which is below the map's default 8192 context.
- The handler socket timeout is 10 seconds (`gateway.py:191`) and total HTTP concurrency is 32 (`gateway.py:376`).

**Conclusion.** Interactive chat on a CPU Xeon without AVX2 will routinely exceed 120 seconds and 1 MiB of SSE. Raising `executionSeconds` does not help because the cap exists to fence uncertain work for retries (`README.md:143-148`), which is the wrong contract for a chat that must simply stream until the model stops. The router must proxy SSE without a total-duration timeout and without buffering the whole body.

### 3. Unified model list across backends: absent

- There is no `GET /v1/models`. `do_GET` serves only `/healthz` and `/v1/requests/<id>[/result]` (`gateway.py:215-250`).
- The only model inventory is the static profile list in `config.json`, mounted from a ConfigMap (`resources.yaml:208-212`), and every example profile declares the same `Qwen3-0.6B-Q8_0` (`platform/gpu-worker/profiles.example.json`).
- The AI Pod Ollama on port 11434 is a separate service in `charts/homelab-ai` and is never consulted by the gateway; the lifecycle doc describes its model gateway as compiled into the pinned Ollama server (`docs/homelab-lifecycle.md:15`).

**Conclusion.** The router owns the catalog: one record per backend per model, downloaded on demand, as the map decided. It must merge what each backend's Ollama reports (`/api/tags`) with its own catalog and the fit rule. Nothing in the gateway is reusable for this.

### 4. Per-request context length: fixed at 4096

- `--ctx-size 4096` and `--parallel 1` are hard-coded in the runtime Pod args (`runtime.py:137-140`); profile `args` can append but not override safely, and either way the value is process-level, not per request.
- The validated allowlist forwards only `model`, `messages`, `max_tokens`, `stream`, `temperature` (`gateway.py:55-67`). No `num_ctx`, `options`, or system-prompt preset shape passes through; the comment states this is deliberate ("never arbitrary backend configuration").

**Conclusion.** The map's per-chat user-selectable context (default 8192, up to native maximum, subject to the fit rule, with KV cache quantisation) requires the router to pass Ollama `options.num_ctx` per request and to reload the model when the context changes. The gateway would have to be widened at exactly the boundary it exists to narrow.

### 5. Wake handshake: delegated to Kueue with a 30-second admission window

- Live requests get a hard 30-second admission deadline (`store.py:120`, `store.py:133-137`) and the handler returns 504 when it lapses (`gateway.py:326-329`). The README states "Admission expires at 30 seconds" (`README.md:120-121`).
- Wake is implicit: creating the Kueue-labelled runtime Pod (`runtime.py:229`) is what triggers the server power path, and the code comment says "Existing Kueue checks alone wake it" (`runtime.py:361`). Nothing reports progress; the client only sees `state: queued` then 504.
- The acceptance matrix treats wake-through-reservation as a gate to prove, and GPU-only waits explicitly must not wake servers (`README.md:165`). CPU runtimes are also torn down after 5 idle minutes (`runtime.py:354-359`), which collides with the map's reuse of the 30-minute AI Pod idle window.
- The actual user-facing wake gateway lives elsewhere: `wake-ollama` and `wake-odysseus` Pods in `charts/homelab-ai/templates/network.yaml:11-16`, allow-listed in `charts/homelab-queue/templates/admission.yaml:21`, with a documented cold-request contract of HTTP 503 plus `Retry-After: 10` (`docs/runbooks/automatic-server-power.md:47-49`).

**Conclusion.** Wake-on-tap with progress is a router concern layered on the existing `wake-ollama` gateway and the 503/Retry-After contract, not on the inference gateway's Kueue reservation. The gateway's 30-second window is incompatible with a multi-minute Proxmox and Talos boot.

### 6. Other mismatches worth recording

- Access is opt-in via `kubectl port-forward` with main-cluster credentials, no ingress (`README.md:115-117`); the gateway Deployment has no Tailscale Ingress and its NetworkPolicy admits only its own Pod on 8080 (`resources.yaml:284-293`). The playground needs Tailscale operator ingress.
- Text-only messages with `role` in `{system, user, assistant}` and string `content` (`gateway.py:41-47`); no image input for a future vision GGUF.
- Backend URL is the llama.cpp Pod IP on 8080 with `/v1/chat/completions` and `/health` (`runtime.py:90-91`, `gateway.py:113-118`); the playground backends are Ollama on 11434 with `/api/*` and `/v1/*`, and Ollama's `keep_alive` and model residency semantics differ from llama.cpp's single-model process.
- SQLite retains at most 512 requests including results and returns 429 when full, with no export automation (`store.py:21`, `store.py:106-107`, `README.md:150-154`). Chat history needs unbounded, backed-up storage, which the map already assigns to the application backup scope (`docs/homelab-lifecycle.md:51`).

## What the thin router may borrow

| Piece | Where | How to reuse | Do not copy |
| --- | --- | --- | --- |
| Backend profile schema | `profiles.example.json`; validated at `resources.yaml:27-36` | `id`, `node`, `kind` (`cpu`/`gpu`), `desktop`, `priority`, `resources`, `queue`, `enabled`, `acceptedNodeUID`, `nodeIP` are exactly the fields a backend profile needs; add `budgetGi`, `ollamaURL`, `nativeContextCap`, and drop `model`/`modelFile`/`modelSHA256` (the catalog owns those) | Per-profile single `model` |
| Ordering and policy vocabulary | `store.py:10`, `store.py:14-17`; `README.md:134-136` | `backend_order` (GPU, then desktop CPU, then server CPU, ties by `priority`) and the three policies `gpu-preferred`/`gpu-required`/`cpu-only` map directly onto the playground's manual backend pick with "no silent smaller-model fallback" | Automatic fallback across backends; the playground picks explicitly |
| Kueue reservation pattern | `runtime.py:229` label `kueue.x-k8s.io/queue-name`; `resources.yaml:55-93` flavors and queues; `runtime.py:354-366` demand-driven Pod create/delete | Only if the playground places its own runtime Pods. The map reuses the existing AI Pod Ollama, so the router should **not** create Kueue Pods for the server; the desktop GPU profile (open item on #237) may adopt the `desktop` LocalQueue and `ResourceFlavor` when #212 lands | The 5-minute CPU teardown (`runtime.py:359`) and the 30-second admission deadline |
| Bearer auth | `gateway.py:208-213`, `gateway.py:398-400`, `resources.yaml:274` | Constant-time compare of an external Secret-mounted token of 32+ characters is the right minimal app login on top of Tailscale; keep the same Secret-not-in-Git rule | Nothing; this is sound as is |
| Backend health probe | `runtime.py:66-96` | The shape (node accepted UID, node Ready and no pressure, Cilium Pod Ready on that node, then an HTTP `/health`) is what a wake progress indicator should report step by step; swap the final probe to Ollama `/api/tags` | The GPU allocatable check is only for Kueue-placed Pods |
| Kubernetes adapter | `runtime.py:14-45` | Minimal in-cluster `urllib` client with service-account token and CA; enough for node and Pod reads without a client library | The node-taint PATCH loop (`runtime.py:300-338`) is desktop quarantine logic the router does not need |
| SQLite discipline | `store.py:41-59` | WAL, `synchronous=FULL`, `busy_timeout`, `BEGIN IMMEDIATE` transactions; a single-process `flock` at `gateway.py:402-403`; state under `/var/lib/homelab-inference` on the control-plane VM (`values.yaml:17`, `README.md:87-89`) | The `requests`/`attempts`/`fairness` tables and the `one_slot` index; chats and presets are a different schema and must join the application backup, not laptop-local hostPath |
| Idempotency-Key handling | `store.py:82-101` | Useful for "send" retries on a flaky phone link if the router queues wake-then-send | Stream replay rejection is a batch concern |
| Wake contract | `charts/homelab-ai/templates/network.yaml:15`, `docs/runbooks/automatic-server-power.md:47-49` | The router fronts `wake-ollama` and turns 503 + `Retry-After` into a progress UI; the AI Pod's 30-minute idle window already applies | Do not add a second wake path through Kueue reservations for the server |

## What the router must not duplicate

- Durable at-least-once batch execution, retries, uncertainty fencing and result retention (`store.py:213-298`, `README.md:143-154`). The playground is a single-user interactive surface; a dropped stream is shown to the user, not fenced and retried.
- Desktop enrollment, serving-CSR approval and quarantine taints (`certificates.py`, `runtime.py:300-338`, `charts/homelab-inference/templates/enrollment.yaml`). These stay with #212.
- Model cache ownership on Talos hostPath via init containers (`runtime.py:187-217`). The playground downloads into the existing 300 GiB `ollama-models` volume through Ollama itself.

## Sources

- `apps/platform/inference/gateway.py`, `runtime.py`, `store.py`, `cache.py` at `f80746b`
- `platform/gpu-worker/README.md`, `platform/gpu-worker/profiles.example.json`
- `charts/homelab-inference/Chart.yaml`, `values.yaml`, `templates/resources.yaml`, `templates/enrollment.yaml`
- `charts/homelab-ai/templates/network.yaml`, `charts/homelab-queue/templates/admission.yaml`
- `docs/homelab-lifecycle.md`, `docs/runbooks/automatic-server-power.md`
- Map decisions in [#237](https://github.com/TusharSariyaOrg/aws-account-infra/issues/237)
