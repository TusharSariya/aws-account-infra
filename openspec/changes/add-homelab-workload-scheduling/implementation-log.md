# Implementation evidence

## Local checks, 2026-09-14

- Planning artifacts and both affected active specifications pass strict OpenSpec validation.
- 94 local unit/contract tests pass across `scripts/tests`; Helm renders are included.
- Talos and Kubernetes OpenTofu roots initialized backend-free with read-only lockfiles and passed validation. Backend keys and pinned provider versions were not changed.
- ShellCheck and actionlint pass for the changed scripts/workflows.
- Trivy HIGH/CRITICAL configuration scan passed. Checkov reports 663 passed, 0 failed and 87 existing skips. TFLint recursive scan passed.
- Gitleaks baseline history scan reports no leaks. Rescan staged/new content before publishing.
- Disposable Linux XFS testing passed quota write rejection with confirmed physical headroom, neighboring writes, overcommitted declarations, UUID retrieval, quota/project persistence across unmount/remount, rejection of missing mounts/wrong devices/disabled quotas, and project-zero escape rejection inside a user namespace.

## Findings

- The initially tested ordinary non-root file owner could change an owned file's project ID to zero without quota-administration capabilities. Consequently, migrated application consumers must use `hostUsers: false`; worker user-namespace prerequisites and an adversarial regression test were added. Linux-container testing is not live Talos/Kubernetes acceptance.
- `lvs --readonly` omits live device-mapper state. The sampler instead uses only the fixed `lvs` reporting command with explicit fields and never accepts command arguments from clients.
- An existing local Proxmox SSH identity can query physical capacity. A read-only sample observed `pve/data` at 1.71% data and 0.20% metadata. This is a point-in-time administrative query, not independent collector deployment evidence.
- The local kubeconfig points to an older, unresolved desktop endpoint. No attempt was made to replace it or bypass the protected Talos CI identity.

## Outstanding gates

The new capacity release is disabled pending trusted filesystem UUID enrollment, independent collector credential provisioning, endpoint routing verification and live quota maintenance acceptance. The root host installation recipe is repository managed but has not been run. No production apply, quota activation, worker reboot, reset, migration, model benchmark or restore is claimed for this change.

Storage review/CI rollout must precede AI packaging and lifecycle/Argo rollout. The task checklist remains authoritative and unfinished work is not archived.

## First CI attempt

[Run 34806235563](https://github.com/TusharSariyaOrg/aws-account-infra/actions/runs/34806235563) failed the isolated namespace test because the Ubuntu runner rejected unprivileged uid_map creation, before the quota-bypass assertion ran. The test now creates the user namespace as a host administrator, matching a container runtime, then tests the stronger namespace-root file owner. It also tests rejection of clearing directory project inheritance. No runner hardening is disabled.

Read-only Proxmox inspection verified VM 102 scsi1 maps to the existing 1200 GiB `vm-102-disk-2`, whose only partition is named `u-local-path-provisioner` at sector 2048 (512-byte sectors). A read-only filesystem probe at that offset returned XFS UUID `86f3ada1-17e4-4f74-9d73-a18c1774cc31`; that expected UUID and observed `pve/data` pool are now pinned. The helper must still independently match the mounted guest filesystem before creating directories. Collector transport credentials and live activation remain pending.

### Review follow-up

- Run 34806516380 passed isolated quota acceptance; plan run 34806516203 and repository checks passed. Live network/PVC acceptance failed again and the apply gate stayed closed. No deployment was attempted.
- Standards review found no documented standards violation. Specification review identified missing live enrollment/host CI acceptance (still unchecked), missing collector readiness, TLS handshake blocking and unsupported DNS endpoints.
- Added fresh-sample readiness after successful publication, rejected hostname URLs before opening credentials/network, and moved bounded TLS handshakes into request threads. A real TLS concurrency regression test passes alongside collector freshness checks.
- Added narrowly allowlisted acceptance check/line diagnostics across the existing private-output boundary to locate the live failures without emitting command output or credentials.

- Added reviewed-main-only protected host reconciliation using an independent SSH identity and certificate bundle, plus live capacity acceptance in the existing required acceptance workflow. No credentials have been enrolled and no host workflow has run.
- Third isolated CI run 34807002496 passes. Its PVC failure is at disposable namespace creation, before any PVC or application data write. Plan run 34807002134 failed downloading OpenTofu release metadata; this is distinct from validation and the live acceptance failures.

- Run 34807222816 passes isolated tests and correctly reports capacity activation disabled. PVC acceptance reports timeout creating its temporary Namespace. Added bounded read-only API and server dry-run probes to distinguish schema discovery from API/admission failures; the original check still fails on its original failure.
- Added separate protected-main credential reconciliation for the physical client Secret with tests proving PR refs cannot invoke it and credential data is removed from child environments.

- Run 34807402562 reproduced namespace creation timeout while a bounded API read and server-side dry-run without schema discovery both succeeded. Updated only disposable core-v1 fixture submission to direct core API requests with `fieldValidation=Strict`, preserving server validation/admission and all behavioral assertions. A transport regression test guards against falling back to discovery or disabling strict validation. Original diagnostic probes were removed after isolating this failure.
- Local full suite passed 99 tests before this fixture fix; its two new regression tests also pass. An independent correctly mounted gitleaks scan checked 196 commits / 4.65 MB with no leaks (the existing linked-worktree pre-push wrapper incorrectly scans zero commits).

- Plan run 34807646664 passed on retry. Live network/PVC and isolated quota acceptance passed in 34807646845 after the strict core-API fixture fix.
- Requested guarded apply and explicit worker maintenance through the existing labels. Run 34808147694 applied AWS/Proxmox prerequisites and Talos configuration, then failed in Kubernetes credential bootstrap before Helm. Worker maintenance did not run. A duplicate queued label-triggered run, 34808148037, was canceled before execution to avoid duplicate maintenance.
- Replaced bootstrap schema-discovery-dependent writes with narrowly allowlisted strict core API POST/PUT operations. Updates retain observed resourceVersion and existing metadata; credentials remain stdin-only and no last-applied annotation is introduced. Standards and specification reviews found no blocking issue, and all 16 application tests pass.

- Run 34808992975 passed the repaired credential bootstrap, then failed during the saved Helm apply. Worker maintenance remains unexecuted. Added fixed-category error reporting and an allowlisted release-status probe; raw provider output remains suppressed. This is not a successful application deployment.
- Applied the same strict, resource-version-protected transport to the separate physical client credential step; its three tests and specification review pass. The PR is temporarily held as draft while deployment failure is diagnosed.

- Run 34809708118 again passed Talos apply and credential bootstrap, but saved Helm apply reported schema-discovery/timeout with no capacity release record. Read-only local inspection using the fingerprint-verified original Talos bundle confirms the API is reachable and the chart's server dry run succeeds. The global local kubeconfig was not changed. Temporary fixed-output CI probes compare schema transport paths without printing API payloads or credentials.
- Read-only Talos mount status still reports `projectQuotaSupport: false` on the existing `/dev/sdb1` XFS mount. Added a regression-tested post-maintenance assertion for the exact mount and enabled project quotas. This does not claim kernel write enforcement or persistence was tested live; those remain separate outstanding checks.
- Run 34810327867 successfully applied the guarded saved Helm plan and passed private DNS/HTTPS checks. Its three read-only schema transport probes all passed, so the observations support intermittent API transport failure rather than a compression-specific defect. Removed temporary diagnostic probes and retained a bounded authenticated schema-readiness preflight; schema validation remains enabled and no mutation is retried automatically.
- The same run completed explicitly requested worker maintenance. A separate read-only Talos observation after reboot reports the unchanged `/dev/sdb1` XFS mount with `projectQuotaSupport: true`. Removed the one-shot maintenance label after completion to avoid rebooting on routine follow-up commits. Actual Pod quota-write enforcement, independent collector enrollment, and quota persistence with configured projects remain outstanding.
- Focused specification review of the readiness/maintenance follow-up found no issue; 18 application and eight Talos-stage tests pass. The independent gitleaks scan checked 202 commits / 4.72 MB with no leaks.
