# Power recovery acceptance - PR 275

Status: live acceptance complete. Final-commit CI and merge reconciliation are
recorded in the delivery receipt on PR 275 after this document is committed.

## Incident

The 2026-09-29 06:30 UTC scheduled database backup created demand; the primary
power-on request followed at 06:30:22 UTC. Proxmox autostart started VM 102 at
06:34:30 UTC. The coordinator attempted the same VM start at 06:34:38 UTC and
received `VM 102 already running`. The generic management error left the host
blocked. AI was Off with zero active work. The backup reached its deadline.

## Local verification and review

- Source `2b6fca5404693ddd85f00af7c5b28064c793fd2c`: 124 controller tests passed.
- Fault injection covers duplicate starts, late demand, conflicting patches,
  interruption after an accepted scale-up, journal reconstruction, restoration
  of replicas/schedules, storage and operator ownership rejection, inventory
  outages, wake timeouts and bounded recovery.
- Independent Standards and Spec reviews found and resolved cancellation-intent,
  preflight-observation, deadline, wake-error classification, and test-coverage
  gaps. No deployment-blocking findings remained in the predeployment review.
- Local pre-push OpenTofu formatting, Trivy, Checkov (862 passed, 187 skipped),
  Gitleaks and TFLint passed. GitHub checks remain separate requirements.

## Deployment and recovery

The existing coordinator installation on the management laptop and forced-command
helpers on both Proxmox hosts were updated from reviewed source `2b6fca5`.
No credentials, VM definitions or storage bindings were changed. The private
release directory is `~/.local/share/homelab-capacity/releases/pr275-2b6fca5/` on
the laptop. It retains source/journal rollback copies, a source-hash receipt and
periodic redacted acceptance observations. Each host retains its previous helper
as `/usr/local/lib/homelab-power/helper.before-pr275.py`.

Before recovery, every protected binding and the mounted primary data-volume
identity matched the retained platform snapshot; VM 102 had the registered UUID
and was running. Recovery used the normal `powerctl resume primary` command.
Named `power-recovery-275` holds protected both hosts during initial validation
and were released before idle acceptance. The coordinator is active. Both hosts reached admission-ready. The primary's
20 registered platform components restored, and its snapshot reached `complete`.
A coordinator restart at 2026-09-30 01:00:42 UTC while the primary was restoring
retained the same platform operation ID and subsequently completed restoration.
The record is `restart-test.json` in the private release directory.

Job `homelab-data/apps-db-backup-power-recovery-275` completed successfully with
one succeeded Pod and no failures. Its verified backup receipt records version
`fGDgTE4_yXzbZ_O.BaJFpKq6Z48JeINg`, SHA-256
`5980bda8f0d48944116ff65a20e3a6be12db4aee3e9ec07e8b41ddc842f2d4df`.
The existing backup implementation verifies the uploaded version before success.
This is backup evidence, not a new restore rehearsal.

All 19 active coordinator Python files and both deployed helpers matched the
reviewed source hashes. Old backup directories under `src` are retained but are
not imported as the active package. Both acceptance holds were released. A
read-only observer is recording the automatic idle cycle while CI consumes the
restored hosts; no active work is cancelled to force retirement.

The secondary subsequently completed automatic retirement through quiesce,
worker stop and graceful host shutdown, with physical power observed off at
2026-09-30 01:16:02 UTC. During primary drain, the cache CI job introduced a
durable capacity hold. At 01:15:49 UTC the coordinator cancelled retirement,
cleared `shutdown_requested`, and restored the primary to ready by 01:18:17 UTC.
This independently exercises the live late-demand cancellation path. A normal
`powerctl wake secondary` request then completed the secondary cold-wake test:
the worker became Ready and the coordinator reached ready by 01:26:02 UTC,
without a blocked state. Both registered Talos workers were independently
observed Ready through the Kubernetes API.

All relevant checks on `2b6fca5` passed, including `plan-gate`, `apply-gate`,
controller configuration validation, inference verification, secret scanning,
and the admission contracts plus management/cache plans (run `36652777734`).
Final documentation updates will receive checks again before merge.

The primary also completed automatic retirement: ordered quiesce, graceful
worker stop at 01:36:07 UTC, graceful host shutdown and observed physical off by
01:37:32 UTC. This completes the independent automatic-off checks for both hosts.
The recorded idle intervals exceeded 300 seconds before draining; a sample gap
resets idle accounting instead of treating unobserved time as verified idle.
The subsequent normal primary cold wake reached platform phase `complete`
with all 20 registered components restored. At 01:47:03 UTC it reached ready;
a fresh observation confirmed admission-ready. Both wake and shutdown intents
were cleared. There were no unexplained blocked states or acceptance holds.

## Completion checklist

- [x] Both helpers and coordinator match reviewed code `2b6fca5`; final changes are documentation only.
- [x] Primary and secondary restore and become admission-ready.
- [x] Successful database backup verified by terminal Job and backup receipt.
- [x] Controller restart during a transition converges safely.
- [x] Five-minute continuous idle produces graceful physical shutdown on both hosts.
- [x] Cold wake restores applications and both hosts operate correctly.
- [x] Acceptance holds released; no unexplained blocked state.
- [x] Reviewed-code gates and relevant checks pass; review findings resolved.

Final-commit checks, merge SHA and comparison of the deployed hash receipt to
merged source are recorded in the PR delivery receipt. They cannot be asserted
by a document committed before its own merge.
