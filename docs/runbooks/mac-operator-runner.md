# macOS operator runner

The operator runner is a GitHub Actions self-hosted runner on the owner's MacBook
(Apple silicon). It runs the class 2 "circular" jobs: maintenance that mutates the
Proxmox hosts, Talos nodes or admission path that the ARC runners themselves run on.
These jobs cannot run on ARC, and hosted runners become only the fallback.

Routing has three classes:

| Class | Jobs | Switch | Fallback when unset |
| --- | --- | --- | --- |
| 1. Routine | Everything else | `vars.CI_EXECUTOR` (`talos` = ARC) | `ubuntu-latest` |
| 2. Circular / off-cluster | See the table below | `vars.CI_OPERATOR` (`mac` = this runner) | `ubuntu-latest` |
| Hosted by design | `homelab-etcd-backup/backup`, `ci-runner-image/build` (dispatch) | none | n/a |

Class 2 jobs use exactly this expression, which
`scripts/tests/test_ci_executor_routing.py` enforces:

```yaml
runs-on: ${{ vars.CI_OPERATOR == 'mac' && fromJSON('["self-hosted","macOS","homelab-operator"]') || 'ubuntu-latest' }}
```

Every class 2 job also declares `environment: prod`.

| Workflow / job | Trigger |
| --- | --- |
| `homelab-ci-admission` / `admission` (not `contracts`) | PR plan, dispatch plan/apply |
| `tofu-plan` / `proxmox-plan`, `talos-plan` | PR |
| `tofu-apply` / `apply`, only when a Proxmox or Talos unit is selected (other units follow `CI_EXECUTOR`) | PR with `apply` label |
| `homelab-worker-maintenance` / `worker-reboot` | dispatch, or called from `tofu-apply` |
| `homelab-lifecycle-maintenance` / `proof` | dispatch, or called from `tofu-apply` |
| `homelab-ai-migration` / `reset` | dispatch |
| `homelab-capacity-host` / `reconcile` | dispatch |
| `homelab-quota-acceptance` / `proof` | dispatch |

## Security model

Environment:

- **Every operator job uses `prod`, which is unrestricted.** `prod` holds the
  Talos, lifecycle and capacity secrets. The AWS apply role and the Tailscale
  `tag:github-ci` OIDC login trust only `environment:prod`. PR plans and the
  apply-before-merge flow deploy from `refs/pull/N/merge`, so a main-only policy on
  `prod` would break them. `test_operator_jobs_require_the_prod_environment` fails
  any job that routes to `CI_OPERATOR` or `homelab-operator` without
  `environment: prod`.
- **Required reviewers: unavailable.** GitHub rejects that rule for a private
  repository on the Team plan.
- **No branch restriction on any operator job yet.** See "Future hardening" below.

Controls on the runner itself:

1. **Org runner group `homelab-operator`, restricted to this repository (owner action).**
   This needs an org owner token with `admin:org`, which the current `gh` token
   does not have:

   ```bash
   gh auth refresh -h github.com -s admin:org
   gh api -X POST orgs/TusharSariyaOrg/actions/runner-groups \
     -f name=homelab-operator -f visibility=selected \
     -F 'selected_repository_ids[]=1284389494'   # TusharSariyaOrg/aws-account-infra
   ```

   Then register (or re-register) with `RUNNER_GROUP=homelab-operator` set (see
   Install). Runner groups exist only at the organization level, so a grouped
   runner registers with the organization URL and an organization registration
   token; the group limits it to this repository. A repository-level
   registration, the fallback, is already scoped to this repository but cannot
   join a group.
2. **The runner is offline outside maintenance windows.** The LaunchDaemon has
   `RunAtLoad` and `KeepAlive` set to false. Install leaves it stopped. Start it for
   a window and stop it afterwards.
3. **Dedicated non-admin user.** `ghrunner` is a hidden, standard account with
   shell `/usr/bin/false` and no sudo. It has no `~/.kube`, `~/.aws` or `~/.talos`
   and no access to the owner's keychain. Jobs get AWS credentials through OIDC,
   and Talos secrets from `prod` environment secrets into `$RUNNER_TEMP`, then
  delete them.

Forking is disabled and the repository has a single admin collaborator, so fork PRs
cannot reach the runner.

### Residual risk

Every operator job, dispatched or PR-triggered, runs under the unrestricted `prod`
environment. While `CI_OPERATOR=mac` and the runner is online, a workflow from any
same-repository branch that targets `homelab-operator` with `environment: prod` can
run on the Mac. Only three controls protect it:

- the runner is offline outside maintenance windows;
- the org runner group is restricted to this repository;
- the runner uses a dedicated non-admin user.

Usability consequence: while `CI_OPERATOR=mac`, a PR touching `live/proxmox` or
`live/talos` cannot pass `plan-gate` until the owner brings the Mac runner online. The
alternative is to unset `CI_OPERATOR`, which falls back to hosted runners.

## Future hardening: main-only operator environment

Dispatched maintenance could run under a separate `operator` environment that
deploys from `main` only. PR plans, `tofu-apply` hardware applies and the reusable
calls from `tofu-apply` would keep `prod`, because they deploy from
`refs/pull/N/merge`. An attempt was reverted because every prerequisite below must
be in place first; otherwise every maintenance dispatch breaks.

1. **Create the environment with a main-only branch policy:**

   ```bash
   gh api -X PUT repos/TusharSariyaOrg/aws-account-infra/environments/operator \
     -F 'deployment_branch_policy[protected_branches]=false' \
     -F 'deployment_branch_policy[custom_branch_policies]=true'
   gh api -X POST repos/TusharSariyaOrg/aws-account-infra/environments/operator/deployment-branch-policies \
     -f name=main -f type=branch
   gh api repos/TusharSariyaOrg/aws-account-infra/environments/operator \
     --jq '{deployment_branch_policy, protection_rules}'
   ```

2. **Copy the `prod` secrets and variable it needs.** Secrets cannot be read back
   from GitHub, so re-enter each value from its original private source:
   - `TALOS_SECRETS_B64`
   - `AI_LIFECYCLE_CREDENTIALS_B64`
   - `CAPACITY_CLIENT_CREDENTIALS_B64`
   - `CAPACITY_HOST_CREDENTIALS_B64`
   - `CAPACITY_HOST_SSH_KEY`
   - `ARC_GITHUB_APP_JSON_B64`, if it is used

   ```bash
   gh secret set TALOS_SECRETS_B64 --env operator < /PRIVATE/talos-secrets.b64   # repeat per secret
   gh variable set CAPACITY_HOST_KNOWN_HOSTS --env operator \
     --body "$(gh variable get CAPACITY_HOST_KNOWN_HOSTS --env prod)"
   ```

3. **Widen the AWS apply-role trust.** In `modules/aws/account_identity/github_oidc.tf:107`
   the `TOFU_APPLY_ROLE_ARN` trust accepts only `environment:prod`. It must also
   accept `${local.github_sub_prefix}:environment:operator`, applied through the
   `aws-staging-account` root. The plan role already trusts any subject in the
   repository.
4. **Update the Tailscale login rule.** The `tag:github-ci` OIDC trust credential
   subject is `repo:TusharSariyaOrg/aws-account-infra:environment:prod`
   (`live/proxmox/homelab/CI.md`). Add a credential or rule for
   `...:environment:operator` so that the hosted fallback of dispatched jobs can join
   the tailnet. The Mac path does not use the Tailscale action.
5. **Switch the workflows.** Dispatch-only workflows (`homelab-ai-migration`,
   `homelab-capacity-host`, `homelab-quota-acceptance`) use `environment: operator`.
   `homelab-ci-admission/admission`, `homelab-worker-maintenance` and
   `homelab-lifecycle-maintenance` use
   `environment: {name: "${{ github.event_name == 'workflow_dispatch' && 'operator' || 'prod' }}"}`.
   Extend `test_ci_executor_routing.py` to require `operator` for dispatch-only
   workflows. Revert commit `67f275e` (which undid `922a823`) to restore both
   changes.

## Prerequisites

The script checks these but never installs them. Install them as the admin user:

```bash
brew install opentofu uv helm kubernetes-cli jq gh tailscale python@3.13 awscli
```

- The runner PATH is `/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin`. It is set in
  the LaunchDaemon and in the runner's `.path` file. `python3` on that PATH must be
  3.11 or newer; the macOS Command Line Tools ship 3.9 in `/usr/bin`.
- Tailscale: the Mac must already be on the tailnet with subnet routes accepted
  (`tailscale set --accept-routes=true`) and MagicDNS enabled.
  - On macOS, jobs never start the `tailscale/github-action` node and never run
    `sudo tailscale set`. They only assert that `tailscale status --json` reports
    `BackendState == "Running"`.
  - Proxmox applies additionally require `pve.tail2f646b.ts.net` to resolve. The job
    never edits the Mac's `/etc/hosts`.
  - The Mac's tailnet identity needs the same ACL grants as `tag:github-ci`.
  - Check that the CLI works for the runner user:
    `sudo -u ghrunner -H tailscale status`. If the GUI app's daemon is not reachable
    from that user, use the app's CLI integration rather than the Homebrew formula.
- The repo scripts download pinned, sha256-verified darwin/arm64 builds of kubectl and
  talosctl (`scripts/talos_tools.py`, into `~ghrunner/.cache/aws-account-infra/talos`)
  and age (`scripts/ai-data-backup.py`).
  The Homebrew `kubectl` only satisfies the tool check.

## Install

From an administrator account in a checkout of this repository:

```bash
./scripts/mac-operator-runner.sh token-help
# recommended: org-level registration into the runner group (needs admin:org)
RUNNER_GROUP=homelab-operator RUNNER_TOKEN="$(gh api -X POST orgs/TusharSariyaOrg/actions/runners/registration-token --jq .token)" \
  ./scripts/mac-operator-runner.sh install
# fallback: repository-level registration, no group (needs repository admin)
RUNNER_TOKEN="$(gh api -X POST repos/TusharSariyaOrg/aws-account-infra/actions/runners/registration-token --jq .token)" \
  ./scripts/mac-operator-runner.sh install
```

The token expires 60 minutes after it is issued. `install` runs these steps:

1. Checks Apple silicon and the prerequisites.
2. Obtains sudo.
3. Creates `ghrunner`. `sysadminctl` prompts for a password: type a long random
   value and do not record it.
4. Downloads `actions-runner-osx-arm64-2.337.0.tar.gz` and verifies its pinned sha256.
5. Unpacks it into `/Users/ghrunner/actions-runner`.
6. Registers it as `mac-operator-<LocalHostName>` with label `homelab-operator`
   (GitHub adds `self-hosted`, `macOS` and `ARM64`).
7. Installs `/Library/LaunchDaemons/dev.tfdraw.homelab.operator-runner.plist` from
   `platform/operator-runner/`.

The runner name never starts with `homelab-talos-`. That keeps it on the upstream
`opentofu/setup-opentofu` path and outside the ARC-only setup branches.

## Maintenance window, end to end

1. Open the window and confirm the runner is online:

   ```bash
   ./scripts/mac-operator-runner.sh start
   ./scripts/mac-operator-runner.sh status   # status=online busy=false
   ```

2. Route class 2 jobs to the Mac:

   ```bash
   gh variable set CI_OPERATOR --body mac
   ```

3. Dispatch from `main`, for example:

   ```bash
   gh workflow run homelab-worker-maintenance.yml --ref main -f confirm=talos-worker-01
   gh run watch "$(gh run list --workflow homelab-worker-maintenance.yml --limit 1 --json databaseId --jq '.[0].databaseId')"
   ```

   The job enters the `prod` environment. It then runs on
   `mac-operator-*` and asserts the tailnet session. It fetches the pinned
   darwin/arm64 talosctl and kubectl and runs the operation.
4. Close the window:

   ```bash
   gh variable delete CI_OPERATOR           # back to the hosted fallback
   ./scripts/mac-operator-runner.sh stop
   ```

To fall back to hosted at any time, delete the variable (or set it to anything other
than `mac`). Queued jobs that already targeted the Mac stay queued until the runner
starts or the run is cancelled.

## Limitations

- **No Docker.** `talos-runner-setup` fails with `docker: 'true'` on macOS. Docker and
  image-build jobs stay on ARC or hosted.
- **Hosted by design:**
  - `homelab-etcd-backup` is a daily cron at 06:17 UTC, and the Mac may be asleep.
    Its daily age encryption is also Linux amd64 only.
  - `ci-runner-image/build` builds a `linux/amd64` image with Docker.
- **No Nexus.** Nexus is reachable only inside the cluster. On macOS,
  `talos-runner-setup` does not enable `HOMELAB_DEPENDENCY_CACHE` or call
  `talos-cache-setup.sh`, and `nexus-dependency-cache` is skipped. Downloads go
  upstream with pinned checksums.
- **PR hardware plans wait for the Mac.** See "Residual risk" above: while
  `CI_OPERATOR=mac`, PR-triggered operator jobs queue until the runner is online.
- **Persistent host.** The workspace (`_work`) and the talos tool cache survive
  between jobs. Workflows keep secrets in `$RUNNER_TEMP` and remove them. Cached
  tools are re-hashed before use.

## Uninstall

```bash
# org-registered runner (the default install above)
RUNNER_GROUP=homelab-operator RUNNER_TOKEN="$(gh api -X POST orgs/TusharSariyaOrg/actions/runners/remove-token --jq .token)" \
  ./scripts/mac-operator-runner.sh uninstall
# repository-registered runner
RUNNER_TOKEN="$(gh api -X POST repos/TusharSariyaOrg/aws-account-infra/actions/runners/remove-token --jq .token)" \
  ./scripts/mac-operator-runner.sh uninstall
sudo sysadminctl -deleteUser ghrunner   # optional: removes the user and install dir
```
