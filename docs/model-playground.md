# Model playground specification

Status: decided on 2026-09-26 through wayfinder map
[#237](https://github.com/TusharSariyaOrg/aws-account-infra/issues/237); every section
links the ticket that holds the detail. Execution is handed off as the OpenSpec changes
listed at the end. Terms follow `CONTEXT.md` (model playground, inference backend, model
catalog, fit rule, context reserve, backend overhead, memory budget, on-invoke policy).

## Goal

One **model playground** reachable from a phone over Tailscale: load any Hugging Face GGUF
quant by URL, switch models, keep system-prompt presets and per-chat parameters, routed by a
thin router across inference backends with wake-on-tap. Single user, Tailscale-only, app
login on top. Odysseus is unchanged and coexists for research, search and RAG.

Out of scope: a Mac or MLX backend, safetensors conversion on homelab hardware, multi-user
accounts, public exposure, voice, RAG over documents, extending the batch inference gateway,
buying GPUs. Deferred (fog on the map): desktop GPU backend profile and partial offload once
#212 lands, image input for vision GGUFs, chat memory and context compaction, handoff of
sizing and readiness to the app-development map.

## Backends

| Backend | Host | Memory budget | Overhead | KV cache | Wake |
|---|---|---|---|---|---|
| server CPU | AI Pod Ollama on `talos-worker-01` | 56 GiB | 6 GiB | q8_0 | `wake-ollama` gateway, then the AI lifecycle, then Kueue |
| desktop GPU | RTX 3060 Ti 8 GiB, pending #212 | to be measured | to be measured | q8_0 | manual power; reported `offline` |

Ollama on every backend, one loaded model, one parallel slot, `OLLAMA_MAX_LOADED_MODELS=1`,
`OLLAMA_KV_CACHE_TYPE=q8_0`, `OLLAMA_FLASH_ATTENTION=1` set explicitly in the chart. Ollama
0.34.0 supports `hf.co/org/repo:QUANT` pulls, per-request `num_ctx`, `/api/ps`
`context_length` and streamed `/api/pull` (#241). Private Hugging Face repos need the
Ollama SSH key on the account and the `huggingface.co` host.

Measured on the server CPU backend (#242): cold tap to a proxying gateway 12 min 37 s, to
first token 16 min; 27B Q4_K_M generation 1.5 to 1.8 tok/s, prompt 7 to 14 tok/s, load
from disk 20 to 40 s, 22 GB runner RSS at 8192 context; 15 GiB pulls take 10 min. Keep-warm
is ruled out; the owner accepts the wake.

## Router

A custom thin Python proxy in the style of the existing controllers
([ADR 0001](adr/0001-playground-thin-router-speaks-ollama.md), #246). It presents the
**Ollama API** to the UI and intercepts four routes:

- `/api/tags`: merged list across backends; each model shows which backends hold a copy and
  desktop copies show `offline` while the desktop is off.
- `/api/pull`: chooses the backend (user's pick, server default), wakes it if needed, emits
  synthetic pull-status lines in the wake vocabulary, then proxies the real pull stream.
- `/api/chat`, `/api/generate`: applies the fit rule, wakes the backend, streams prefixed
  progress chunks until the model answers.
- Everything else passes through to the chosen backend.

Auth: bearer on both hops (UI to router with a router Secret, router to backend with that
backend's model-user token). State: SQLite on a backed-up claim with the batch gateway's WAL
discipline for the catalog, override flags and pull jobs; backend profiles as Helm-managed
config. Borrowed from the batch gateway (#238): profile schema, backend vocabulary without
automatic fallback, bearer compare, health-probe shape. Never duplicated: batch retries,
desktop enrollment, hostPath caching.

## Fit rule (#244)

`weights + context_reserve + overhead ≤ budget`, with
`context_reserve = bytes_per_token × requested_context + fixed_cache`, one slot.

- `weights`: GGUF file size. `bytes_per_token`, `fixed_cache`: derived from the GGUF header
  at add time (global versus sliding-window or recurrent layers, KV heads, head size, the
  backend's KV type); unknown architectures fall back to every layer as full attention.
- `overhead` and `budget`: per backend, above. Re-measure overhead when batch size or the
  Ollama version changes.
- Requested context: missing `num_ctx` means 8192; values above the model's native maximum
  are rejected by the router. Context is offered as fixed presets 8k, 16k, 32k and native
  maximum, because changing `num_ctx` reloads the model; other values round up to their
  ceiling preset.
- Override: a per-model catalog flag `fit_override` on the router's admin page, never per
  message.
- Refusal: the router streams one line naming the requested context, bytes needed, backend
  budget and the largest preset that fits. No silent clamp, no smaller-model fallback.

## Model catalog (#245)

Technical facts only: source `hf.co/org/repo:QUANT`, architecture, weight bytes, native
context, derived `bytes_per_token` and `fixed_cache`, `fit_override`, and per backend a copy
record with the Ollama digest and pull time. Presets (system prompt, default parameters)
live in Open WebUI workspace models. Each backend's `/api/tags` is the truth for copy
presence, reconciled whenever that backend is awake. Removal deletes every copy and the row;
chats keep the name and fail on next use with the refusal line. A moved upstream tag shows
as a different digest on re-pull. No automatic deletion for disk pressure.

## UI (#243, #248)

Open WebUI, installed as a phone PWA. Native: chat history, login, SQLite data, model
switching, pulls by `hf.co` URL with progress, per-chat `num_ctx`, workspace-model presets.
It does not understand a waking backend or route by fit, which is why the router exists.
SillyTavern was rejected: squeezed desktop layout, roleplay structure, basic auth only, no
model manager; its richer presets are noted for a later enhancement inside workspace models.

## Wake contract (#247)

Trigger through the wake gateways, observe through the AI lifecycle `wake-status` and the
coordinator host phase. Stage vocabulary, each with elapsed and typical time: `host powering
on` (60 s), `worker joining` (5 min), `runtime queued`, `runtime starting` (30 s), then while
the answer is silent (change 4): `loading weights, N of M GiB in memory` and `processing
prompt, ~T tokens at R tok/s`, whose typical figures are the last measured load and prompt
rate for that model (the line says when none exists yet), then `ready`. The router holds the
stream open and emits `[waking] <stage>, <elapsed> of ~<typical>` chunks; the same words are
the synthetic pull-status lines. A gateway 503 during the silent wait means the runtime
stopped between the probe and the request; the router waits for it and sends once more. Cap 25 minutes, then one line naming the stage reached while the wake
continues in the background. Navigating away costs nothing. Desktop off is refused with
"desktop is off, power it on and retry". Opening the app while the host sleeps shows the
`wake-playground` gateway's 503 page, reworded to "waking, about 10 minutes", with
auto-refresh.

## Deployment shape (#249)

The control-plane guest is full (98 percent CPU, 88 percent memory requests), so:

- One chart `charts/homelab-playground` with two Deployments, router and Open WebUI, in
  `homelab-models` on the primary worker as platform pods outside Kueue, released from
  `live/kubernetes/homelab` after `homelab-ai` through the placement post-renderer and the
  `apply` label. Router 100m/128Mi to 500m/256Mi; Open WebUI 250m/512Mi to 1 CPU/1.5Gi.
- A `wake-playground` entry in `platform/automatic-power/gateways.json`; one Tailscale
  hostname `playground`; the router has no ingress.
- Two `worker-local-retain` claims (UI data, router state) added to the AI data backup scope
  under the 24-hour loss bound.
- Secrets: a setup wizard issues the router bearer and Open WebUI secret key into `prod`;
  the apps bootstrap reconciles them with the new names in its allow list; the model-user
  token is reused from `ai-runtime-credentials`.
- Network policies mirror the AI chart: gateway to UI, UI to router, router to Ollama and
  the lifecycle only.
- The AI runtime gets a dedicated Kueue ClusterQueue with a reserved slice so CI runners
  never starve it (#255); CI keeps BestEffortFIFO on the remainder, never preempted.
- The AI runtime keeps its on-invoke policy and 5-minute idle; host idle counts gateway
  activity.

## Acceptance criteria

1. From a powered-off primary, opening `playground` on the phone shows the waking page and
   loads the app within 15 minutes without manual steps.
2. A chat on a cold runtime streams the stage chunks and then the answer; the connection is
   never cut during a silent load (#252 fix, verified 78.7 s silent).
3. A verified-idle stop follows the last request within 6 minutes with zero open activity
   tickets (#253 fix, verified 5 min 17 s), and the host powers off afterwards.
4. Adding `hf.co/<org>/<repo>:Q4_K_M` from the phone pulls to the server and appears in the
   merged list with its digest; removing it deletes the copy.
5. A chat with a context that does not fit is refused with the one-line message naming the
   largest fitting preset, without starting the runtime; this is the CI check.
6. A pull or chat targeting the desktop while it is off is refused explicitly.
7. Both claims restore from the AI data backup in the isolated restore proof.

## OpenSpec changes (execution handoff)

Run through the existing root and `apply` label, in this order:

1. `add-playground-runtime-settings`: chart env for KV cache type, flash attention, max
   loaded models; the dedicated Kueue ClusterQueue and reserved slice; `wake-playground`
   gateway entry and reworded 503 page. Modifies `homelab-workload-scheduling`.
2. `add-playground-router`: the thin router image and chart half, catalog schema, fit rule,
   wake contract, bearer secrets and wizard, backup scope, network policies, the synthetic
   refusal CI check. New capability `model-playground`.
3. `add-playground-ui`: Open WebUI Deployment, claim, hostname, login, workspace-model
   presets, PWA verification from a phone.
4. Later, gated on #212: `add-playground-desktop-backend` for the GPU profile, partial
   offload rule and manual-power reporting.

## App-development map

The playground is the first app that #38 deferred: app, user, private access, data needs
and the source-to-running path are decided here, and no new GitOps, ingress or identity
stack is introduced. #40's budget is given above (router and UI envelope, runtime slice);
its representative run and #41's developer handoff (build, deploy, reach, logs, roll back,
remove) are execution evidence that the OpenSpec changes produce, so those two tickets close
when change 3 is verified, not now.
