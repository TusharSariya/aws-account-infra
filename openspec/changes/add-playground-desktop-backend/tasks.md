## 1. Management root

- [ ] 1.1 `charts/homelab-inference`: `desktopQuota` flag separate from `enabled`; the `desktop-compute` ClusterQueue gets its capped quota (12 CPU, 24 GiB, 1 GPU) without the llama.cpp gateway; the render guard still requires measured capacity and `acceptedNodeUID`.
- [ ] 1.2 Guard test case for `desktopQuota` in `apps/platform/inference/tests/test_chart.py`.
- [ ] 1.3 Admission dispatch after merge; `desktop-compute` shows the quota.

## 2. Apps root

- [ ] 2.1 `charts/homelab-playground/templates/desktop.yaml` gated by `desktop.enabled`: Deployment `desktop-ollama` in `homelab-inference` (Ollama pinned by digest, `runtimeClassName: nvidia`, `nvidia.com/gpu: 1`, `nodeSelector` hostname `ubuntu-gpu-01`, tolerates `compute` only, `queue-name: desktop` and priority labels, 20 GiB limit, same Ollama env as the server).
- [ ] 2.2 Local retained PersistentVolume and claim on the desktop disk (about 150 GiB), outside the application backup.
- [ ] 2.3 Service `desktop-ollama:11434` and a NetworkPolicy admitting only `playground-router`.
- [ ] 2.4 Router chart: egress to `homelab-inference` `app: desktop-ollama` on 11434; backends config gains `desktop` (url `http://desktop-ollama.homelab-inference.svc:11434`, `manual_power: true`, budget 26 GiB and overhead 2 GiB placeholders, `kv_type: q8_0`, no `node` or `token_file`).
- [ ] 2.5 UI: `OLLAMA_BASE_URLS` set to the two router prefixes and `OLLAMA_API_CONFIGS` with the bearer and `prefix_id` `server` and `desktop`; one-time update of the live instance's persisted connection config.
- [ ] 2.6 Chart tests in `scripts/tests/test_lifecycle_charts.py`: desktop objects only when enabled, GPU and toleration, NetworkPolicy, queue label; `helm lint`.

## 3. Router

- [ ] 3.1 Path prefixes `/b/<name>` pin chat, generate and pull to that backend and filter `/api/tags` to its copies; the unprefixed root stays the default backend.
- [ ] 3.2 Manual power: passthrough and streamed refusal "desktop is off, power it on and retry"; no wake call and no server fallback.
- [ ] 3.3 Pending delete: copies on an asleep backend are kept pending and deleted on its next awake merge.
- [ ] 3.4 Desktop stage lines from `/api/ps` only; no kubelet memory read.
- [ ] 3.5 Tests in `apps/platform/playground/tests/test_router.py` with a second fake backend: prefix routing for chat and pull, tags per prefix, desktop-off refusal without touching the server, pending delete.

## 4. Ansible

- [ ] 4.1 Host directory for `ubuntu-gpu-01` under `ansible/` with its inventory variables.

## 5. Operator steps (on hardware)

- [ ] 5.1 Desktop acceptance: GPU visible to a pod, disk space for the model volume.
- [ ] 5.2 Remove the `homelab.tfdraw.dev/quarantine` taint; `desktop-ollama` becomes Ready on `ubuntu-gpu-01` and admitted by `desktop-compute`.
- [ ] 5.3 Measure the budget: load a 27B at 8192 context and read VRAM and RAM use.
- [ ] 5.4 Set the measured budget and overhead in the backends config and the spec table.
- [ ] 5.5 From the phone, pull `hf.co/bartowski/TheDrummer_Fallen-Gemma3-27B-v1-GGUF:Q4_K_M` and `hf.co/mradermacher/Qwen3.8-27B-Heretic-JP-Roleplay-NSFW-DanbooruTags-i1-GGUF:Q4_K_M` to the `desktop` connection; both list as `desktop.<model>`.
- [ ] 5.6 Chat on each; record first-token time and generation tok/s against the server's 1.5 tok/s.
- [ ] 5.7 Off path: power the desktop off; a desktop chat returns "desktop is off, power it on and retry" at once, server models are unaffected and the servers are not woken; a server cold chat still shows the stage lines.
