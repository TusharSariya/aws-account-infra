# LiteLLM as the model playground router: fit-and-awake routing

Research updated: 2026-09-26. Supports [Research whether LiteLLM can express fit-and-awake routing](https://github.com/TusharSariyaOrg/aws-account-infra/issues/239), a child of [map #237](https://github.com/TusharSariyaOrg/aws-account-infra/issues/237). Documentation and source review only against LiteLLM `main` (latest release `v1.102.1` at time of reading); `main` links are moving references, not version guarantees.

## Conclusion: plugin needed

LiteLLM cannot express the fit-and-awake rule from `config.yaml` alone, and the plugin surface it does offer is a poor fit for the "wake on tap, show progress" behaviour the map decided on.

- The static half of the fit rule (which models may run on which backend) is config-only: list each model once per backend it fits under `model_list`, and omit it elsewhere. The token-budget half (`prompt + reserve <= backend budget`) is only partly expressible via `enable_pre_call_checks` plus `model_info.max_input_tokens`, which filters on prompt length against a per-deployment number, not on weights plus KV cache under a memory budget.
- The awake predicate is not expressible in config. The closest built-in, health-check-driven routing, probes every deployment with a real chat completion every `health_check_interval` seconds, which would either keep the CPU backend awake or fight the 30-minute idle shutdown. When no deployment is awake it returns a generic `429 "No healthy deployment available"`, not a structured "waking, retry after N seconds" answer, and it never triggers a wake.
- A structured waking response requires Python: either a `CustomLogger.async_pre_call_hook` raising `ProxyException(code=503, headers={"Retry-After": ...})`, or a `CustomRoutingStrategyBase` subclass, which the proxy has no config key to load and would need a wrapper entrypoint.
- The Ollama provider passes `num_ctx` (as an `options` field) and `keep_alive` (as a top-level body field) through, and streams. That part is fine.
- Footprint: the single image is about 371 MiB compressed (amd64) and the vendor's production guidance is 1 vCPU / 4 GiB per pod; the Helm chart deploys a Postgres by default. That is heavy for a single-user router in front of one or two Ollama instances.

Given the map's constraints (single user, one backend awake at a time, wake-on-tap with progress), the thin router is better written as a small service that owns the fit table, the wake gateway call and the retry-after contract, and forwards the OpenAI-compatible stream to Ollama. LiteLLM would add a Python plugin plus a 4 GiB pod to save writing a few hundred lines of forwarding code.

## Routing: what config can and cannot select

`router_settings.routing_strategy` accepts `simple-shuffle` (default), `least-busy`, `usage-based-routing`, `latency-based-routing`; `cost-based-routing` and `usage-based-routing-v2` are documented for the SDK. None takes a user predicate. [config_settings](https://docs.litellm.ai/docs/proxy/config_settings), [routing](https://docs.litellm.ai/docs/routing)

`enable_pre_call_checks: true` filters deployments in a model group whose declared context window is smaller than the prompt token count (needs `model_info.max_input_tokens` or `base_model`), whose `rpm` is exhausted, or whose `region_name` does not match. The source docstring for `Router._pre_call_checks` lists exactly those three filters. It is a prompt-length check, not a "weights plus context reserve under backend budget" check, and it cannot read backend state. [config_settings](https://docs.litellm.ai/docs/proxy/config_settings), [router.py `_pre_call_checks`](https://github.com/BerriAI/litellm/blob/main/litellm/router.py)

Several `model_list` entries may share a `model_name` with different `api_base` values, which is how two Ollama backends serving the same GGUF would be expressed. Selection between them is then one of the strategies above. [proxy load balancing](https://docs.litellm.ai/docs/proxy/load_balancing)

Custom selection exists only in Python. `CustomRoutingStrategyBase` defines `async_get_available_deployment(model, messages, input, specific_deployment, request_kwargs)` returning an element of `router.model_list`, and `Router.set_custom_routing_strategy()` monkey-patches it onto the router instance. A GitHub code search for `set_custom_routing_strategy` in `BerriAI/litellm` finds only `litellm/router_strategy/lar1_routing.py` (a built-in `routing_strategy: "lar1"`) and a test; `proxy_server.py` has no `custom_routing` reference, so there is no `config.yaml` key to load a custom strategy into the proxy. Using it means importing and patching the proxy's router from your own startup code. [routing docs, custom routing strategy](https://docs.litellm.ai/docs/routing), [types/router.py](https://github.com/BerriAI/litellm/blob/main/litellm/types/router.py), [router.py `set_custom_routing_strategy`](https://github.com/BerriAI/litellm/blob/main/litellm/router.py)

Routing plugins (v1.92+) are a pipeline over `RoutingContext` that can only narrow `candidate_models` or raise; they are registered under `complexity_router_config.plugins` of an `auto_router/complexity_router` model entry, and narrowing to zero candidates raises `ValueError` rather than a shaped response. They are read-only over the request and cannot add deployments. That is enough to drop a sleeping backend but not to answer "waking". [routing plugins](https://docs.litellm.ai/docs/routing_plugins)

## Returning "backend waking, retry after N seconds"

The proxy hook surface is `CustomLogger.async_pre_call_hook(user_api_key_dict, cache, data, call_type)`, registered via `litellm_settings.callbacks: custom_callbacks.proxy_handler_instance`. It runs before routing and sees `data["model"]` (the model group name), so it can consult backend state, call the wake gateway and reject. It may return a modified `data`, return a string (which becomes an assistant message for chat endpoints), or raise `HTTPException(status_code, detail)`. [call hooks](https://docs.litellm.ai/docs/proxy/call_hooks)

Header behaviour matters for a retry contract. In `litellm/proxy/utils.py`, an `HTTPException` raised by a hook is rewrapped as `ProxyException(message=e.detail, code=e.status_code, headers=litellm_call_id_headers(...))`: the HTTPException's own headers are discarded, only the call-id header survives. A `ProxyException` raised directly is passed through with its `headers` intact (`with_litellm_call_id(e, ...)`), and `ProxyException.__init__` accepts `headers: dict[str, str]`. So a hook can raise `ProxyException(message=<json string>, type=..., param=None, code=503, headers={"Retry-After": "30"})` and the client sees a 503 with a body and a `Retry-After` header. `detail` may be a dict, so the body can be structured. This works, but it is plugin code, and the "waking" state and wake trigger must live in that plugin or in a sidecar it calls. [proxy/utils.py](https://github.com/BerriAI/litellm/blob/main/litellm/proxy/utils.py), [proxy/_types.py `ProxyException`](https://github.com/BerriAI/litellm/blob/main/litellm/proxy/_types.py)

Note the router's own semantics when nothing is available: `ProxyException` rewrites "No healthy deployment available" / "No deployments available" to code `429`. Clients that treat 429 as rate limiting would back off rather than show wake progress. [proxy/_types.py](https://github.com/BerriAI/litellm/blob/main/litellm/proxy/_types.py)

Known gaps around `Retry-After` in general: upstream provider `retry-after` is only forwarded as `llm_provider-retry-after`, and retry-after on 502/503/504 is dropped in the retry loop. [issue #21553](https://github.com/BerriAI/litellm/issues/21553), [issue #16286](https://github.com/BerriAI/litellm/issues/16286), [response headers](https://docs.litellm.ai/docs/proxy/response_headers)

## Health checks and the sleeping backend

`/health` "runs a real test request against every configured model" (default prompt `test from litellm`, `max_tokens` 16). Background checks are `general_settings.background_health_checks: true` with `health_check_interval` (default 300 s); `enable_health_check_routing: true` removes a deployment from the pool on the first failed probe "until the next check cycle clears it". Per-deployment `model_info.disable_background_health_check: true` opts out. [health](https://docs.litellm.ai/docs/proxy/health), [health check routing](https://docs.litellm.ai/docs/proxy/health_check_routing)

Consequences for this design: a probe against Ollama is a chat completion, so it loads the model (or the last model) and resets Ollama's `keep_alive`, and any traffic through the wake gateway may wake the host. Either the probe keeps the CPU backend awake or the probe must be disabled, in which case LiteLLM does not know the backend is asleep and the first user request fails through into cooldown. Cooldown itself is failure-rate based (`allowed_fails`, `cooldown_time` default 5 s) and, per `cooldown_handlers._should_cooldown_deployment`, a single-deployment model group is exempt from 429-triggered cooldown so the request just errors. [cooldown_handlers.py](https://github.com/BerriAI/litellm/blob/main/litellm/router_utils/cooldown_handlers.py), [reliability](https://docs.litellm.ai/docs/proxy/reliability)

`/health/liveliness` and `/health/readiness` are process-level and do not touch backends, so Kubernetes probes are safe. [health](https://docs.litellm.ai/docs/proxy/health)

## Ollama provider: `num_ctx`, `keep_alive`, streaming

Use the `ollama_chat/` prefix (Ollama `/api/chat`), with `api_base` per deployment; default `http://localhost:11434`. Streaming is supported for sync and async, and the proxy streams through. [ollama provider](https://docs.litellm.ai/docs/providers/ollama)

`OllamaChatConfig` declares `num_ctx`, `num_predict`, `num_gpu`, `num_thread`, `repeat_penalty`, `top_k`, `seed`, `mirostat*`, `tfs_z`, `system`, `template`. In `transform_request`, `optional_params` (after `max_tokens -> num_predict`, `frequency_penalty -> repeat_penalty`) becomes the request body's `"options"` dict, and `keep_alive` is popped and set at the top level of the body, matching Ollama's API. Unknown kwargs outside that set are not forwarded. [ollama/chat/transformation.py](https://github.com/BerriAI/litellm/blob/main/litellm/llms/ollama/chat/transformation.py)

Provider-specific params may be set per deployment in `litellm_params` (the official Ollama example is `keep_alive: "8m" # ... use -1 for Forever`) or sent by the client in the request body. So a per-backend `num_ctx` and `keep_alive` are config-only; per-chat context selection from the phone would be the client passing `num_ctx` on each request. [ollama provider](https://docs.litellm.ai/docs/providers/ollama), [provider-specific params](https://docs.litellm.ai/docs/completion/provider_specific_params)

KV-cache quantisation is an Ollama server environment setting (`OLLAMA_KV_CACHE_TYPE`), not a request option, so it is outside LiteLLM either way.

## Model list aggregation across Ollama endpoints

`/v1/models` reflects `model_list` entries (plus `model_group_alias`); the proxy does not discover models from an Ollama `api_base`. The SDK has `OllamaChatConfig.get_models()` calling `/api/tags` for `litellm.get_valid_models`, but `proxy_server.py` does not call it. Wildcard entries (`model: "ollama_chat/*"`) pattern-match request names to a deployment; they do not enumerate the backend's catalog or express which of two wildcard backends holds a given GGUF. [ollama/common_utils.py](https://github.com/BerriAI/litellm/blob/main/litellm/llms/ollama/common_utils.py), [wildcard routing](https://docs.litellm.ai/docs/wildcard_routing), [proxy configs](https://docs.litellm.ai/docs/proxy/configs)

So the map's "model catalog, one copy per backend, downloaded on demand" would have to be mirrored into LiteLLM's `model_list` on every catalog change, either by regenerating the ConfigMap and restarting or via the `/model/new` management API, which requires the Postgres-backed model store. That duplicates the catalog's source of truth. [model management](https://docs.litellm.ai/docs/proxy/model_management)

## Kubernetes: how config is supplied

Raw manifests mount a ConfigMap at `/app/proxy_server_config.yaml` and start with `--config /app/proxy_server_config.yaml`; secrets are `os.environ/NAME` references resolved from env. The vendor's componentized chart is `oci://ghcr.io/berriai/litellm/chart/litellm` (config under `proxy_config` values); the in-repo chart `helm/litellm-helm` (chart 1.1.3, appVersion v1.85.1) renders `proxy_config` as `config.yaml`, accepts an existing `proxyConfigMap`, `masterkeySecretName`, and has `db.deployStandalone: true` by default with a Bitnami Postgres subchart. Running with no database is supported: "there is no key management, spend tracking, or UI persistence, so authentication falls back to the master key alone." [deploy](https://docs.litellm.ai/docs/proxy/deploy), [helm values.yaml](https://github.com/BerriAI/litellm/blob/main/helm/litellm-helm/values.yaml)

A pre-call-hook plugin would be a Python module mounted next to the config (ConfigMap or a custom image) and referenced by dotted path from `litellm_settings.callbacks`. [call hooks](https://docs.litellm.ai/docs/proxy/call_hooks)

## Image size and resource footprint

Images: `ghcr.io/berriai/litellm` (core, includes Prisma toolchain), `litellm-non_root`, `litellm-spend_logs`, `litellm-database` (legacy alias), mirrored at `docker.litellm.ai/berriai`. No slim variant is published. [docker image security](https://docs.litellm.ai/docs/proxy/docker_image_security)

Measured from the GHCR manifest for `v1.102.1` on 2026-09-26: 371 MiB compressed layers for linux/amd64, 378 MiB for linux/arm64 (a `main-latest` package page has shown about 1.98 GB uncompressed). [ghcr package](https://github.com/berriai/litellm/pkgs/container/litellm)

Production guidance: "Give each pod 1 vCPU and 4Gi of memory, as both requests and limits"; run one Uvicorn worker per pod; Redis 7+ once there is more than one instance; memory is described as a floor that tracks the largest Prisma write, not concurrency. Single-instance, no-DB deployments need neither Postgres nor Redis, but the 4 GiB recommendation is for the process itself. [prod](https://docs.litellm.ai/docs/proxy/prod)

## What a LiteLLM-based design would need

1. `model_list`: one `ollama_chat/<model>` entry per (model, backend) pair the fit rule admits, with `api_base`, `num_ctx`, `keep_alive`, `model_info.max_input_tokens`; regenerated from the catalog.
2. `enable_pre_call_checks: true` for prompt-length filtering.
3. A `CustomLogger` plugin whose `async_pre_call_hook` checks backend state, calls the wake gateway, and raises `ProxyException(code=503, headers={"Retry-After": ...})` with a JSON body while waking; and pins `data["model"]` to the awake backend's deployment when both hold the model.
4. Background health checks off (or per-deployment disabled) so probes do not keep the server awake.
5. A pod at roughly 1 vCPU / 4 GiB, no Postgres, master-key auth behind Tailscale.

Items 3 and 4 carry all the logic the playground actually needs, which is why the conclusion is plugin needed rather than config-only, and why a purpose-built thin router is the simpler path for this map.
