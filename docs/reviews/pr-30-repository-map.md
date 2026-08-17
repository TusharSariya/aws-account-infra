# PR #30 Repository Map

Analyzed implementation commit: `20e16726ef2f95cebadcac5820ec2ee000503091`

This is a reviewed, point-in-time architecture snapshot for PR #30. Graphify analyzed
an isolated detached worktree based on the implementation commit with this Spec Kit
retrofit overlaid. The unrelated local Ubuntu desktop and Tailscale edits were excluded.
The raw `graph.json`, `graph.html`, and generated report remain ignored audit artifacts
under `graphify-out/`; this concise review is the committed record.

## Snapshot identity

| Item | Value |
| --- | --- |
| Graphify | v0.9.45 with Terraform and MCP extras |
| Extraction model | Codex semantic extraction; per-agent token usage was unavailable and is recorded as zero, not estimated |
| Graph mode | Undirected, no automatic hooks |
| Corpus | 480 files, approximately 166,482 words |
| Graph | 2,378 nodes, 3,904 post-build edges, 243 communities |
| Confidence | 95% extracted, 5% inferred, 0% ambiguous; 184 inferred edges at 0.61 average confidence |
| PR impact | 325 changed files mapped to 1,626 nodes across 168 communities |
| Raw artifacts | `graphify-out/graph.json`, `graphify-out/graph.html`, and `graphify-out/GRAPH_REPORT.md` (ignored) |

## Architecture communities

The most relevant communities for safe service vending are:

- Service catalog schema and compiler: validates immutable service identity, capacity,
  repository, AWS, Kubernetes, and external-service declarations before rendering.
- AWS organization and account control planes: separates organization, account,
  bootstrap, repository, access, security, and external-control state and authority.
- Vended account baseline and identity: composes governance, artifact repositories,
  OIDC roles, Roles Anywhere, and immutable distribution references.
- External provider reconciliation: uses a local serialized journal and state lock for
  Supabase lifecycle work that must not run in GitHub-hosted automation.
- Kubernetes automation: combines fail-closed add-on and tenant gates, native admission
  controls, Argo CD resources, node identity, and validation roles.
- Safe vending specification: binds the feature specification, plan, data model,
  research, checklists, evidence-bearing tasks, and static convergence report.
- Golden service template: carries the same pinned Spec Kit command pack, constitution,
  local overrides, and repository-contract validation into newly vended repositories.
- OpenAPI and SDK delivery: keeps API contracts independent from numbered product specs
  while preserving Spectral, Python, TypeScript, and documentation workflows.

## Critical dependency paths

1. Catalog YAML -> JSON Schema validation -> normalized `catalog/catalog.json` -> AWS,
   Kubernetes, repository, and external-provider renderers. The catalog UID and provider
   identities are the immutable join keys across those planes.
2. Account request -> Organizations create checkpoint -> account ID reconciliation PR ->
   account baseline -> repository/bootstrap/access roots. Each stage has separate state
   so a failed stage can resume without repeating account creation.
3. External service declaration -> serialized reconciler -> DynamoDB journal and lock ->
   Supabase OpenTofu module -> local auth canary and restore evidence. Live provider work
   remains outside hosted CI.
4. Kubernetes catalog target -> generated native tenant controls -> optional Argo CD
   applications. Add-on, policy-enforcement, and tenant rollout gates all default false.
5. Feature requirements -> plan and data model -> evidence-bearing tasks -> deterministic
   audit. The graph confirms the specification-to-task edge directly; live evidence stays
   represented by deferred tasks rather than static-test claims.

## Reviewed surprising connections

- The inferred connection from Spec Kit's read-only analyze workflow to the committed
  analysis report is valid as provenance, but it is not an implementation dependency.
- The inferred connection between repository guidance and the constitution's fail-closed
  gates is valid: both require Kubernetes vending flags to remain disabled pending evidence.
- The tenant playbook to service-vending documentation edge is valid: the playbook invokes
  the catalog-driven `kubernetes_tenants` role described by that document.
- The root rollout-gate statement to cluster add-on defaults edge is valid: Argo CD,
  Kyverno, and image-verification defaults are all false.
- The local Supabase canary to the catalog example edge is conceptually valid, but the
  canary proves application behavior only and does not prove hosted provider compatibility.
- Inferred application-model edges around `UpaceHttpBooker`, `BookingResult`, and
  `BookingRequest` are supplementary navigation hints and were not used as vending evidence.

## Graph health

The diagnostic found no missing endpoint fields, self-loops, or unverified code nodes.
It did report 489 dangling endpoint edges, primarily external imports and shortened code
references from application, OpenTofu, and script extraction. The undirected build also
collapsed 129 same-endpoint edges (126 in a directed simulation), including repeated schema
containment and call/type-reference variants. The final graph therefore preserves strong
repository navigation value but is not a lossless call graph. Critical claims above were
checked against source files and committed tests rather than inferred edges alone.

## Audit boundaries

No Kubernetes downgrade, AWS apply, account vend, repository vend, Supabase project
creation, hosted canary, or secret retrieval was performed while producing this snapshot.
No Graphify or RepoWise hooks were installed. The graph and index remain supplementary;
the specifications, ADRs, schemas, IaC, and tests remain authoritative.
