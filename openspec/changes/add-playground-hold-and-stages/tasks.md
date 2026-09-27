## 1. Hold

- [x] 1.1 Gateway: `/_power/` page, `/_power/hold`, `/_power/release`, `/_power/status`; lease patch with `hold-until`; heartbeat expiry; tests.
- [x] 1.2 Chart `homelab-always-on`: Lease, Role, RoleBinding and env from a `hold` block in `gateways.json`; chart test.
- [x] 1.3 Lifecycle: read the lease, `held` in `reconcile`, `hold_until` in status, RBAC `get` on the lease; tests.
- [x] 1.4 Management dispatch and apply; on hardware: hold from the phone keeps host and runtime past 5 minutes idle, release then verified idle and power off. (Dispatch 36338155577; hold 18:09 UTC pulled the host from verified idle back to ready and kept the runtime up 8 min silent; release 18:21, runtime stopped 18:26, draining 18:27. First shutdown blocked on the quiesce order gap, fixed in #267; power off recorded below when observed.)

## 2. Wait stages

- [x] 2.1 Router: sub-stage lines from pod readiness, `/api/ps` and kubelet stats; catalog timings from the final chunk; RBAC `nodes/proxy`; tests.
- [x] 2.2 On hardware: a chat on a cold runtime shows `runtime starting`, `loading weights, N of M GiB`, `processing prompt`, then the answer; second chat shows the measured typical.
- [ ] 2.3 Backup workflow proof lists both playground claims (carried from change 3).
