## Context

Decisions come from map #237: router (#246), fit rule (#244), catalog (#245), wake contract (#247), deployment shape (#249). Measured facts: cold loads and switches are silent for 60 to 80 s, the wake gateway's idle guard is 30 minutes, the runtime needs the whole worker pool.

## Decisions

- **Code ships as a ConfigMap on a plain Python image**, like the inference gateway and the lifecycle controller; no image build. The root injects `apps/platform/playground/*.py`.
- **All server traffic goes through `wake-ollama`.** The router never talks to the AI Pod directly, so the first request is the wake and the gateway's credential path is exercised on every wake.
- **Stage naming reads the cluster, not the coordinator.** Node Ready and runtime Pod phase name `host powering on` (first 90 s while the node is NotReady), `worker joining`, `runtime queued` (Pending with no container state), `runtime starting`; the gateway's 200 is `ready`; silence after forwarding is `model loading`. The coordinator lives on the laptop and is not reachable from the cluster by design.
- **Progress is assistant text.** Open WebUI cannot render a custom waiting state, so progress lines prefixed `[waking]` stream as content chunks in the Ollama response shape; the answer follows in the same stream. A refusal is a single done chunk with the fit line, HTTP 200, so the UI shows it as a message.
- **Catalog numbers come from `/api/show`.** `fit.derive` reads `model_info`; gemma3 and gemma4 use the known 1-in-6 global-layer interleave with a fixed 1,536-cell sliding-window cache; unknown architectures count every layer as global (conservative). Verified against the research note's figures in tests.
- **Context presets** 8k, 16k, 32k, native; a missing `num_ctx` is the 8k preset (or native max when smaller); above native is refused.
- **Override** is a catalog flag set through `POST /admin/override`.
- **Backup**: the router claim joins the AI data backup in change 3 together with the UI claim, so the backup scope changes once.

## Risks

The router's own memory is small (256Mi) and it streams upstream bodies line by line without buffering. A backend that never answers a forwarded request holds a thread until the 3600 s urllib timeout; the wake cap (25 min) only covers the pre-forward wait.
