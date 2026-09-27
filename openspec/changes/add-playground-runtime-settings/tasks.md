## 1. Runtime settings and admission

- [x] 1.1 Set KV cache type and flash attention explicitly in `homelab-ai` and `homelab-ollama`.
- [x] 1.2 Switch `homelab-compute` to `StrictFIFO`; the standalone-queue contract test still passes.
- [x] 1.3 Record why a cohort or hold was rejected (design.md).
- [x] 1.4 Gateway: per-entry `message`; `wake-playground` entry; test for the configured cold page.
- [x] 1.7 Set the strategy in `homelab-ci/pool-values.yaml` (the root reads it, not the chart default) and register `wake-playground` plus the playground services as operational Pods in the compute admission policy.
- [x] 1.5 Deploy through `live/kubernetes/homelab` (`apply` label) and the management dispatch (queue, lifecycle, always-on); verify the rendered queues and that CI admission resumes after a runtime start.
- [ ] 1.6 Record measured runner RSS at 8192 context with q8_0 KV on the map.
