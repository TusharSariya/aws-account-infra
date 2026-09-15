## Why
Application compute needs one bounded admission pool on the existing Talos worker. GitHub-hosted bootstrap and Mac recovery must remain independent of that pool.

## What Changes
- Replace the separate VM runner proposal with pinned Kueue 0.19.4 and ARC 0.14.2.
- Restore worker RAM to 172 GiB and admit AI, CI and ordinary Argo Pods against one 36 CPU / 160 GiB pool.
- Preserve lifecycle controls, retained AI storage, reviewed workflows and deployment gates.
- Retire only identified VM 103 CI resources through guarded maintenance.
- Select routine execution explicitly with CI_EXECUTOR=github-hosted|talos after acceptance; no automatic paid fallback.

## Capabilities
### New Capabilities
- `homelab-self-hosted-ci`: shared compute admission and disposable Talos runners.
### Modified Capabilities
None. Existing AI lifecycle controls remain authoritative.

## Impact
Three reviewed PRs: foundation, admission/runners, cutover. New state key: kubernetes/homelab-ci/terraform.tfstate. Existing roots and keys remain intact. The prior plan and completed checkboxes are preserved in evidence/pre-kueue-plan; they do not prove this migration.
