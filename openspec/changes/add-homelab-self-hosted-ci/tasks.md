## 1. Storage and VM foundation
- [x] 1.1 Record approved requirements and pass strict OpenSpec validation before implementation.
- [ ] 1.2 Add opt-in runner hardware and exact worker resize budgets; mocked OpenTofu tests and plan-guard adversarial tests pass.
- [ ] 1.3 Add idempotent network, identity and Ubuntu bootstrap recipes; validate syntax and unchanged Talos identities/backends.
- [ ] 1.4 Bootstrap through a guarded local saved plan and verify worker, DNS and nested KVM recovery; record live evidence.

## 2. Disposable runner management
- [ ] 2.1 Implement pinned image construction and private GitHub registration; verify checksums and credential isolation.
- [ ] 2.2 Implement serial guest lifecycle, pause/resume/status and fail-closed recovery; unit tests cover failure, cancellation and restart.
- [ ] 2.3 Enforce guest network isolation and bounded storage/logging; live isolation and cleanup tests pass.
- [ ] 2.4 Complete one self-hosted GitHub job with hosted allowance exhausted and record its runner identity.

## 3. Workflow migration
- [ ] 3.1 Route every job to the reviewed runner without altering gates; static workflow contract tests pass.
- [ ] 3.2 Preserve ARM image and Lambda artifacts using emulation; actual ARM packaging and import tests pass.
- [ ] 3.3 Exercise all job families, private deployment and intentional-off drift checks; required acceptance succeeds.
- [ ] 3.4 Deliver three reviewed PRs and document bootstrap, recovery and measured limitations; strict specs and local lint/security checks pass.
