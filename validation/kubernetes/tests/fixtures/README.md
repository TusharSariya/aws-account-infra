# Replay inputs

- `live-smoke.json`: projected Kubernetes API observations from the suite's real
  laptop run `kv-9f3c4263da7dca7f` on 2026-09-21. Keeps object identities, server
  timestamps, conditions and placement; excludes full specs, addresses and events.
- `worker-recreation.json`: before/after observations from the existing pilot's
  [live lifecycle proof](https://github.com/TusharSariyaOrg/aws-account-infra/tree/cd48f53/prototypes/one-slot-autoscaler/lifecycle).
  Verifies both the Kubernetes UID and VM hardware identity assertion.
- `admission.json`: synthetic compact replay with capacity becoming usable near
  the 15-minute limit. Tests the two-minute admission clock independently of boot
  time. Tests also derive timeout, cancellation, missing-prerequisite, interrupted
  cleanup and identity-change cases; these are simulated failures, not live drills.
