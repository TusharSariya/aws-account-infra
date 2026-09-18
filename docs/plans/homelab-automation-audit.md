# Homelab automation responsibility audit

> Historical audit, 2026-09-13, against the revision named below. This is not a
> current caller inventory or an instruction to repeat completed refactors.
> PRs #61, #62 and #63 subsequently merged the deployment stages, acceptance
> separation and consolidated backup command. Remaining parity and caller
> cleanup are tracked in [#83](https://github.com/TusharSariyaOrg/aws-account-infra/issues/83).
> The original findings and sequence below are retained as dated evidence.

Task 8.1, 2026-09-13. Audited source: 0f5fd28 on the evidence branch, containing
implementation through PR #60. Two independent read-only reviews covered
(1) deployment/configuration and (2) backups/recovery; the parent review mapped
workflow triggers, merge gates and local callers. No implementation or live
infrastructure changed during this audit.

## Decision

Keep OpenTofu + Helm + GitHub Actions. Remove the broad custom deployment
orchestrator after moving its responsibilities to visible native steps and a few
focused helpers. Keep native CLI operations where they already work. Do not
introduce another deployment framework, translate everything into Bash/YAML,
or use a line-count target as proof of simplification.

The five main Talos/storage/backup Python files total 780 lines; this excludes
Proxmox helpers, the manual backup shell script, networking tests and bootstrap
utilities. Some of that code is justified safety and integration coverage.

## Responsibility and disposition inventory

| Current entry point | Responsibility | Target/disposition |
| --- | --- | --- |
| scripts/talos-ci.py, main | Private inputs, tool setup, plan/apply, output filtering, guards, reboot, integration tests | Retire this broad wrapper after callers migrate; named CI setup/plan/apply/readiness/acceptance steps plus focused helpers below |
| scripts/talos-ci.py, guard_plan | Reject unexpected resources, deletes, repeat bootstrap and unsafe settings | Keep a small structural plan guard; move static release/config constraints to native blocking validation where inputs are available |
| scripts/talos-ci.py, assert_public_state and private-input preparation | Identity fingerprint, private workspace, environment sanitation, ephemeral variables, secret-free state/logs | Keep one focused private-input/inspection helper; never move raw private outputs into job logs or artifacts |
| scripts/talos-ci.py, guard_storage_disks/check_storage_mount | Exact disk identity/capacity, unknown-content refusal, expected labeled-volume reuse and mount readiness | Keep a focused live preflight/readiness helper; disk selectors alone do not replace existing-content inspection |
| scripts/talos-ci.py, download_verified/prepare_local_path_chart | Downloads and checksum verification | Consolidate pinned versions/checksums and installation in visible setup steps; use one composite action only where setup repeats |
| scripts/homelab-talos-config.py | Original-secret init/generation, strict validation, private permissions, Talos CLI installation | Keep local recovery interface initially; remove duplicated installer code; evaluate provider-native generation separately before retiring generation |
| scripts/homelab-config-validate.py | Cross-layer VM/Talos checks, tofu console serialization, repeated strict validation and embedded self-tests | Consolidate public inputs/native validation; retain narrow cross-layer assertions until equivalent coverage exists; move self-tests into normal tests |
| scripts/homelab-cilium-validate.sh | Disposable network integration tests and readiness checks | Keep coverage as an independently callable targeted integration suite; extract lightweight routine readiness |
| scripts/homelab-storage-validate.py | PVC placement, recreation persistence, Retain/Delete, quotas, owned-fixture cleanup | Keep focused integration suite; run for affected changes and explicit dispatch, not hidden inside every apply |
| scripts/proxmox-ci-check.py | Authenticated trusted endpoint/token permission checks | Keep focused preflight; consolidate the overlapping local check while retaining distinct plan/apply scopes |
| scripts/proxmox-tofu.py | Local credential/environment setup and check/init/validate/plan wrapper | Replace generic command forwarding with documented native invocation or a small private setup adapter; preserve local preview-only behavior and inherited-environment filtering |
| scripts/proxmox-provider-bootstrap.py | Initial root-mediated scoped provider credential bootstrap | Keep explicit out-of-band bootstrap; moving initial authentication into its own provider would create a circular dependency |
| scripts/proxmox-ci-secrets.py and scripts/talos-ci-secrets.py | Validate private local inputs and upload through gh stdin | Keep small onboarding helpers; do not print, rotate or relocate credentials to simplify code |
| scripts/homelab-etcd-backup-ci.py | CI guard, identity, private setup, encryption, upload/readback, heartbeat, receipt | Consolidate with snapshot/manual etcd operations behind the focused backup interface below; workflow owns scheduling/authentication/setup |
| scripts/homelab-etcd-snapshot.py | Capture, metadata/integrity, reconstruction bundle, duplicate generation/install | Retain snapshot validation in backup command; generate inputs once and share output instead of generating twice |
| scripts/homelab-backup-manual.sh | Interactive bootstrap or etcd packaging, passphrase encryption, versioned verification and receipt | Preserve existing modes through compatibility entry point until equivalent capture/backup/verify operations and docs are validated |
| scripts/tests/homelab-backup-certificates.sh | Offline certificate-chain tests | Keep separate; this is the Roles Anywhere path, not daily GitHub OIDC backup orchestration |
| scripts/deploy-units.py and deploy-units.json | Root inventory, selection and ordering | Keep this existing small interface; update watch paths and test trigger behavior as callers move |

Host/network/bootstrap shell utilities such as homelab-network-wizard.sh,
homelab-network-validate.sh, homelab-tailscale-subnet.sh and proxmox-baseline-*.sh
remain outside the initial wrapper-removal scope. They are recovery prerequisites,
not redundant simply because deployment now uses OpenTofu. Their broader fresh-
machine reconciliation gaps remain existing tasks 2.7/2.11.

## Caller migration checklist

Paths below are active callers or operator instructions. Historical implementation
logs preserve the commands used at the time and must not be rewritten as if they
used the future interface.

| Caller | Current dependency | Required migration |
| --- | --- | --- |
| .github/workflows/tofu-plan.yml:120,177 | Proxmox permission check; talos-ci.py plan | Preserve trusted read identity and sanitized PR summary; expose native plan steps with private inputs |
| .github/workflows/tofu-apply.yml:65,86 | Apply permission check; talos-ci.py apply | Preserve apply-label authorization, target revision, root ordering, state locking and private saved-plan handling |
| .github/workflows/tofu-apply.yml:101,118 | apply-gate and auto-merge depend on apply | When acceptance becomes a separate job, include required acceptance in both success gate and auto-merge dependencies; handle intentionally skipped suites explicitly |
| .github/workflows/homelab-config-tests.yml | Python/shell syntax, imported guard tests, Proxmox/Talos/AWS validation | Update relocated imports and path filters; retain native tests and negative helper tests |
| .github/workflows/homelab-etcd-backup.yml:33-36 | homelab-etcd-backup-ci.py | Call the focused backup command after visible authenticated setup; preserve schedule/concurrency and success-only heartbeat |
| .github/workflows/homelab-recovery-tests.yml | Recovery-root mocked tests and certificate test | Keep separate; add backup failure/compatibility coverage in an appropriate focused job rather than claiming these tests cover snapshot logic |
| deploy-units.json:102,119-120 | Specific Proxmox/Talos helper watch paths | Register replacement helper/action paths; verify selection instead of assuming dependency ordering selects every dependency |
| scripts/talos-ci.py:31,211,307,310 | Imports/calls generator; runs both integration scripts | Move private-input dependency and suite calls together with removal of orchestrator |
| scripts/homelab-etcd-backup-ci.py:52,55 and scripts/homelab-etcd-snapshot.py:53,84 | Generator and snapshot helper | Shared private generation once per backup; no deletion of generator until all backup callers are migrated |
| scripts/homelab-backup-manual.sh:37 | Snapshot helper for --etcd | Preserve interactive passphrase mode and legacy receipts |
| scripts/homelab-config-validate.py:93 and scripts/tests/test_talos_ci.py:6 | Dynamic imports of generator/orchestrator | Replace imports at the new focused interface; retain behavior tests rather than obsolete implementation-shaped tests |
| scripts/tests/test_proxmox_access.py | Bootstrap/local preview/permission helpers | Preserve token-secrecy, scope and environment-override rejection tests |
| config/environments/proxmox/homelab/talos/README.md:13,25,86 | init-secrets, generate, config validation CLI | Keep new-cluster initialization distinct from existing-cluster recovery; document equivalent local commands before retirement |
| live/talos/homelab/README.md:19,49,75,129-142 | CI helper, secret upload, local plan and network acceptance | Update routine use and explicit test instructions; preserve private local preview |
| live/proxmox/homelab/ACCESS.md:24,89-92 and CI.md:69,78,113 | Initial credentials, local wrapper, secret upload | Update native preview/setup instructions without removing independent bootstrap access |
| docs/plans/homelab-recovery.md:74,136,167,176-204 | Manual bootstrap/etcd, snapshot-only, daily backup and restore | Document compatibility modes, exact-version receipts and independent keys |
| live/aws/staging/workloads/homelab-recovery/MANUAL-BACKUP.md:30-70 | Native age/AWS canary and bootstrap recovery instructions | Preserve the standalone harmless canary and align real-backup receipt/version guidance with the consolidated command |
| docs/plans/homelab-worker-storage.md:17,114 | CI orchestration, automatic first-provision reboot and storage acceptance | Describe explicit maintenance/acceptance operations and new test entry point |

A repository-wide search excluding historical logs found the above executable,
workflow, test-import and operator-document references. Existing OpenSpec design
text describing today's scripts must be reconciled during migration; historical
log entries remain evidence, not current entry points.

## Native replacement limits

OpenTofu 1.11 blocking variable validation and preconditions/postconditions can
replace static constraints. Warning-only check blocks cannot replace a deployment
gate. prevent_destroy is already present, but removing a resource declaration
also removes that configuration guard; retain parsed-plan rejection of unwanted
deletes and unexpected resources. Do not replace actual disk-content checks with
an assumption that the configured selector is sufficient.

Talos provider 0.11.0 documents ephemeral machine_configuration and
client_configuration with existing structured machine_secrets, while apply
already uses write-only fields here. Native generation is a candidate, not an
approved drop-in. The provider pins Talos SDK/machinery 1.13.0; current generation
uses talosctl 1.13.9. Compare rendered multi-document configuration, defaults,
identity and certificate behavior privately before adopting it. Preserve existing
state addresses/backend keys and secret fingerprint. Keep the CLI generator if
parity is not established; this does not block removal of command orchestration.

Sources: [OpenTofu 1.11 conditions](https://opentofu.org/docs/v1.11/language/expressions/custom-conditions/),
[lifecycle guard limits](https://opentofu.org/docs/v1.11/language/meta-arguments/lifecycle/),
[Talos ephemeral machine configuration](https://raw.githubusercontent.com/siderolabs/terraform-provider-talos/v0.11.0/docs/ephemeral-resources/machine_configuration.md),
[ephemeral client configuration](https://raw.githubusercontent.com/siderolabs/terraform-provider-talos/v0.11.0/docs/ephemeral-resources/client_configuration.md),
[write-only apply fields](https://raw.githubusercontent.com/siderolabs/terraform-provider-talos/v0.11.0/docs/resources/machine_configuration_apply.md),
[provider dependency versions](https://raw.githubusercontent.com/siderolabs/terraform-provider-talos/v0.11.0/go.mod).

## Focused backup interface and compatibility

Target operations, with final command spelling left to task 8.4:

- capture: produce a private validated etcd/reconstruction bundle; no upload or mutation.
- backup: capture/package/encrypt/upload/read back the exact version and emit a receipt.
- verify: select a receipt or explicit bucket/key/VersionId, download, locally decrypt
  and check integrity; never restore or apply to a cluster.

Use talosctl, etcdutl, age and aws s3api internally. Keep private workspace,
identity/integrity and receipt logic together; no new AWS SDK is needed merely to
replace existing CLI calls. GitHub owns OIDC/Tailscale/tool setup and schedule;
OpenTofu continues owning IAM/KMS/S3 retention and monitoring. A separately visible
heartbeat step is acceptable only after an explicit verified-backup result.

| Existing bundle | Archive layout | Encryption/recovery input |
| --- | --- | --- |
| Manual bootstrap | Home-relative paths | Original age passphrase |
| Manual --etcd | Members under ./ | Original age passphrase |
| Daily etcd | Members under homelab/ | Independently saved age private identity |

Preserve restore support for all three. Receipt schema must identify the bundle
format/encryption method and retain bucket/key/VersionId, ciphertext hash,
snapshot time/status and Git provenance. Add fields compatibly rather than
invalidating existing text/JSON receipts. Derive new metadata versions from the
reviewed inputs and verified binaries instead of repeating hard-coded versions.

Keep the daily etcd/latest.tar.gz.age key, non-null VersionId verification,
exact-version readback, success-only metric, independent missing-heartbeat alarm,
no-delete/no-bypass runner permissions and 30-day noncurrent retention with no
current expiration. Local decryption is not a full etcd restore rehearsal.

## Findings to resolve during implementation

- Tool downloads and identity validation are duplicated across scripts; daily
  backup generates machine configurations twice.
- Static version/topology values appear in configuration and validator code;
  backup metadata can drift from actual generator inputs.
- Exceptions suppress too much operational context. Expose a safe stage/error
  category while keeping raw private config, state and command diagnostics out
  of logs and uploaded artifacts.
- Cilium/PVC acceptance runs inside every Talos apply, and a blank-data-disk
  preflight triggers a hidden worker reboot. Separate these responsibilities
  while preserving first-provision acceptance and the no-reset failure behavior.
- Integration-script-only changes are not covered by the Talos deploy-unit watch
  list. deploy-units.py orders selected roots but does not compute a dependency
  closure. Design explicit affected-test selection and test the relevant paths.
- Current apply-gate/auto-merge depends on the combined apply job. Merely moving
  acceptance out would weaken the merge gate unless dependencies are updated.
- docs/plans/homelab-recovery.md:154-155 mentions routine/monthly for future
  scheduled etcd snapshots, contradicting the deployed fixed daily key documented
  later in the file. Correct this during the backup documentation migration.
- Existing mocked AWS identity/certificate tests do not exercise backup failure
  behavior. Add identity/checksum/missing-VersionId/readback/heartbeat tests.

## Concrete implementation sequence

1. Task 8.2: extract shared verified setup and private-input preparation, then
   expose plan/apply as named steps. Keep the current generator initially. Move
   supported static constraints to blocking native validation and retain small
   structural/live guards. Preserve local preview and sanitized output.
2. Task 8.3: add affected-change and explicit-dispatch integration jobs, retain
   lightweight readiness, and update apply/merge gates. Put reboot/recovery
   rehearsals behind explicit maintenance operations with separate evidence.
3. Task 8.4: consolidate backup capture/backup/verify, reuse generated inputs and
   tool pins, preserve all legacy formats/keys and update recovery instructions.
4. Task 8.5: prove an authenticated no-change plan, negative guard/secret tests,
   targeted network/PVC acceptance, two distinct backup versions and exact-version
   local decryption/integrity plus legacy-format verification. Update every caller
   above, remove compatibility wrappers and record the working rollback revision.

Only task 8.1 is complete from this audit. No proposed replacement has been
implemented or accepted, and no existing backup or infrastructure was modified.
