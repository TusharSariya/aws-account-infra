## Why

The playground spec (`docs/model-playground.md`) needs the thin router before any UI can be useful: Open WebUI cannot wake a backend, apply the fit rule or choose a backend, and the batch inference gateway was ruled out as a base (ADR 0001).

## What Changes

- Add `apps/platform/playground`: a Python router presenting the Ollama API, intercepting `/api/tags` (merged list), `/api/pull` (backend choice, wake, synthetic progress, catalog registration), `/api/chat` and `/api/generate` (fit rule, wake progress, model-load progress) and `/api/delete`; bearer auth on both hops; SQLite catalog on a retained claim.
- Add chart `charts/homelab-playground` released from `live/kubernetes/homelab` after `homelab-ai`, with the router Deployment, RBAC to read the worker node and runtime Pods for stage naming, network policies, and an Open WebUI half switched off until change 3.
- Issue the router bearer and Open WebUI secret key with `scripts/playground-setup-wizard.sh` into `prod` as `PLAYGROUND_CREDENTIALS_B64`; the apps bootstrap reconciles `playground-router-auth` and `playground-ui`.
- Let the router through the `wake-ollama` gateway's network policy (gateway entries gain `clients`).

## Capabilities

### Modified Capabilities

- `model-playground`: router, fit rule, catalog and wake contract requirements (change 1 added the platform settings).
