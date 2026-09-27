---
status: accepted
date: 2026-09-26
---

# The model playground router is a custom thin proxy that presents the Ollama API

The playground needs three interceptions in front of Ollama that no off-the-shelf gateway expresses in configuration: wake-on-tap with progress, the fit rule, and the choice of inference backend. LiteLLM would still need a Python pre-call plugin for all three, so we build a small Python proxy in the style of the existing homelab controllers, borrowing the batch inference gateway's profile schema, bearer pattern, health-probe shape and SQLite discipline. It presents the Ollama API rather than an OpenAI surface because Open WebUI drives model lists, pulls with progress and per-chat context through that API; an OpenAI surface would lose native pulls.

## Considered options

- LiteLLM with config only: covers a static fit table and Ollama passthrough, not the awake check or a structured waking response.
- LiteLLM with a plugin: the same logic inside a much larger dependency.
- Extending the batch inference gateway: ruled out on the map; it is a fixed-model batch runner with a 120 s deadline.

## Consequences

The wake status vocabulary lives in the router and is emitted as synthetic Ollama pull-status lines, so the UI shows one continuous progress bar. Replacing the router later means re-implementing the wake contract, which is why this is recorded.
