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
environment: prod
```

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

Controls, in the order they apply:

1. **`prod` deploys only from `main` (applied).** The `prod` environment has a
   deployment branch policy that allows `main` only. GitHub checks it before it
   assigns a runner, so a job on any other ref that targets the Mac fails at the
   environment gate. Required reviewers are **not** available: GitHub rejects that
   rule for a private repository on the Team plan.
2. **Every operator job declares `environment: prod` (enforced by test).**
   `test_operator_jobs_require_the_prod_environment` fails any job that routes to
   `CI_OPERATOR` or `homelab-operator` without it. Without the environment, the branch
   policy would not apply.
3. **Org runner group `homelab-operator`, restricted to this repository (owner action).**
   This needs an org owner token with `admin:org`, which the current `gh` token
   does not have:

   ```bash
   gh auth refresh -h github.com -s admin:org
   gh api -X POST orgs/TusharSariyaOrg/actions/runner-groups \
     -f name=homelab-operator -f visibility=selected \
     -F 'selected_repository_ids[]=1284389494'   # TusharSariyaOrg/aws-account-infra
   ```

   Then register (or re-register) with `RUNNER_GROUP=homelab-operator` set (see
   Install). A repository-level registration, the default, is already scoped to
   this repository.
4. **The runner is offline outside maintenance windows.** The LaunchDaemon has
   `RunAtLoad` and `KeepAlive` set to false. Install leaves it stopped. Start it for
   a window and stop it afterwards.
5. **Dedicated non-admin user.** `ghrunner` is a hidden, standard account with
   shell `/usr/bin/false` and no sudo. It has no `~/.kube`, `~/.aws` or `~/.talos`
   and no access to the owner's keychain. Jobs get AWS credentials through OIDC,
   and Talos secrets from repository secrets into `$RUNNER_TEMP`, then delete them.

Forking is disabled and the repository has a single admin collaborator, so fork PRs
cannot reach the runner.

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
RUNNER_TOKEN="$(gh api -X POST repos/TusharSariyaOrg/aws-account-infra/actions/runners/registration-token --jq .token)" \
  ./scripts/mac-operator-runner.sh install
# with the org group created (security control 3):
RUNNER_GROUP=homelab-operator RUNNER_TOKEN="$(gh api -X POST repos/TusharSariyaOrg/aws-account-infra/actions/runners/registration-token --jq .token)" \
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

   The job waits for the `prod` environment. It then runs on
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
- **Branch policy covers PR runs too.** The PR-triggered operator jobs (`tofu-plan`
  Proxmox/Talos plans, `tofu-apply` hardware applies, admission PR plans) declare
  `prod`, so the main-only branch policy governs them on hosted runners as well as
  on the Mac.
- **Persistent host.** The workspace (`_work`) and the talos tool cache survive
  between jobs. Workflows keep secrets in `$RUNNER_TEMP` and remove them. Cached
  tools are re-hashed before use.

## Uninstall

```bash
RUNNER_TOKEN="$(gh api -X POST repos/TusharSariyaOrg/aws-account-infra/actions/runners/remove-token --jq .token)" \
  ./scripts/mac-operator-runner.sh uninstall
sudo sysadminctl -deleteUser ghrunner   # optional: removes the user and install dir
```
