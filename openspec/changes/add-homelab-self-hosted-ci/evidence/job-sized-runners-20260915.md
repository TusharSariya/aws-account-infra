# Job-sized runner implementation and deployment, 2026-09-15

## Scope and source

Worktree: `/private/tmp/aws-account-infra-sized-runners`, branch
`feat/job-sized-kueue-runners`, based on merged PR #79 (`6a2d681`). The original
planning checkout and its uncommitted work were preserved. Existing evidence
remains authoritative for earlier observations; this entry does not replace it.

## Local verification

- 18 Kueue unit/contract tests passed, including actual pinned ARC Helm rendering
  of all catalog configurations and arbitrary 3.001-CPU Docker budget splitting.
- 15 CEL cases passed, including CPU, memory and scratch oversized rejection,
  restartable-init accounting, operational bypass and privileged gate removal.
- 23 affected-state selection tests and 5 relevant-check selection tests passed.
- OpenTofu validation/formatting, actionlint with ShellCheck, strict OpenSpec and
  whitespace checks passed. These are local results, not GitHub check evidence.

## Guarded deployment

The existing Mac recovery/administration path applied the exact saved CI-root
plan through `scripts/homelab-ci.py`. The plan updated Kueue/queue, moved the
existing runner state address without replacing the release, and created the
light/checks scale sets. No deletions or other state roots were included.

Private immutable plan, kubeconfig, execution receipt and post-plan are under
`~/.config/aws-account-infra/kueue/sized-runners-20260915-01/`. Credentials and plan
contents are intentionally not committed. The receipt records successful apply
and `post_plan_empty=true`.

Observed preflight: worker allocatable 37.95 CPU, 176626296 KiB RAM and
94227975217 bytes ephemeral storage; projected platform requests 1.056 CPU,
1358954496 bytes RAM; root/image used 19076153344 bytes (images included in root
usage); 8-GiB additional storage headroom; 22 projected platform Pods, 30 maximum
catalog runner slots and 10 additional Pod slots within the node's 110 limit.
AI termination and Pi-hole TCP/UDP DNS passed before plan and apply.

Observed after apply: `homelab-talos`, `homelab-talos-checks` and
`homelab-talos-light` exist with `minRunners=0` and no `maxRunners`. Fresh guarded
post-deployment plan is empty. CI_EXECUTOR remains unset, preserving hosted
routine execution pending acceptance. No Actions budget changes were made.

## Acceptance status

Runtime scenarios are recorded below only after observation. Deployment and local
contracts do not prove mixed-size GitHub execution, full application compatibility,
GitHub queue expiry, recovery or global routing completion. Unobserved OpenSpec
tasks remain unchecked.
