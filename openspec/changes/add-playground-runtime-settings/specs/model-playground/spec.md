## Purpose

Platform settings the model playground relies on before its router and UI exist.

## ADDED Requirements

### Requirement: Fit-rule consistent runtime
Every inference backend's Ollama SHALL run with `OLLAMA_KV_CACHE_TYPE=q8_0`, flash attention enabled and one loaded model, so the fit rule's per-token figures match the runtime.

#### Scenario: Rendered runtime
- **WHEN** the AI Pod or standalone Ollama chart is rendered
- **THEN** the Ollama container declares `OLLAMA_KV_CACHE_TYPE=q8_0`, `OLLAMA_FLASH_ATTENTION=1` and `OLLAMA_MAX_LOADED_MODELS=1`

### Requirement: Runtime admission ahead of CI
The shared ClusterQueue SHALL admit in strict FIFO order so a pending AI runtime is never passed by later, smaller workloads, and running CI work SHALL never be interrupted or preempted for it.

#### Scenario: Runtime pending behind runners
- **WHEN** the runtime workload is at the head of `homelab-compute` and runner Pods hold part of the quota
- **THEN** no later runner is admitted until the runtime is admitted, and the running runners finish normally

### Requirement: Playground wake gateway
An always-on `wake-playground` gateway SHALL front the playground UI so a cold request wakes the primary host and shows a page that names the wait and refreshes itself.

#### Scenario: Cold browser request
- **WHEN** a browser requests the playground while the host is off
- **THEN** it receives 503 with `Retry-After: 10`, a `Refresh: 10` header and a body starting "Waking the playground server"
