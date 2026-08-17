# Local repository intelligence

Committed specifications, ADRs, schemas, IaC, contracts, and tests are authoritative.
RepoWise and Graphify are local, supplementary evidence. Do not provide either tool with
credentials or configure a hosted backend that uploads private repository content.

Versions and sources are pinned in `tooling/repository-intelligence.json`.

## RepoWise primary index

Install v0.43.0, disable telemetry, and register the local MCP server in user-level Codex
configuration only:

```bash
uv tool install --from 'git+https://github.com/repowise-dev/repowise.git@v0.43.0' repowise
repowise telemetry disable
codex mcp add repowise -- repowise mcp
scripts/repository-intelligence.sh repowise-init
scripts/repository-intelligence.sh repowise-update
```

Initialization uses no model prose, editor setup, generated AGENTS/CLAUDE files, saved
key, telemetry, workspace discovery, or automatic hooks. Only ignored `.repowise/` may
change. Do not use `repowise init --dry-run` as a read-only probe: v0.43.0 was observed
persisting an index despite that flag.

After update, query `get_overview`, `get_change_risk("main...HEAD")`, and targeted
`get_context`/`get_risk` calls through MCP. Query commands must leave both source and
indexes byte-stable; the shell wrapper enforces this for its CLI query equivalents.

## Graphify reviewed snapshots

Install only Terraform and MCP extras:

```bash
uv tool install --from 'git+https://github.com/Graphify-Labs/graphify.git@v0.9.45' \
  'graphifyy[terraform,mcp]'
```

Generate `graphify-out/` only for high-risk pull requests, inspect inferred edges and
graph-health diagnostics, and publish a concise reviewed map under `docs/reviews/`.
Attach `graph.json` and HTML to the review as audit artifacts; do not commit them. No
Graphify hooks or second always-on index are installed.

Community Spec Kit extensions remain disabled because the upstream catalog warns that
community entries are not endorsed or audited. This repository uses core commands and
reviewed local template overrides only.
