## Why

Every playground model runs on the server CPU backend, `talos-worker-01`, where a 27B model generates at about 1.5 tok/s and processes prompts at about 7.5 tok/s. The Ubuntu desktop `ubuntu-gpu-01` is now a Ready node with an RTX 3060 Ti (8 GiB VRAM), 31 GiB RAM and the NVIDIA device plugin running, but nothing serves chats from it. The owner wants the Gemma and Qwen 27B models on the desktop and chats routed there. The router already models several backends (`manual_power`, per-backend copies and budgets), but Open WebUI cannot choose a backend, pulls always land on the default, the chart assumes one backend, and a delete orphans copies on an asleep backend.

## What Changes

- **Desktop Ollama** in `charts/homelab-playground` (`desktop.enabled`): a Deployment `desktop-ollama` in `homelab-inference`, pinned to `ubuntu-gpu-01` with `runtimeClassName: nvidia` and one GPU, the same Ollama settings as the server, the `desktop` Kueue queue label, a Service on 11434, a NetworkPolicy admitting only `playground-router`, and a local retained model volume.
- **Desktop quota** in `charts/homelab-inference`: a `desktopQuota` flag, separate from `enabled`, gives the `desktop-compute` ClusterQueue its capped quota without deploying the batch llama.cpp gateway.
- **Path-prefixed backends** in the router: `/b/server/...` and `/b/desktop/...` each present one backend's Ollama API; the unprefixed root stays the default backend. Open WebUI gets two connections with `prefix_id` `server` and `desktop`.
- **Manual power** end to end: a desktop request while it is off is refused at once with "desktop is off, power it on and retry"; the server is never touched and the servers are never woken.
- **Pending delete**: deleting a model while a backend is asleep records the copy as pending and deletes it on that backend's next awake merge.
- **Desktop fit and stages**: budget = pod RAM limit + VRAM - headroom (placeholder 26 GiB, overhead 2 GiB, until measured); desktop stage lines use `/api/ps` only.
- **Ansible host directory** for `ubuntu-gpu-01` and the operator steps: acceptance, lifting quarantine, measuring the budget, pulling both 27B models.

## Capabilities

### Modified Capabilities

- `model-playground`: backend selection by path prefix, manual-power refusal, pending delete, desktop fit rule, desktop isolation from server wake.

## Impact

- Management root: `charts/homelab-inference` values and guard test; the admission dispatch after merge.
- Apps root (`apply` label): `charts/homelab-playground` desktop, router and UI templates; `apps/platform/playground/router.py`, `catalog.py` and tests; chart tests in `scripts/tests/test_lifecycle_charts.py`.
- Live Open WebUI: a one-time update of its persisted connection config.
- Docs: `docs/model-playground.md` backends table, routing section, fit rule and criterion 6.
- Not affected: the coordinator, the server backend's wake path, the batch inference gateway's own enablement.
