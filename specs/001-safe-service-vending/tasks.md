# Tasks: Safe Service Vending

**Input**: Retrospective design artifacts in `specs/001-safe-service-vending/`
**Implementation baseline**: `20e1672`
**Status markers**: `[x]` complete, `[-]` partial, `[>]` deferred, `[!]` blocked

Checked tasks prove only their cited repository evidence. They do not imply that a live
operation ran. Partial and deferred tasks state both the remaining work and enabling gate.

## Phase 1: Catalog and immutable identity

- [x] T001 [US1] [FR-001,FR-002,SR-003] Normalize v1/v2 service manifests and validate schema, uniqueness, capacity, immutable identities, and lifecycle transitions. (evidence: `scripts/service-catalog.py`, `catalog/schema/service.schema.json`, `tests/catalog/test_service_catalog.py`, commit `20e1672`)
- [x] T002 [US1] [FR-001] Generate a deterministic merged v2 catalog and enforce checked-in output. (evidence: `catalog/catalog.json`, `.github/workflows/service-catalog.yml`, test `test_catalog_is_valid_and_deterministic`)
- [x] T003 [US1] [FR-014,SR-004] Keep external-provider gates explicit and false by default. (evidence: `catalog/external-provider-gates.json`, `tests/catalog/test_external_reconciler.py`)

## Phase 2: AWS account, governance, and repository foundations

- [x] T004 [US2] [FR-003] Split organization, accounts, access, bootstrap, security, repositories, template bootstrap, and external control into independently recoverable OpenTofu roots. (evidence: `live/aws/organization/`, `tests/catalog/test_external_iac.py`, commit `20e1672`)
- [x] T005 [US2] [FR-003,FR-014] Separate account-vending plan/apply roles and protect apply behind `platform-prod`. (evidence: `.github/workflows/account-vend.yml`, `live/aws/organization/organization/identity.tf`, `docs/account-vending.md`)
- [x] T006 [US2] [FR-004,FR-016] Preserve retired account identity and document interrupted-create import recovery without automated closure. (evidence: `scripts/service-catalog.py`, `docs/account-vending.md`, tests `test_account_key_cannot_be_deleted` and `test_provisioned_account_identity_is_immutable`)
- [x] T007 [US2] [FR-005,FR-013] Mint a short-lived GitHub App token locally and remove the PEM before OpenTofu executes. (evidence: `scripts/repository-tofu.py`, `tests/catalog/test_secret_materialization.py`, `docs/account-vending.md`)
- [x] T008 [US2] [FR-003,FR-015] Add vended-account baseline, governance, identity, artifact, and immutable module-distribution controls. (evidence: `modules/aws/`, `tests/catalog/test_supply_chain.py`, commit `20e1672`)

## Phase 3: Kubernetes tenant safety

- [x] T009 [US3] [FR-007] Render native and Argo tenant phases with namespace, quota, LimitRange, NetworkPolicy, metadata, RBAC, Pod Security, and admission controls. (evidence: `scripts/kubernetes-vending.py`, `ansible/roles/kubernetes_tenants/files/`, `tests/catalog/test_kubernetes_vending.py`)
- [x] T010 [US3] [FR-007,SR-001] Encode the Ansible, Helmfile, and Argo CD ownership allowlist with native controls independent of add-on availability. (evidence: `docs/kubernetes-vending.md`, `ansible/roles/cluster_addons/`, test `test_argocd_phase_is_namespaced_and_allowlisted`)
- [x] T011 [US3] [FR-008,FR-016] Pin Kubernetes 1.35.7 and document rebuild plus verified restore instead of in-place downgrade. (evidence: `ansible/roles/kubernetes_control_plane/defaults/main.yml`, `ansible/roles/kubernetes_node/defaults/main.yml`, `docs/kubernetes-vending.md`)
- [x] T012 [US3] [FR-009,FR-014] Pin compatible Argo CD and Kyverno releases while retaining disabled rollout defaults. (evidence: `ansible/roles/cluster_addons/defaults/main.yml`, `ansible/roles/cluster_addons/templates/helmfile.yaml.j2`, `research.md`)
- [x] T013 [US3] [FR-013,SR-002] Stream Kubernetes Secret manifests through stdin without arguments, temporary files, registered output, or diffs. (evidence: `ansible/roles/cluster_apps/tasks/main.yml`, `ansible/roles/cluster_harvester/tasks/main.yml`, `tests/catalog/test_secret_materialization.py`)

## Phase 4: External-provider lifecycle and recovery

- [x] T014 [US4] [FR-010] Model one dedicated, operator-only Supabase project with public signup and Storage disabled and no backup promise. (evidence: `catalog/schema/service.schema.json`, `catalog/examples/supabase-auth-canary.yaml`, `modules/external/supabase_project/`, `docs/service-vending.md`)
- [x] T015 [US4] [FR-011,SR-005] Implement local serialized reconciliation with bounded leases, idempotent SHA checks, checkpoints, sanitized failures, and isolated provider state. (evidence: `scripts/external-provider-reconciler.py`, `live/aws/organization/external-control/`, `tests/catalog/test_external_reconciler.py`)
- [x] T016 [US4] [FR-012] Require UID plus exact catalog-SHA purge confirmation and permanent tombstones. (evidence: `scripts/external-provider-reconciler.py`, `scripts/service-catalog.py`, `tests/catalog/test_external_reconciler.py`)
- [x] T017 [US4] [FR-013,FR-016] Provide runtime secret references, operator-only restore, and an auth canary that avoids response-body disclosure. (evidence: `scripts/supabase-restore.py`, `scripts/supabase-auth-canary.py`, `docs/service-vending.md`, `tests/catalog/test_secret_materialization.py`)

## Phase 5: Specification and repository contract retrofit

- [x] T018 [US5] [FR-017] Install the pinned Spec Kit 0.16.4 Codex/shell scaffold without replacing root `AGENTS.md`, then add concrete constitutions and local safety overrides. (evidence: `.specify/integration.json`, `.specify/integrations/`, `.agents/skills/speckit-*/SKILL.md`, `.specify/templates/overrides/`)
- [x] T019 [US5] [FR-006] Add the same managed scaffold, generic service constitution, overrides, and pinned tooling policy to the golden service template. (evidence: `templates/service-stack/.specify/`, `templates/service-stack/.agents/`, `templates/service-stack/tooling/repository-intelligence.json`)
- [x] T020 [US5] [FR-019] Move OpenAPI source to `contracts/openapi/` and update SDK, workflow, CODEOWNERS, documentation, and stable-publish filters. (evidence: `contracts/openapi/`, `scripts/sdk-generate.sh`, `scripts/sdk-pages.sh`, `.github/workflows/sdk.yml`, `.github/workflows/api-docs.yml`)
- [x] T021 [US5] [FR-017] Add deterministic Spec Kit and template-contract checks for pins, hashes, placeholders, task evidence, deferred explanations, and snapshot freshness. (evidence: `scripts/spec-kit-audit.py`, `tests/catalog/test_service_template.py`, `.github/workflows/spec-kit-audit.yml`)
- [x] T022 [US5] [FR-020] Generate stable module input/output tables with pinned terraform-docs and add reviewed Mermaid architecture. (evidence: `scripts/terraform-docs.sh`, `.terraform-docs.yml`, `modules/*/*/README.md`, `plan.md`)

## Phase 6: Repository intelligence and reviewed snapshot

- [x] T023 [US5] [FR-018] Pin RepoWise 0.43.0, keep its index ignored, disable prose/telemetry/editor changes/keys/hooks, and document user-local MCP registration plus explicit init/update commands. (evidence: `tooling/repository-intelligence.json`, `.gitignore`, `scripts/repository-intelligence.sh`, `docs/repository-intelligence.md`)
- [x] T024 [US5] [FR-018] Pin Graphify 0.9.45 with Terraform/MCP extras, add scoped ignores and explicit generation/query boundaries, and prohibit automatic hooks or an always-on second index. (evidence: `tooling/repository-intelligence.json`, `.graphifyignore`, `scripts/repository-intelligence.sh`, ADR 0005)
- [x] T025 [US5] [FR-018,SC-007] Run Graphify after the retrofit, review inferred edges and graph health, and commit a concise point-in-time repository map. (evidence: `docs/reviews/pr-30-repository-map.md`; raw `graphify-out/graph.json` and HTML retained only as ignored audit attachments)
- [x] T026 [US5] [FR-018,SC-006] Run RepoWise overview, `main...HEAD` change risk, and targeted context/risk checks for catalog, AWS, Kubernetes, and secret paths. (evidence: `docs/reviews/pr-30-repository-map.md`, local `.repowise/` index metadata)
- [x] T027 [US5] [FR-017,SR-006] Run Spec Kit analyze read-only, then converge append-only and preserve every identified gap as evidence or an explicit deferred gate. (evidence: `specs/001-safe-service-vending/analyze-report.md`, Phase 8 convergence tasks below)

## Phase 7: Static validation and delivery

- [x] T028 [US5] [SC-008] Run catalog unit, Ansible syntax, OpenTofu validation, TFLint, formatting, Trivy, Checkov, Gitleaks, SDK, Spectral, documentation, and pre-push suites without live credentials. (evidence: `specs/001-safe-service-vending/validation.md`)
- [x] T029 [US5] [SC-003] Scan generated Markdown and reviewed graph artifacts with Gitleaks and record the clean result. (evidence: `specs/001-safe-service-vending/validation.md`)
- [x] T030 [US5] [SC-007] Push the retrofit as a commit separate from implementation and update draft PR #30 with direct audit, matrix, ADR, and repository-map links. (evidence: commit containing this file and PR #30 description/comment links)

## Phase 8: Convergence - live evidence intentionally outstanding

- [>] T031 [US2] [FR-003,FR-014] Apply AWS organization and account roots and vend accounts only in an approved operator window. (reason: static repository evidence cannot prove a live apply and this retrofit has no live-change authorization; gate: protected environment approval, reviewed plans, backend readiness, quota and root-email checks; evidence: `docs/account-vending.md`, `.github/workflows/account-vend.yml`)
- [>] T032 [US2] [FR-005] Vend or migrate live GitHub repositories through the local App boundary. (reason: no repository creation is needed to validate the implementation; gate: seeded and protected template, reviewed history migration/import, authorized App runtime; evidence: `scripts/repository-tofu.py`, `live/aws/organization/repositories/`)
- [>] T033 [US3] [FR-008,FR-009] Rebuild/restore Kubernetes 1.35 and enable Argo CD or Kyverno only after live readiness proofs. (reason: cluster mutation and downtime are outside this PR; gate: verified off-node etcd/application restores, maintenance approval, health/reboot/policy/rollback evidence; evidence: `docs/kubernetes-vending.md`, `ansible/roles/cluster_addons/defaults/main.yml`)
- [>] T034 [US4] [FR-010,FR-011,FR-012] Create, exercise, and purge the unique hosted Supabase adapter canary before enabling normal live reconciliation. (reason: this would consume scarce hosted capacity and mutate an external provider; gate: harvester rotation, sensitive-state readiness, unique canary approval, lifecycle evidence and tombstone; evidence: `catalog/external-provider-gates.json`, `docs/service-vending.md`)
- [>] T035 [US4] [FR-013] Resolve runtime secrets only during separately authorized live operations. (reason: static validation needs no secret value and retrieval is explicitly prohibited in this retrofit; gate: installed secret-safety tooling, authorized operator, runtime `asm-exec` dynamic references, tracing disabled; evidence: `AGENTS.md`, `docs/account-vending.md`, `docs/service-vending.md`)

## Dependencies and Gates

- Phases 1 through 4 are the pre-existing implementation baseline.
- Phase 5 establishes intent and deterministic repository contracts before intelligence.
- RepoWise updates after source changes; Graphify snapshots only after the Spec Kit retrofit.
- Phase 8 is not required to merge static safety controls. Each task requires separate
  authority and must not be checked merely because repository validation passed.

## Live-Mutation Disclosure

No live Kubernetes downgrade/rebuild, AWS apply, account vend, repository vend, Supabase
project mutation, hosted canary, or secret retrieval occurred. All corresponding rollout
gates remain disabled.
