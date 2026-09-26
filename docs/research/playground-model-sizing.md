# GGUF quants and memory sizing for the three named playground models

Research updated: 2026-09-26. Supports [Research GGUF quants and memory sizing for the three named models](https://github.com/TusharSariyaOrg/aws-account-infra/issues/240) under map [#237](https://github.com/TusharSariyaOrg/aws-account-infra/issues/237). Documentation, GGUF-header and source review only; nothing was downloaded or run. This note records technical metadata only (architecture, context, file sizes, cache bytes); it does not evaluate model content. Hugging Face file sizes and headers were read from the repos' `main` revision on the date above and can change.

## Summary

| Model | GGUF arch | Native ctx | Q4_K_M | KV/token f16 | KV/token q8_0 | Fixed cache (f16 / q8_0) | Ollama 0.34.0 |
|---|---|---|---|---|---|---|---|
| Fallen-Gemma3-27B-v1 | `gemma3` | 131,072 | 15.41 GiB | 80 KiB (10 global layers) | 42.5 KiB | SWA 624 / 332 MiB | supported |
| Qwen3.8-27B-Heretic-JP-Roleplay-NSFW-DanbooruTags | `qwen35` | 262,144 | 15.41 GiB | 64 KiB (16 attention layers) | 34 KiB | recurrent state 150 MiB (f32) | supported |
| gemma-4-31B-it-heretic | `gemma4` | 262,144 | 17.40 GiB | 80 KiB (10 global layers) | 42.5 KiB | SWA 1200 / 638 MiB | supported |

"KV/token" is the part that grows with context. "Fixed cache" is allocated once per load regardless of `num_ctx` (above 1,536 tokens) and must be added to weights. Compute buffers, the mmproj (none of these text GGUFs ship one) and process overhead are not estimated here.

Weights plus KV, Q4_K_M, q8_0 KV cache (the map's chosen default), 1 parallel slot:

| Model | 8k | 32k | native max |
|---|---|---|---|
| Fallen-Gemma3-27B-v1 | 16.07 GiB | 17.06 GiB | 21.05 GiB (128k) |
| Qwen3.8-27B | 15.82 GiB | 16.62 GiB | 24.06 GiB (256k) |
| gemma-4-31B-it-heretic | 18.36 GiB | 19.35 GiB | 28.65 GiB (256k) |

All three fit the server CPU backend's 64 GiB limit at native maximum context even at Q6_K with f16 KV (worst case 44.64 GiB, Gemma 4 Q6_K f16 at 256k). None fit the desktop's 8 GiB GPU fully at any quant listed; that backend needs the partial-offload rule the map leaves unspecified.

## Ollama version pinned on `main`

`config/environments/kubernetes/homelab/ollama-values.yaml` pins `ollama/ollama@sha256:684d8674b4315fa18f4f0e973a118ec2652ed96f67563277839985175858e0ba`. Docker Hub resolves that index digest to tag `0.34.0` (pushed 2026-09-09); the GitHub release `v0.34.0` was published 2026-09-05. Sources: [Docker Hub tag](https://hub.docker.com/v2/repositories/ollama/ollama/tags/0.34.0), [release v0.34.0](https://github.com/ollama/ollama/releases/tag/v0.34.0).

At v0.34.0 Ollama no longer has its own Go inference engine for GGUF: `llm/server.go` states "All GGML models are served via the upstream llama-server subprocess", and `LLAMA_CPP_VERSION` pins llama.cpp tag `b10760` (released 2026-09-02), fetched at build time by `llama/server/CMakeLists.txt`. Architecture support is therefore llama.cpp b10760's. Sources: [llm/server.go](https://github.com/ollama/ollama/blob/v0.34.0/llm/server.go), [LLAMA_CPP_VERSION](https://github.com/ollama/ollama/blob/v0.34.0/LLAMA_CPP_VERSION), [llama/README.md](https://github.com/ollama/ollama/blob/v0.34.0/llama/README.md), [llama.cpp b10760](https://github.com/ggml-org/llama.cpp/releases/tag/b10760).

llama.cpp b10760 registers `gemma3`, `gemma4` and `qwen35` in `src/llama-arch.cpp`, with model loaders at `src/models/gemma3.cpp`, `src/models/gemma4.cpp` and `src/models/qwen35.cpp`. Ollama's `fs/ggml/ggml.go` also lists all three in `FlashAttention()` and `qwen35` in `SupportsFlashAttention()`. Ollama's `llama/compat` layer only rewrites Ollama-published GGUFs whose layout predates llama-server; Hugging Face GGUFs converted by llama.cpp are loaded directly. Sources: [llama-arch.cpp](https://github.com/ggml-org/llama.cpp/blob/b10760/src/llama-arch.cpp), [fs/ggml/ggml.go](https://github.com/ollama/ollama/blob/v0.34.0/fs/ggml/ggml.go), [compat README](https://github.com/ollama/ollama/blob/v0.34.0/llama/compat/README.md).

Runtime facts that shape the fit rule (all from [llm/llama_server.go](https://github.com/ollama/ollama/blob/v0.34.0/llm/llama_server.go) unless noted):

- Ollama passes `-c num_ctx * OLLAMA_NUM_PARALLEL` and `-np`; the chart sets `OLLAMA_NUM_PARALLEL=1` and `OLLAMA_CONTEXT_LENGTH=4096` ([chart](../../charts/homelab-ollama/templates/resources.yaml)). A request's `num_ctx` above the GGUF `context_length` is clamped to it ([llm/server.go](https://github.com/ollama/ollama/blob/v0.34.0/llm/server.go)).
- `OLLAMA_KV_CACHE_TYPE` is global, accepts `f16` (default), `q8_0`, `q4_0`, and is passed as both `--cache-type-k` and `--cache-type-v`. The chart does not set it today, so the current deployment runs f16. Sources: [faq.mdx](https://github.com/ollama/ollama/blob/v0.34.0/docs/faq.mdx), [envconfig/config.go](https://github.com/ollama/ollama/blob/v0.34.0/envconfig/config.go).
- A quantized V cache requires flash attention. Ollama passes `--flash-attn auto` when `OLLAMA_FLASH_ATTENTION` is unset and the device supports it (`Library == "cpu"` counts), and llama.cpp turns `auto` into enabled when V is quantized. Sources: [ml/device.go](https://github.com/ollama/ollama/blob/v0.34.0/ml/device.go), [llama-context.cpp](https://github.com/ggml-org/llama.cpp/blob/b10760/src/llama-context.cpp).
- `-b` and `-ub` are both set to `num_batch`, default 512 ([api/types.go](https://github.com/ollama/ollama/blob/v0.34.0/api/types.go)). `n_ubatch` sizes the sliding-window cache below.

## Formulas

Bytes per element: f16 = 2; q8_0 = 34/32 = 1.0625 (`block_q8_0` is one `ggml_half` scale plus 32 `int8`, `QK8_0 = 32`). Source: [ggml-common.h](https://github.com/ggml-org/llama.cpp/blob/b10760/ggml/src/ggml-common.h).

Per attention layer per token, K and V are both stored: `2 x n_head_kv(il) x head_dim(il) x bytes_per_element`. Head count and head dimension are per layer in llama.cpp (`n_embd_k_gqa(il) = n_embd_head_k(il) x n_head_kv(il)`, with `_swa` variants for sliding layers). V is allocated for every non-MLA layer even when the graph reuses K as V. Sources: [llama-hparams.cpp](https://github.com/ggml-org/llama.cpp/blob/b10760/src/llama-hparams.cpp), [llama-kv-cache.cpp](https://github.com/ggml-org/llama.cpp/blob/b10760/src/llama-kv-cache.cpp).

Sliding-window layers do not scale with context. llama.cpp splits the cache into a full cache of `n_ctx` cells for global layers and an SWA cache of `GGML_PAD(min(n_ctx, n_swa x n_seq_max + n_ubatch), 256)` cells (unless `--swa-full`, which Ollama does not pass). With `n_swa = 1024`, `n_seq_max = 1`, `n_ubatch = 512` that is 1,536 cells for any `num_ctx >= 1536`. Source: [llama-kv-cache-iswa.cpp](https://github.com/ggml-org/llama.cpp/blob/b10760/src/llama-kv-cache-iswa.cpp), [common.h](https://github.com/ggml-org/llama.cpp/blob/b10760/common/common.h).

Recurrent (linear-attention) layers keep a fixed f32 state per sequence instead of a KV cache: `n_embd_r = (d_conv - 1) x (d_inner + 2 x n_group x d_state)` and `n_embd_s = d_state x d_inner` elements per layer, `x (1 + n_rs_seq)` rows where `n_rs_seq` defaults to 0. Sources: [llama-hparams.cpp](https://github.com/ggml-org/llama.cpp/blob/b10760/src/llama-hparams.cpp), [llama-memory-recurrent.cpp](https://github.com/ggml-org/llama.cpp/blob/b10760/src/llama-memory-recurrent.cpp), [llama-model.cpp](https://github.com/ggml-org/llama.cpp/blob/b10760/src/llama-model.cpp) (`recurrent_type_k/v = GGML_TYPE_F32`), [llama.h](https://github.com/ggml-org/llama.cpp/blob/b10760/include/llama.h).

Total per load: `weights + global_bytes_per_token x num_ctx + fixed_cache`.

## Fallen-Gemma3-27B-v1 (`gemma3`)

GGUF header of `bartowski/TheDrummer_Fallen-Gemma3-27B-v1-GGUF` Q4_K_M: `block_count 62`, `embedding_length 5376`, `head_count 32`, `head_count_kv 16`, `key_length = value_length = 128`, `sliding_window 1024`, `context_length 131072`, `rope.scaling linear x8`. The `config.json` in the source safetensors repo is incomplete (it carries 12B-shaped `text_config` values), so the GGUF header is the reference here. Source: [GGUF header](https://huggingface.co/bartowski/TheDrummer_Fallen-Gemma3-27B-v1-GGUF/resolve/main/TheDrummer_Fallen-Gemma3-27B-v1-Q4_K_M.gguf) (first bytes), [source config.json](https://huggingface.co/TheDrummer/Fallen-Gemma3-27B-v1/raw/main/config.json).

Layer split: llama.cpp's gemma3 loader uses `set_swa_pattern(6)` unless the GGUF overrides it, so layers with `il % 6 == 5` are global: 10 global, 52 sliding. Source: [models/gemma3.cpp](https://github.com/ggml-org/llama.cpp/blob/b10760/src/models/gemma3.cpp), [set_swa_pattern](https://github.com/ggml-org/llama.cpp/blob/b10760/src/llama-hparams.cpp).

Per token per layer: `2 x 16 x 128 = 4096` elements = 8,192 B f16 / 4,352 B q8_0. Global (10 layers): **81,920 B/token f16, 43,520 B/token q8_0**. SWA fixed cache: `52 x 1536 x 8192 = 624 MiB` f16, 332 MiB q8_0.

Quant files (bytes from the Hugging Face API, `?blobs=true`):

| Quant | bartowski (imatrix) | mradermacher i1 (imatrix) | mradermacher static |
|---|---|---|---|
| IQ4_XS | 14,767,447,744 (13.75 GiB) | 14,767,448,160 (13.75 GiB) | 14,893,891,424 (13.87 GiB) |
| Q4_K_M | 16,546,688,704 (15.41 GiB) | 16,546,689,120 (15.41 GiB) | 16,546,688,864 (15.41 GiB) |
| Q5_K_M | 19,271,675,584 (17.95 GiB) | 19,271,676,000 (17.95 GiB) | 19,271,675,744 (17.95 GiB) |
| Q6_K | 22,166,974,144 (20.64 GiB) | 22,166,974,560 (20.64 GiB) | 22,166,974,304 (20.64 GiB) |

Sources: [bartowski](https://huggingface.co/bartowski/TheDrummer_Fallen-Gemma3-27B-v1-GGUF), [mradermacher i1](https://huggingface.co/mradermacher/Fallen-Gemma3-27B-v1-i1-GGUF), [mradermacher static](https://huggingface.co/mradermacher/Fallen-Gemma3-27B-v1-GGUF). No repo ships an `mmproj`, so these load text-only.

Weights plus KV (bartowski sizes), GiB:

| ctx | KV f16 | KV q8_0 | IQ4_XS f16 / q8_0 | Q4_K_M f16 / q8_0 | Q5_K_M f16 / q8_0 | Q6_K f16 / q8_0 |
|---|---|---|---|---|---|---|
| 8,192 | 1.23 | 0.66 | 14.99 / 14.41 | 16.64 / 16.07 | 19.18 / 18.60 | 21.88 / 21.30 |
| 32,768 | 3.11 | 1.65 | 16.86 / 15.41 | 18.52 / 17.06 | 21.06 / 19.60 | 23.75 / 22.30 |
| 131,072 | 10.61 | 5.64 | 24.36 / 19.39 | 26.02 / 21.05 | 28.56 / 23.58 | 31.25 / 26.28 |

## Qwen3.8-27B-Heretic-JP-Roleplay-NSFW-DanbooruTags (`qwen35`)

GGUF header of `mradermacher/...-i1-GGUF` Q4_K_M: `block_count 64`, `embedding_length 5120`, `head_count 24`, `head_count_kv 4`, `key_length = value_length = 256`, `context_length 262144`, `full_attention_interval 4`, `attention.recurrent_layers` array (48 true, 16 false), `ssm.conv_kernel 4`, `ssm.inner_size 6144`, `ssm.group_count 16`, `ssm.state_size 128`, `ssm.time_step_rank 48`. The source repo's `config.json` is `Qwen3_5ForConditionalGeneration` with `layer_types` three `linear_attention` per `full_attention`, `head_dim 256`, `hidden_size 5120`. The "3.8" in the name is the uploader's naming; the GGUF architecture is `qwen35`. Sources: [GGUF header](https://huggingface.co/mradermacher/Qwen3.8-27B-Heretic-JP-Roleplay-NSFW-DanbooruTags-i1-GGUF/resolve/main/Qwen3.8-27B-Heretic-JP-Roleplay-NSFW-DanbooruTags.i1-Q4_K_M.gguf), [source config.json](https://huggingface.co/sss22213/Qwen3.8-27B-Heretic-JP-Roleplay-NSFW-DanbooruTags/raw/main/config.json).

No sliding-window layers. 16 full-attention layers cache KV: `2 x 4 x 256 = 2048` elements = 4,096 B f16 / 2,176 B q8_0 per layer, so **65,536 B/token f16, 34,816 B/token q8_0**. 48 recurrent layers hold `n_embd_r = 3 x (6144 + 2 x 16 x 128) = 30,720` and `n_embd_s = 128 x 6144 = 786,432` f32 elements each: `48 x 817,152 x 4 B = 149.6 MiB` fixed, independent of context and of `OLLAMA_KV_CACHE_TYPE`. Source: [models/qwen35.cpp](https://github.com/ggml-org/llama.cpp/blob/b10760/src/models/qwen35.cpp) plus the formulas above.

Quant files:

| Quant | mradermacher i1 (imatrix) | mradermacher static |
|---|---|---|
| IQ4_XS | 15,082,508,928 (14.05 GiB) | 15,193,919,776 (14.15 GiB) |
| Q4_K_M | 16,547,402,368 (15.41 GiB) | 16,547,402,016 (15.41 GiB) |
| Q5_K_M | 19,231,101,568 (17.91 GiB) | 19,231,101,216 (17.91 GiB) |
| Q6_K | 22,082,531,968 (20.57 GiB) | 22,082,531,616 (20.57 GiB) |

Sources: [i1 repo](https://huggingface.co/mradermacher/Qwen3.8-27B-Heretic-JP-Roleplay-NSFW-DanbooruTags-i1-GGUF) (updated 2026-09-21), [static repo](https://huggingface.co/mradermacher/Qwen3.8-27B-Heretic-JP-Roleplay-NSFW-DanbooruTags-GGUF). No `mmproj`.

Weights plus KV plus recurrent state (i1 sizes), GiB:

| ctx | KV+state f16 | KV+state q8_0 | IQ4_XS f16 / q8_0 | Q4_K_M f16 / q8_0 | Q5_K_M f16 / q8_0 | Q6_K f16 / q8_0 |
|---|---|---|---|---|---|---|
| 8,192 | 0.65 | 0.41 | 14.69 / 14.46 | 16.06 / 15.82 | 18.56 / 18.32 | 21.21 / 20.98 |
| 32,768 | 2.15 | 1.21 | 16.19 / 15.26 | 17.56 / 16.62 | 20.06 / 19.12 | 22.71 / 21.77 |
| 262,144 | 16.15 | 8.65 | 30.19 / 22.69 | 31.56 / 24.06 | 34.06 / 26.56 | 36.71 / 29.21 |

## gemma-4-31B-it-heretic (`gemma4`)

`coder3101/gemma-4-31B-it-heretic` is safetensors only (`Gemma4ForConditionalGeneration`, `dtype bfloat16`, `max_position_embeddings 262144`, 60 layers: 50 `sliding_attention`, 10 `full_attention`, `num_key_value_heads 16`, `num_global_key_value_heads 4`, `head_dim 256`, `global_head_dim 512`, `attention_k_eq_v true`, `sliding_window 1024`); it matches `google/gemma-4-31B-it` dimension for dimension. Published GGUF quants exist: `mradermacher/gemma-4-31B-it-heretic-GGUF` (static) and `mradermacher/gemma-4-31B-it-heretic-i1-GGUF` (imatrix), both declaring `base_model: coder3101/gemma-4-31B-it-heretic` and `general.source.url` pointing at it. A Hugging Face search also shows other uploaders' GGUFs of differently named heretic variants; those are different source repos and are not recorded here. Sources: [source config.json](https://huggingface.co/coder3101/gemma-4-31B-it-heretic/raw/main/config.json), [static GGUF](https://huggingface.co/mradermacher/gemma-4-31B-it-heretic-GGUF), [i1 GGUF](https://huggingface.co/mradermacher/gemma-4-31B-it-heretic-i1-GGUF).

GGUF header of the i1 Q4_K_M: `block_count 60`, `context_length 262144`, `head_count 32`, `head_count_kv` per-layer array (16 on sliding layers, 4 on global), `key_length = value_length = 512` (global), `key_length_swa = value_length_swa = 256`, `sliding_window 1024`, `sliding_window_pattern` array (50 true, 10 false; global at `il % 6 == 5`), `shared_kv_layers 0`. Source: [GGUF header](https://huggingface.co/mradermacher/gemma-4-31B-it-heretic-i1-GGUF/resolve/main/gemma-4-31B-it-heretic.i1-Q4_K_M.gguf).

Global layers (10): `2 x 4 x 512 = 4096` elements = 8,192 B f16 / 4,352 B q8_0 per layer, so **81,920 B/token f16, 43,520 B/token q8_0**. Note llama.cpp b10760 allocates and fills a V cache on these layers even though `attention_k_eq_v` makes `Vcur = Kcur` when no `v_proj` exists (`models/gemma4.cpp`, `llama-kv-cache.cpp`); a future upstream change could halve this figure. Sliding layers (50): `2 x 16 x 256 = 8192` elements = 16,384 B f16 / 8,704 B q8_0 per layer, times 1,536 cells: **1,200 MiB f16 / 638 MiB q8_0 fixed**.

Quant files:

| Quant | mradermacher i1 (imatrix) | mradermacher static |
|---|---|---|
| IQ4_XS | 16,735,790,016 (15.59 GiB) | 16,862,228,608 (15.70 GiB) |
| Q4_K_M | 18,687,062,976 (17.40 GiB) | 18,687,058,048 (17.40 GiB) |
| Q5_K_M | 21,845,570,496 (20.35 GiB) | 21,845,565,568 (20.35 GiB) |
| Q6_K | 25,201,484,736 (23.47 GiB) | 25,201,479,808 (23.47 GiB) |

No `mmproj` in either repo, so vision and audio inputs are unavailable from these files.

Weights plus KV (i1 sizes), GiB:

| ctx | KV f16 | KV q8_0 | IQ4_XS f16 / q8_0 | Q4_K_M f16 / q8_0 | Q5_K_M f16 / q8_0 | Q6_K f16 / q8_0 |
|---|---|---|---|---|---|---|
| 8,192 | 1.80 | 0.95 | 17.38 / 16.54 | 19.20 / 18.36 | 22.14 / 21.30 | 25.27 / 24.43 |
| 32,768 | 3.67 | 1.95 | 19.26 / 17.54 | 21.08 / 19.35 | 24.02 / 22.30 | 27.14 / 25.42 |
| 262,144 | 21.17 | 11.25 | 36.76 / 26.83 | 38.58 / 28.65 | 41.52 / 31.59 | 44.64 / 34.72 |

## Implications for the fit rule

- A single linear "weights + bytes_per_token x ctx" rule over-reserves for all three because the context-scaling part is only 10 or 16 layers; a catalog entry needs `bytes_per_token` (global layers) and `fixed_cache` separately, both derivable from the GGUF header with the formulas above.
- `OLLAMA_KV_CACHE_TYPE=q8_0` is a server-wide setting in 0.34.0, not per chat, and the chart does not set it yet; enabling it roughly halves the context-scaling part and the SWA cache but not Qwen's recurrent state.
- Ollama clamps `num_ctx` to the GGUF `context_length`, so the "native maximum" column is the real ceiling per model without RoPE overrides.
- Reproduce the numbers with a GGUF header read and the formulas in this note; the scripts used are throwaway and were not committed.
