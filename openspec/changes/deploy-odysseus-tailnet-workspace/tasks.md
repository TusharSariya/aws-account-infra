## 1. Specification and packaging
- [x] 1.1 Capture approved service contract and deferred Pi-hole tests; pass strict OpenSpec validation.
- [x] 1.2 Add pinned source/image build and private GHCR publishing; verify checksum, linux/amd64 build and image digest.
## 2. Deployment implementation
- [x] 2.1 Add retained-volume Helm deployments and private ingress; pass rendered resource/credential/isolation tests.
- [x] 2.2 Integrate guarded OpenTofu CI and protected inputs; verify plan rejection of missing credentials, unpinned images and destructive changes.
- [x] 2.3 Provide credential setup, model inventory/download/API instructions and consistent encrypted backup/isolated restore runbook; verify command syntax and failure handling.
## 3. Rollout and acceptance
- [x] 3.1 Review PR and deploy through CI; verify immutable private image pull and all workloads healthy.
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

- CPU image build [34789472431](https://github.com/TusharSariyaOrg/aws-account-infra/actions/runs/34789472431) passed; private package digest `sha256:fd18b7fa8cb32c0c55971c31b367d141462312c0853f74b7f40b6c97572860bf` was the initial successful build.

- Packaged startup/authentication passed in [34789879143](https://github.com/TusharSariyaOrg/aws-account-infra/actions/runs/34789879143); its digest `sha256:6feb3dd257b13d746a1e88e8e624b083d71f0cc1e2420a810c7ef65f6126862a` is now pinned.
- Application plan in [34789879109](https://github.com/TusharSariyaOrg/aws-account-infra/actions/runs/34789879109) creates only the two new releases; Pi-hole and operator are no-op. Actual worker model execution and restore are still outstanding.

- First rollout was blocked by an invalid GHCR token; replacement token and pinned image access verified. The 900-second command wrapper interrupted Helm before it could persist state. The command budget now exceeds release deadlines and has a regression test; live rollout remains incomplete pending retry.

## 4. CPU ceiling adjustment
- [x] 4.1 Configure Ollama at 36 vCPU on the existing 38-vCPU worker, preserving VM/workspace settings and the 64 GiB memory limit.
- [ ] 4.2 Review and apply the limit through CI, then verify the live container limit and service health. CI apply succeeded; independent live-limit observation remains outstanding. No VM resize or restart is part of this change.

### Evidence reconciliation, 2026-09-14

Earlier entries describe historical attempts and are retained above. PR #65 merged. [Run 34795800686](https://github.com/TusharSariyaOrg/aws-account-infra/actions/runs/34795800686), commit `1cca1518197a4a562601759b17e66ff732bcaa72`, completed application deployment, network acceptance, PVC acceptance and the apply gate successfully. Runs 34789879237, 34789960537 and 34790124066 failed; 34793826053 was cancelled. The earlier statement that no apply occurred is superseded by this evidence.

PR #66 merged. [Run 34798200114](https://github.com/TusharSariyaOrg/aws-account-infra/actions/runs/34798200114), commit `7ec0cdd699f670392931b0ecea7835855bcb7867`, passed apply and apply-gate after failed run 34798101882. It did not select network/PVC acceptance. This verifies CI rollout of the configured CPU ceiling, not independent live limit observation, model benchmarks, interaction, reboot persistence or isolated restore. Tasks for those behaviors remain unchecked.
