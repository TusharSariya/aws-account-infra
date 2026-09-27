## Why

The model playground spec (`docs/model-playground.md`) needs three platform settings before the router and UI can be built: the Ollama runtime must compute with the KV cache type the fit rule assumes, the AI runtime must not queue indefinitely behind CI runners, and the playground needs its own always-on wake gateway so a phone can open the app while the host sleeps.

## What Changes

- Set `OLLAMA_KV_CACHE_TYPE=q8_0` and `OLLAMA_FLASH_ATTENTION=1` explicitly on the AI Pod and the standalone Ollama chart; `OLLAMA_MAX_LOADED_MODELS=1` is already explicit.
- Switch `homelab-compute` from `BestEffortFIFO` to `StrictFIFO`. The AI runtime needs the whole worker pool; at the head of the queue it now blocks new runner admission until it is admitted instead of being passed indefinitely. Running CI is never interrupted and no runner is preempted.
- Register a `wake-playground` gateway in the always-on registry whose cold page says "Waking the playground server, about 10 minutes" and refreshes on its own; gateways gain an optional per-entry `message`.

## Capabilities

### New Capabilities

- `model-playground`: platform settings the playground relies on (KV cache type, runtime admission ahead of CI, playground wake gateway). Later changes add the router and UI requirements.

### Modified Capabilities

- `homelab-workload-scheduling`: `homelab-compute` admits in strict FIFO order, so a pending runtime is never passed by later runners.
