## Context

Open WebUI is adopted (#243, #248). The control-plane guest is full, so the UI runs on the primary worker (#249) and the phone's first request wakes the host through `wake-playground` (change 1), whose page names the wait and refreshes itself.

## Decisions

- **Auth to the router** uses Open WebUI's `OLLAMA_API_CONFIGS` (`{"0": {"key": <router bearer>}}`), composed into the `playground-ui` Secret by the apps bootstrap so the token never appears in values.
- **Sign-up stays on for the first start** so the owner's first account becomes admin; it is switched off from the admin panel afterwards (documented in the spec's handoff).
- **Timeouts**: `AIOHTTP_CLIENT_TIMEOUT=1800` because a cold load or switch is silent for 60 to 80 s and the router's progress chunks keep the stream alive well inside that.
- **Backup**: both claims join the existing three-volume capture; the archive's volume list gains `playground-ui` and `playground-router`, the snapshot fixture mounts them read-only, and the isolated restore proof covers them. Their size is small (SQLite and uploads), inside the reviewed restore bound.

## Risks

Open WebUI persists its configuration in its database after first start; env changes later need the admin panel. The `main` image tag floats; pinning a digest is a follow-up once a version is chosen.
