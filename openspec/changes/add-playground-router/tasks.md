## 1. Router and chart

- [x] 1.1 `fit.py`: rule, presets, GGUF derivation, refusal line; tests against the research figures.
- [x] 1.2 `catalog.py`: SQLite with WAL, models, copies, pulls, override.
- [x] 1.3 `router.py`: Ollama API proxy with merge, pull, chat/generate interception, wake and load progress, delete, admin; tests with a cold fake backend prove refusal without any backend call, waking lines then the answer, pull registration, delete.
- [x] 1.4 Chart `homelab-playground` (router half live, UI half gated), root release after `homelab-ai`, values file, guard address, deploy-unit watch paths.
- [x] 1.5 Wizard `playground-setup-wizard.sh`; apps bootstrap reconciles the two secrets; gateway `clients` policy for `wake-ollama`.
- [x] 1.6 Deploy through the `apply` label; management dispatch for the gateway policy; verify `/healthz` and a merged `/api/tags` through the router from inside the cluster.
- [x] 1.7 Acceptance 5: synthetic oversized chat refused without starting the runtime (router unit test runs in the apps test workflow; live check after change 3 from the UI).

Verified 2026-09-27: dispatch 36311048340 for the gateway policy; `/healthz` and merged `/api/tags` from inside the cluster; oversized context refused in the apps test workflow (router unit test) without waking anything.
