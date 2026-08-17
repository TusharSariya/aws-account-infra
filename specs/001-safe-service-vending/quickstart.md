# PR #30 Audit Guide

This guide audits repository evidence only. It does not authorize or prove any live AWS,
Kubernetes, GitHub, Supabase, or secret operation.

## 1. Confirm provenance and layout

```bash
git status --short
python3 scripts/spec-kit-audit.py
rg -n 'specs/[^ ]*/openapi|product/' --glob '!specs/001-safe-service-vending/**'
```

Expected: Spec Kit 0.16.4 manifests validate, no placeholders or task-evidence gaps are
reported, root and template contracts pass, and OpenAPI source exists only under
`contracts/openapi/`.

## 2. Verify deterministic vending behavior

```bash
python3 scripts/service-catalog.py validate
python3 scripts/service-catalog.py render
git diff --exit-code -- catalog/catalog.json
python3 scripts/kubernetes-vending.py validate --target homelab --phase native
python3 scripts/kubernetes-vending.py validate --target homelab --phase argocd
python3 -m pytest -q tests/catalog
```

Inspect `catalog/external-provider-gates.json` and confirm live gates remain false.

## 3. Verify API and IaC interfaces

```bash
npx --yes @stoplight/spectral-cli@6.15.0 lint 'contracts/openapi/*/openapi.yaml' -r contracts/openapi/.spectral.yaml
./scripts/sdk-generate.sh upace python
./scripts/sdk-generate.sh upace typescript-fetch
./scripts/sdk-pages.sh build/api-docs
scripts/terraform-docs.sh --check
```

Run OpenTofu, Ansible, lint, and security suites from the repository's existing pre-push
and CI entry points. They require no live cloud credential for validation.

## 4. Inspect supplementary intelligence

```bash
scripts/repository-intelligence.sh repowise-update
scripts/repository-intelligence.sh repowise-risk main...HEAD
scripts/repository-intelligence.sh graphify-query 'critical service-vending paths'
```

Through the user-local RepoWise MCP, call `get_overview`,
`get_change_risk("main...HEAD")`, and targeted context/risk queries for catalog
validation, AWS control-plane IaC, Kubernetes policy, and secret materialization. Compare
Graphify health and impact results with `docs/reviews/pr-30-repository-map.md`.

## 5. Confirm non-actions

The audit is valid only if no live Kubernetes rebuild/downgrade, AWS apply, account vend,
repository vend, Supabase project creation/purge, hosted canary, or secret retrieval was
performed. Leave every rollout gate disabled until separate operator evidence is linked.
