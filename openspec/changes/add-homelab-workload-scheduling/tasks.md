## 1. Storage foundation PR

- [x] 1.1 Complete shared-XFS proposal, design and requirements; strict OpenSpec validation passes before code changes.
- [x] 1.2 Reconcile previous deployment evidence using successful CI job results; preserve failed attempts and unchecked behavior/recovery tasks.
- [x] 1.3 Enable Talos project quota support without changing disk selectors, VM resources or backends; configuration/guard regression tests pass.
- [x] 1.4 Add restricted quota reconciliation with stable IDs, mount/identity/inheritance checks and hard limits and user-namespace prerequisites; isolated enforcement, neighbor-write and project-zero escape rejection tests pass.
- [x] 1.5 Add independent read-only physical thin-pool collector and idempotent host recipe; fixture tests cover missing pools and metadata and credential isolation.
- [x] 1.6 Implement 30-second guest/project collection and fail-closed capacity policy with 90-second freshness and five-minute recovery; boundary and invalid-telemetry tests pass.
- [x] 1.7 Package helpers/configuration/policies through Kubernetes-root Helm, track all inputs in deploy selection and required acceptance; render and selection/gate tests pass.
- [x] 1.8 Exercise disposable quota enforcement and simulated stale/missing/disabled/exhausted conditions through explicit CI; record successful run separately from local tests.
- [x] 1.9 Verify quota activation and persistence through explicit worker maintenance, retaining identities and Pi-hole DNS; attach live evidence.
- [x] 1.10 Run relevant formatting, OpenTofu validation, lint/security checks and strict OpenSpec validation, then deliver and review storage PR through guarded apply and required acceptance.

## 2. AI packaging PR

- [x] 2.1 Publish one approved four-container template with exact aggregate requests/limits, hostUsers=false and bounded ephemeral storage; rendered resource totals and security checks pass.
- [x] 2.2 Add retained static local PVs and claims with fixed worker affinity and project directories; rendering verifies claim binding, retention and isolation.
- [x] 2.3 Add one-time migration recording exact old PVC/PV UIDs and stopped writers, narrowly scoped plan allowances and replay rejection; adversarial migration tests pass.
- [x] 2.4 Disable old writers and default migrated AI to zero without disturbing Pi-hole; CI health verifies intentional-off without starting AI.
- [x] 2.5 Perform authorized reset only through explicit reviewed CI migration; prove unrelated data survives and runtime remains off.
- [x] 2.6 Verify data persists across stop/start and full Pod stays Pending with insufficient resources while Pi-hole answers UDP/TCP DNS; record explicit acceptance evidence.
- [x] 2.7 Run rendering, unit/integration, OpenTofu, lint/security and strict OpenSpec checks; deliver and review packaging PR after storage PR succeeds.

## 3. Lifecycle and scheduling PR

- [x] 3.1 Implement durable desired state/revision, optimistic concurrency and Lease leadership; race/recovery tests prove no stale command reversal.
- [x] 3.2 Implement authenticated Start, Stop, Force Stop and Status with admission closure, graceful drain and observed termination; pending-start cancellation and repeated/concurrent operation tests pass.
- [x] 3.3 Instrument pinned Odysseus streams, documents, agents, schedules and subprocesses including cancellation/error paths; each activity-source integration test passes.
- [x] 3.4 Implement authenticated Ollama admission gateway and prevent network and same-Pod bypass; direct inference/download and unauthorized/bypass tests pass.
- [x] 3.5 Implement verified 30-minute idle interval, unknown-source handling and recovery reset; fake-clock tests cover all interval boundaries and excluded probes/connections.
- [x] 3.6 Connect storage pressure to startup/work admission, alerting and graceful drain without force/delete; integration tests prove five-minute recovery leaves AI off.
- [x] 3.7 Install pinned checksum-verified Argo chart, private Tailscale HTTPS client-token authentication and namespace RBAC; render and unauthorized-access tests pass.
- [x] 3.8 Publish reviewed operation/job templates and suspended UTC smoke schedule with Forbid and shared per-job mutexes; test manual/API/scheduled execution, cancellation, overlap and independent concurrency.
- [x] 3.9 Extend manifest watch paths and required acceptance for all charts/code/images/config/tests; cancellations and unexpected skips demonstrably fail the gate.
- [ ] 3.10 Run local validation and explicit lifecycle/scheduling acceptance; deliver and review final PR after packaging PR succeeds, preserving all deployment safeguards.

## 4. Operational evidence

- [x] 4.1 Document pinned reconstruction and separate credential issuance/recovery, with no credentials in plans/state/logs; review documented commands and credential scopes.
- [ ] 4.2 Document application data backup/restore and run an isolated restore before claiming recovery; record exact artifact/run and verified data.
- [ ] 4.3 Record local checks, CI deployment, live behavior, benchmarks and recovery separately; unfinished scenarios remain unchecked and change stays unarchived.

## Local implementation record, 2026-09-14

Storage foundation code and isolated tests are present. Run 34810327867 successfully applied the guarded storage release, checked private application endpoints and completed explicitly requested worker maintenance. Talos subsequently reports project quotas enabled on the same worker mount. The capacity release remains disabled pending independent physical credentials and verified Pod-to-exporter routing. Actual application-Pod enforcement and configured-project persistence remain unchecked. No production reset, migration or intentional AI shutdown has run. See the implementation log for current-head acceptance and historical failures, and `docs/homelab-capacity.md` for credential prerequisites and the observed project-ID bypass requiring user-namespaced consumers.

## Deployment and live maintenance update, 2026-09-14

Packaging PR #68 merged as f4708346f3e3e170226cced36a1240eee341bcb0 after guarded apply 34819433687 and all required PVC/network/capacity acceptance succeeded. Both collectors are Ready and every legacy AI Deployment remains zero. Quota run 34820173760 passed pre-reboot application enforcement and completed worker maintenance, then failed downloading verified tools before post-reboot verification. Verification-only resume 34820541091 succeeded with the same durable fixture identity and observed changed boot. Reset 34820827996 completed exactly the three-volume migration and retained its immutable receipt. Independent unrelated-data verification and AI stop/start behavior remain unfinished, so task 2.5 and 2.6 remain unchecked. The earlier local implementation paragraph is historical, not the current live state.

Independent read-only verification after reset found the original Pi-hole PVC UID `7738ef98-4f83-4e86-89ac-119b6676ad62` (created 2026-09-13T22:02:46Z) and 26,714 persistent query rows. The oldest timestamp, 1789337206.3400781, predates the reset completion timestamp 1789373078.6698902. This verifies surviving unrelated data without claiming a pre/post byte-for-byte comparison. Task 2.5 is complete; stop/start and isolated restore remain unchecked.
