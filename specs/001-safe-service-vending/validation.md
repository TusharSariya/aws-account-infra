# Validation Record

This record covers the static retrofit of PR #30. Commands ran against an isolated tree
containing the implementation commit and retrofit, with unrelated local Ubuntu desktop and
Tailscale changes excluded.

## Results

| Validation | Result |
| --- | --- |
| Spec Kit prerequisite, analyze, and converge stages | Pass; all 26 functional/security requirements map to tasks and the five live-evidence gaps remain T031-T035 |
| Spec Kit scaffold and golden-template contract | Pass; v0.16.4 manifests and file hashes verified for root and template |
| Repository unit tests | Pass; 61 tests |
| Court Booker Lambda tests | Pass; 38 tests |
| ShellCheck and Bats | Pass; 32 Bats tests |
| Ansible lint and syntax | Pass; production profile and all 13 playbooks, using a non-secret CI placeholder that could not decrypt committed vault ciphertext |
| OpenTofu formatting and validation | Pass; all 12 organization/external/module roots; Supabase provider emitted its existing `legacy_api_keys_enabled` deprecation warning |
| Terraform module documentation | Pass; eight module README tables match terraform-docs v0.24.0 output |
| OpenAPI Spectral lint | Pass; no error-severity findings |
| SDK generation and smoke tests | Pass; Python and TypeScript Fetch clients generated from `contracts/openapi/` and compiled/imported successfully |
| API documentation build | Pass; Swagger UI output generated from `contracts/openapi/` |
| Trivy | Pass; zero high/critical misconfigurations |
| Checkov | Pass; 991 passed, zero failed, 126 explicitly skipped |
| TFLint | Pass; recursive scan |
| Gitleaks | Pass; numbered specs, committed docs, raw graph JSON, graph HTML, and Graphify Markdown report scanned in directory mode with no findings |
| RepoWise v0.43.0 | Pass; fresh local index, overview, main-to-HEAD change risk, and targeted catalog/AWS/Kubernetes/secret-materialization context queries |
| Graphify v0.9.45 | Completed with disclosed health warnings; see the reviewed repository map |
| LocalStack smoke and integration | Not rerun; the local Docker socket became unavailable after the static scanner suite. Existing unit coverage passed, and this is not represented as integration evidence. |

## Repository intelligence observations

RepoWise indexed 479 files and 747 symbols into 1,705 nodes and 2,271 edges, with average
health 9.42 and 14 hotspots. Its main-to-implementation-HEAD comparison scored 9.9 at the
100th percentile of its 45-change local baseline: 211 files, 10,885 additions, and 577
deletions. Targeted hotspot percentiles were 99 for service catalog, 97 for Kubernetes
vending, 95 for external control, and 76 for repository OpenTofu. RepoWise does not have a
per-test coverage map here, so its test-gap labels were treated as a tooling limitation.

Graphify produced 2,378 nodes and 3,904 post-build undirected edges. PR-impact analysis
mapped 325 implementation-and-retrofit files to 1,626 nodes across 168 communities. Its
health diagnostic found 489 dangling references and 129 undirected same-endpoint collapses;
those limitations are preserved in the repository map rather than hidden.

## Live-mutation disclosure

No live Kubernetes downgrade, AWS apply, account vend, repository vend, Supabase project
creation, hosted Supabase canary, or secret retrieval occurred. No secret value was printed,
logged, committed, diffed, or passed in a process argument. Rollout gates remain disabled.
The local LocalStack sandbox, generated SDKs, documentation output, RepoWise index, and
Graphify artifacts are disposable validation outputs, not evidence of live rollout.
