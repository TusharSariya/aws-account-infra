# Retained-host power recovery

## Problem and scope

On 2026-09-29 the scheduled database backup requested primary capacity at 04:00
Newfoundland time. Proxmox autostart started VM 102 at 04:04:30; the coordinator's
start at 04:04:38 failed with `VM 102 already running`. The helper hid the cause,
and the coordinator permanently blocked restoration and subsequent idle shutdown.
The backup exhausted its deadline. AI was Off and was not keeping the server awake.

Keep the existing retained VMs, storage, management host, journal and deployment
identities. Preserve the configured idle interval, active-work protections,
maintenance pause, storage identity checks, node ownership checks, and graceful
Talos/Proxmox shutdown. No forced power-off, deletion, journal erasure, or admission
bypass is a recovery mechanism.

## Recovery contract

| Event | Required behavior |
|---|---|
| Concurrent Proxmox autostart | After a failed start acknowledgement, accept only a fresh direct observation that the registered worker is running. Otherwise preserve the failure. |
| Demand or lost verification in final shutdown preflight | Do not issue shutdown; restore the platform and clear the obsolete shutdown request. |
| Kubernetes resource-version conflict | Obtain fresh objects and retry guarded reconciliation within the existing recovery deadline. Never extend the deadline on each retry. |
| Temporary management transport failure during observation/start | Reobserve before retrying; retain operation and exit/timeout category without raw private output. |
| Lost shutdown acknowledgement | Observe the VM/physical power postcondition; never blindly repeat shutdown. If it cannot be established within the deadline, block for inspection. |
| Restart during platform restore or quiesce | Preserve the platform journal and phase, reset idle accounting, establish a new process-local bounded recovery window, and reconcile with fresh identity/ownership checks. |
| Restart after shutdown acknowledgement | Preserve the wait-for-off intent and observe completion without another shutdown request. |
| Identity/storage mismatch, unrelated operator cordon, forbidden API operation | Remain blocked or unavailable; never reinterpret as a successful operation. |

A restart is not permission to clear an existing hard block. The legacy primary
block must be inspected against its observed running VM and unchanged protected
state, then recovered through the existing explicit `powerctl resume` operation.

## Validation and delivery requirements

- Regression tests cover the actual helper start path, final preflight cancellation,
  adapter error classification, bounded retries, restart recovery and no duplicate
  shutdown writes. Retain negative tests for identity and storage protections.
- Run the full controller suite and the repository-selected checks; review the PR
  against these requirements and address every actionable finding.
- Deploy matching reviewed helper and coordinator code through the supported local
  management installation path. Retain private backup/rollback material and source
  hashes; never rotate credentials merely to update code.
- Verify both physical hosts, cold wake, application restoration, a successful
  database backup, five-minute continuous idle followed by graceful shutdown, and
  controller restart recovery. Observe meaningful state transitions and retain
  redacted evidence. A unit test cannot substitute for live acceptance.
- Merge only after required gates pass. Verify deployment hashes against merged
  code, update the runbook and evidence, and leave no unexplained blocked state.

## Evidence status

Implementation and local fault-injection checks are in progress. Live recovery,
PR review, CI, deployment acceptance and merge have not yet been completed.
