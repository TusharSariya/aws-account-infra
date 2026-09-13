## 1. Specification and packaging
- [x] 1.1 Capture approved service contract and deferred Pi-hole tests; pass strict OpenSpec validation.
- [x] 1.2 Add pinned source/image build and private GHCR publishing; verify checksum, linux/amd64 build and image digest.
## 2. Deployment implementation
- [x] 2.1 Add retained-volume Helm deployments and private ingress; pass rendered resource/credential/isolation tests.
- [x] 2.2 Integrate guarded OpenTofu CI and protected inputs; verify plan rejection of missing credentials, unpinned images and destructive changes.
- [x] 2.3 Provide credential setup, model inventory/download/API instructions and consistent encrypted backup/isolated restore runbook; verify command syntax and failure handling.
## 3. Rollout and acceptance
- [ ] 3.1 Review PR and deploy through CI; verify immutable private image pull and all workloads healthy.
- [ ] 3.2 Verify actual-worker small-model CPU inference and private authenticated HTTPS/API access.
- [ ] 3.3 Download and benchmark Qwen3.8 27B and Gemma4 31B sequentially; record memory, speed and model switching.
- [ ] 3.4 Verify UI model management, streaming chat, search and document memory retrieval.
- [ ] 3.5 Replace application pods and verify retained data; restore encrypted workspace backup into isolated deployment and record evidence.

## Implementation evidence

- OpenSpec strict validation passed. Pi-hole client tests remain explicitly deferred.
- 14 application contract tests, 13 deployment-unit tests and a backup capture-failure recovery test pass locally.
- OpenTofu backend-free validation, shell syntax/ShellCheck and actionlint passed.
- PR #65 is draft. First image build failed in optional upstream CUDA wheel dependencies; the CPU build omits that unsupported feature.
- No service apply, model download, browser acceptance or live recovery has been performed for this change.

- CPU image build [34789472431](https://github.com/TusharSariyaOrg/aws-account-infra/actions/runs/34789472431) passed; private package digest `sha256:fd18b7fa8cb32c0c55971c31b367d141462312c0853f74b7f40b6c97572860bf` is pinned.
