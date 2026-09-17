# Cleanup and pinned downloads, 2026-09-16

The user completed sign-in and supplied the downloaded build-cache CSV. The three
CSV previews in this directory contain headers and zero selected components.
Supported UI configuration now binds the initial 16 repositories to dependency
14-day, pinned raw 30-day, and disposable Docker build 7-day unused policies.
Cleanup and subsequent blob compaction both completed with result OK. Readback
and execution timestamps are in `nexus-cleanup-20260916.json`. The observed next
cleanup is 01:00 UTC and compaction is 05:30 UTC (03:00 Newfoundland local time),
not 03:00 UTC. These empty previews/executions do not prove physical reclamation.
This resolves the earlier browser-panel blocker; no further user UI action is
needed for these settings.

## Additional origins and preserved failed attempt

The guarded plan in private `nexus-finish-20260916-01` selected only the cache
release and passed fresh capacity checks. Its configuration hook failed on PUT
of the existing npm repository with HTTP 400 and an uninformative null message.
An unchanged GET payload also failed on PUT. Adding observed storage defaults,
omitting cleanup, and supplying empty cleanup policies each failed; readback
confirmed the original cleanup binding remained intact. The server-side reason
is unresolved. This is not evidence that all repository updates work.

Reconciliation now skips repositories whose managed fields already match,
allowing server-populated defaults. Actual managed drift still requires PUT and
failures remain fatal. The guarded retry `nexus-finish-20260916-02` succeeded and
produced an empty post-apply plan. It added `raw-codeload` and `raw-awscli` for the
exact source archive and pinned AWS CLI origins. Both were assigned the existing
30-day policy through the supported UI and verified through readback.

Two local port-forward downloads each returned and checksum-verified 30,044,517
bytes of the pinned Ollama source archive through Nexus on the first attempt.
Elapsed times were 35.824 and 29.336 seconds. `nexus-origins-20260916.json` contains
the receipts. These are local smoke tests, not distinct fresh-runner measurements;
upstream payload bytes and authoritative cache-hit evidence remain unverified.

## Client changes and remaining work

The downloader limits cache attempts to two and upstream attempts to three,
writes atomically, retries incomplete/network responses, and fails immediately
on checksum mismatch. Talos setup uses it for the existing pinned AWS CLI ZIP
and exports the cache opt-in for source-context scripts. Hosted/Mac execution
without that opt-in uses upstream directly. Both source-context scripts retain
locked checksums and safe extraction and avoid loading the whole archive into
memory. The shared downloader is included in AI input hashes and workflow path
filters; prior AI receipts cannot validate these changed inputs.

Unit checks cover bounded attempts, interrupted bodies, integrity rejection,
upstream-only recovery, managed-setting comparison and image-receipt guards.
They do not substitute for runtime fault acceptance. Nexus UI reports the default
secret encryption key warning; blob readiness and quota status pass. Client
package-manager/BuildKit wiring, prerequisite images, complete job measurements,
quota/restart/contention acceptance, warning delivery, fresh AI receipts, routing
cutover and compute-budget restoration remain open. The expiry waiver remains
explicitly unverified. No routing switch or merge was performed.
