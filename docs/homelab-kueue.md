# Shared homelab compute

## Policy and ownership

Kueue 0.19.4 admits declared CPU/RAM/ephemeral-storage requests against `homelab-compute` (36 CPU, 160 GiB), bound to `talos-worker-01`. AI, CI and Argo LocalQueues share the whole pool. StrictFIFO, equal priority and disabled preemption/borrowing are reviewed in `config/environments/kubernetes/homelab-ci/pool-values.yaml`. An older large waiting request blocks newer smaller work. Utilization does not affect reservations. GitHub's upstream queue is separate.

Kubernetes schedules admitted Pods and enforces limits. The AI lifecycle controller owns desired state, replicas, draining, idle shutdown and storage protection. ARC 0.14.2 owns disposable runners; Argo owns workflow execution. Platform controllers, DNS and operational commands stay outside Kueue.

AI retains 35.75 CPU / 77 GiB and its existing volumes. Each complete runner Pod reserves/limits its reviewed catalog CPU/RAM/scratch budget. Multiple disposable runners share admission, with zero idle runners and no ARC maximum. The shared scratch quota is 60 GiB. Trusted privileged runner/Docker containers use no host filesystem, host socket or host namespace mounts. GitHub fork PRs never run on Talos. The existing App registration key is not mounted into runner Pods; the runner service account has no Kubernetes API token.

## Automatic platform recovery

Both Talos VMs have `on_boot=true` in reviewed Proxmox configuration, with control-plane startup order 1 and worker order 2. The flags were applied after runner startup, checkout and tool setup passed; full CI acceptance remains gated. Essential Kubernetes services, including Pi-hole, retain their controller-managed replicas and start when their nodes return; their Pods stay outside Kueue. AI startup remains governed by lifecycle desired state, and ARC retains zero idle runners.

## Ordered rollout

Review three PRs in order: foundation; admission/runners; routing/acceptance. Keep AI off during migration and do not credit intermediate branch checks to a different source revision. Previous VM design/checkmarks are retained under the OpenSpec change's `evidence/pre-kueue-plan/`. Preserve all existing deployment logs and failed attempts.

1. Retire the old CI VM and restore worker RAM using the next section. Verify Pi-hole and actual allocatable capacity.
2. Deploy the independent CI/admission root with the hosted workflow or Mac path. Enroll the existing GitHub App privately. Existing application namespaces must already exist.
3. Deploy AI/lifecycle/Argo chart changes through the existing application root with AI off. New compute templates carry an admission gate even if Kueue has not yet installed its webhook. Operational templates have neither gate nor queue label.
4. Complete live acceptance, including a successful guarded private application deployment on ARC. Only then set repository variable `CI_EXECUTOR=talos`. Until then leave it unset or `github-hosted`.

Changing `CI_EXECUTOR` is explicit; unknown values fail workflow runner selection. There is no automatic paid fallback. CI/admission bootstrap, Proxmox/Talos changes and worker/recovery operations always use hosted runners. Routine application-only/AWS deployments can use Talos; a combined Proxmox/Talos apply stays hosted. Required plan/apply/publish gates retain their conditions.

## Retire VM 103

The only retirement targets are `proxmox_virtual_environment_vm.ci_runner[0]`, its pinned `ci_ubuntu[0]` import, and the worker's exact 156-to-172-GiB RAM change. Existing backends and Talos disks/identities remain unchanged. Normal deployment guards reject deletion; the migration uses its dedicated guard.

- Quiesce old CI and record AI Off with no remaining AI Pods. Run `scripts/ci-runner-stop.sh` on `pve` through the existing verified administration SSH connection. It verifies VM name, MAC, RAM, CPU and disk before graceful shutdown; it never forces shutdown.
- Use a fresh private directory and existing Mac tool/credential enrollment. Run `python3 scripts/ci-runner-bootstrap.py plan --stage retirement --record-dir PRIVATE --kubeconfig KUBECONFIG`, review the saved-plan receipt, then the same command with `apply`. Every retirement plan/apply also verifies AI Off and an empty AI Pod listing. The guard requires exactly the identified stopped VM/image deletion and RAM restoration; stale/modified plans and other changes are rejected. If VM 103 was never created, do not manufacture a retirement receipt: verify the already-restored worker directly and retain evidence of absent resources.
- Run `python3 scripts/ci-runner-worker-maintenance.py --restore-for-kueue --record-dir NEW_PRIVATE --bootstrap-record PRIVATE/record.json --kubeconfig KUBECONFIG --talosconfig TALOSCONFIG`. It requires the successful retirement receipt and absent VM 103, drains/shuts down the worker gracefully, starts it, observes a new boot/lease and 172-GiB effective memory, then verifies Pi-hole over UDP/TCP. Failed shutdown never falls back to force.
- On the existing router run `scripts/ci-runner-network-retire.py`; it removes only the exact dedicated reservation, retaining a private backup. Activate the router configuration through its existing reviewed maintenance procedure and repeat DNS checks.
- On `pve`, run `scripts/ci-runner-permissions-retire.sh` after VM absence is verified. It removes only dedicated CI ACL entries, retaining shared provider identities and the GitHub App/key. Role definitions without any grants carry no authority.

If retirement applies VM deletion/RAM configuration but fails only the pinned image deletion with `Datastore.Allocate`, use `scripts/ci-runner-retirement-recover.py --failed-record PRIVATE/record.json --record-dir NEW_PRIVATE --kubeconfig KUBECONFIG`. It checks the original guarded plan and exact live identities, removes only the checksum-verified image through existing root SSH and requires a fresh empty hardware plan. Retain the failed receipt; use the new recovery receipt for maintenance.

Do not enable the pool on a 156-GiB worker. `scripts/kueue_capacity.py` checks actual allocatable against the 36 CPU / 160 GiB pool plus a reviewed 1.5 CPU / 8 GiB platform reserve. It includes restartable init containers and Pod overhead in observed platform requests. If the check fails, inspect and review the budget; do not silently shrink it or disregard platform reservations.

## Independent bootstrap and recovery

State root: `live/kubernetes/homelab-ci`; S3 key: `kubernetes/homelab-ci/terraform.tfstate`. `deploy-units.json` marks it outside the general matrix because `.github/workflows/homelab-ci-admission.yml` exclusively owns its hosted plan/apply flow. The workflow uses the existing `prod` environment, OIDC roles, Tailscale enrollment and original Talos identity. Dispatch `mode=apply` with `confirm=homelab-ci` only after review. It applies the exact guarded saved plan and requires a fresh empty post-plan. Plans/credentials remain private; only a non-secret receipt is uploaded. Bootstrap can run with ARC absent.

The Mac remains the recovery path when hosted allowance is exhausted. Keep the existing Mac bootstrap and original secret recovery procedures. Use the pinned repository OpenTofu/kubectl setup (`scripts/local_lifecycle_tools.py`), Helm 3.19.0 and `uv`; connect through the existing tailnet and original cluster identity. With an owned mode-0700 directory containing a mode-0600 `kubeconfig`:

```sh
uv run --with PyYAML==6.0.3 python scripts/homelab-ci.py setup
tofu -chdir=live/kubernetes/homelab-ci init -input=false -lockfile=readonly
uv run --with PyYAML==6.0.3 python scripts/homelab-ci.py plan --private "$PRIVATE"
# Review the source/plan/capacity receipt before apply.
uv run --with PyYAML==6.0.3 python scripts/homelab-ci.py enroll --private "$PRIVATE" --app-json "$APP_JSON"
uv run --with PyYAML==6.0.3 python scripts/homelab-ci.py apply --private "$PRIVATE"
```

`APP_JSON` is an owned private file with exactly three string fields: `github_app_id`, `github_app_installation_id`, `github_app_private_key`. Recover the existing repository-scoped App/key; do not create a replacement App. Hosted enrollment takes the same JSON base64-encoded in protected secret `ARC_GITHUB_APP_JSON_B64`. It is applied directly as Secret `arc-runners/github-app`, never passed to OpenTofu values/state or job environments. Do not put key contents in command-line arguments or Git.

Every plan/apply rechecks AI termination, worker capacity and Pi-hole. Reuse no attempted receipt. Preserve failures before retrying in a new private directory. Applying this root never starts AI or switches routine routing.

## Status and cancellation

```sh
uv run --with PyYAML==6.0.3 python scripts/homelab-ci.py status --private "$PRIVATE"
python3 scripts/ai-control.py status --credentials "$LIFECYCLE_CREDENTIALS"
```

Queue order comes from Kueue's visibility API, not an estimate from CPU usage or creation timestamps. Status reports requested/reserved resources and workload conditions. AI's existing API states remain unchanged, with an added `queue` field and waiting reasons. Missing queue visibility is reported separately and cannot prevent Stop/Status. Read the current lifecycle revision before `start`, `stop` or `force-stop`; pass it with `--revision` using the existing API semantics.

Stop cancels a waiting start or drains running work. The lifecycle controller sets replicas to zero after draining; Kueue releases quota after it observes termination. Waiting does not count toward the configurable idle timer. Runtime template updates remain off-only. Kueue webhooks exclude operational Pods; lifecycle replica/annotation changes and off-template adoption also bypass Deployment webhook calls. New compute Pods require their queue, equal priority and Kueue's gate. Only Kueue may remove the gate. Oversized aggregate/init requests fail with a reduce-requests/review-budget message.

Argo admits each execution Pod independently. Reviewed smoke execution uses a 300-second process alarm after its container starts; time spent waiting for admission does not consume it. Future ordinary templates must supply an execution-only timeout too. Existing UTC schedules, suspended rollout default, `Forbid` and mutexes remain. Start/Stop/Force Stop/Status templates bypass the queue.

## Acceptance and evidence

Leave all unobserved acceptance unchecked in OpenSpec. Record source commit, run URL or local receipt, actual runner identity, before/after workload conditions, quota and cleanup evidence. Local tests cannot satisfy required GitHub checks.

- With AI off, no other waiting/running compute and scheduled jobs quiesced, run `python3 scripts/kueue-acceptance.py --kubeconfig "$KUBECONFIG" --scenario cpu`, then `--scenario memory`, `--scenario ephemeral-storage` and `--scenario combined`. Each creates uniquely named bounded Pods, proves older-large/newer-small FIFO blocking, queued cancellation, normal completion/release and cleanup. It never restarts a node/controller or deletes unrelated work.
- Dispatch `homelab-arc-acceptance` before changing routine routing. It explicitly selects the ARC scale set and covers checkout, Docker, a privileged bounded fixture, ARM Linux tests and private cluster networking. Repeat with a queued GitHub run and cancel it; verify its EphemeralRunner, Pod and Workload disappear. Record an expired-request case separately; a cancelled run does not prove expiry.
- AI-first: Start AI, verify its 35.75/77 reservation, dispatch an ARC job and observe it waiting. Stop AI and observe runner admission only after AI termination. CI-first: run a held ARC job, Start AI, observe AI pending with zero idle time, complete CI, then observe AI admission. End with AI Off.
- Exercise controller restart while queued/running, then node restart through the existing hosted worker-maintenance workflow. Verify no stale reservations, duplicate runners or unexpected AI desired-state change.
- During a controlled Kueue outage, prove operator Stop/Status and Pi-hole UDP/TCP remain usable, new compute cannot start and cleanup completes after controller recovery. Preserve and restore the exact controller replica count; do not force-remove workload finalizers to manufacture success.
- Run actual ARM candidate packaging/upload, Docker image publishing, the existing privileged disposable quota/reboot suite and a reviewed application-only private deployment on ARC. The latter still needs all protected environments, saved-plan checks and merge gates. Neither the local ARM test nor the acceptance network check proves private deployment.
- With ARC absent, dispatch hosted CI/admission plan/recovery. Require fresh empty post-deployment plans for every changed root, successful required GitHub checks and all three PR reviews before cutover.

## Upstream contracts

- [Kueue Deployment integration](https://kueue.sigs.k8s.io/docs/tasks/run/deployment/)
- [Argo plain-Pod integration](https://kueue.sigs.k8s.io/docs/tasks/run/external_workloads/argo_workflow/)
- [ClusterQueue policy](https://kueue.sigs.k8s.io/docs/concepts/cluster_queue/)
- [Kueue visibility API](https://kueue.sigs.k8s.io/docs/tasks/manage/monitor_pending_workloads/pending_workloads_on_demand/)
- [ARC 0.14.2 chart inputs](https://github.com/actions/actions-runner-controller/blob/gha-runner-scale-set-0.14.2/charts/gha-runner-scale-set/values.yaml)

## Runner catalog and measured admission

`config/environments/kubernetes/homelab-ci/runner-catalog.json` is authoritative.
CPU is cores to whole-millicore precision; memory and scratch are integer MiB.
These are arbitrary reviewed amounts, not fixed size tiers. OpenTofu generates
one homogeneous ARC scale set per entry, using the existing App/controller/state.
Adding a configuration requires catalog review and deployment before workflow use.

| runs-on | Whole-Pod CPU | RAM | Scratch | Docker |
| --- | ---: | ---: | ---: | --- |
| homelab-talos-light | 1 | 2 GiB | 2 GiB | No |
| homelab-talos-checks | 2 | 4 GiB | 4 GiB | No |
| homelab-talos | 4 | 16 GiB | 30 GiB | Yes |

Lightweight sizing is an initial budget. Promote a job through review when actual
usage exceeds it; do not automatically escalate resources or fall back to hosted.
`runner_catalog.py` validates all workflow names and effective resources from the
production OpenTofu locals. Contract tests additionally render the pinned ARC
chart and check aggregate requests/limits, including initialization and Docker.
All compute containers must declare ephemeral-storage so omitted requests cannot
bypass scratch admission. Pod limits include emptyDir, logs and writable layers.

Before plan and again before apply, the guard requires AI Off, idle runners,
fresh kubelet root/image storage samples, the 60-GiB pool plus 8-GiB additional
storage headroom fitting measured allocatable/free storage, all desired listener
requests inside the existing CPU/8-GiB RAM reserve, and sufficient Pod slots with
10 slots reserved for platform/ordinary Argo. Missing/stale measurements fail.
AI retained storage is never a fallback. Preserve the compatible Helm release
through the OpenTofu moved block; do not uninstall active runners.

### Job audit

- Light: detection, comments, required result gates, merge helpers, shell checks,
  Gitleaks, recovery unit tests, SDK spec lint and catalog validation.
- Checks: AWS/application plans and application-only apply, Ansible lint, Trivy,
  TFLint, SDK smoke, API docs build and reusable live acceptance.
- Docker: Checkov's Docker action, config/application tests using Docker,
  LocalStack/Compose, SDK generation/publication, image builds/publication,
  ARM packaging/upload and disposable storage quota enforcement.
- Independent hosted: admission bootstrap/upgrades and their contracts,
  Proxmox/Talos plans or combined hardware apply, node/lifecycle/storage
  maintenance, migration, independent etcd backup and recovery. Mac recovery
  remains available. There is no automatic paid fallback.

The prerequisite action takes explicit `packages`, `aws`, `docker` and `tailscale`
inputs. Non-Docker jobs never wait for a Docker daemon. Workflow-only changes keep
the existing affected-state selector and cannot select unrelated infrastructure.

Run the explicit ARC acceptance matrix before cutover. Preserve timestamps and
actual identities to prove overlapping light/checks jobs and inspect simultaneous
Kueue reservations including scratch. Completion requires all remaining OpenSpec
runtime scenarios, not only these probes. GitHub's [24-hour self-hosted queue
limit](https://docs.github.com/en/enterprise-cloud%40latest/actions/reference/limits)
requires an independent full-duration expiry observation, external monitoring and
cleanup; cancelling a job proves only cancellation. Keep CI_EXECUTOR unset until
acceptance passes, and retain the temporary Actions budget until ordinary workflow
execution has been verified on Talos.
