> Historical host installation guide. For the current migration use [README.md](README.md).

# Isolated pilot: monitoring before deployment

Current live results and blockers: [2026-09-21 verification](monitoring/evidence/2026-09-21.md).

This is an independent delivery path for `laptop-wifi-PROTOTYPE`, not the production
Talos manifests or AWS deployment units. Every mutation checks both the API URL and
`kube-system` UID in `monitoring/profile.json`. Existing controller units, worker
pause markers, production resources, and storage-proof volumes are not modified.
The secondary remains paused. No physical power operations are implemented here.

## Install and prove metrics and logs

Run from this checkout on `laptop-dell-studio`, or copy only `pilot/` there:

```sh
rsync -az --exclude __pycache__ pilot/ laptop-dell-studio:~/pilot-platform/
ssh laptop-dell-studio
python3 ~/pilot-platform/monitoring/install.py metrics
python3 ~/pilot-platform/monitoring/acceptance.py logs
python3 ~/pilot-platform/monitoring/measure.py
```

Python 3.12+, OpenSSL, the existing pilot kubectl/admin kubeconfig, user systemd,
and enabled user lingering are prerequisites. No sudo is required. Releases are
Linux amd64 binaries with SHA-256 locks in `monitoring/releases.json`; the installer
validates Prometheus, Loki and Alloy configuration before starting them. Units are
named `pilot-{prometheus,loki,alloy,exporter}.service`. State lives under
`~/.local/share/pilot-monitoring/`; the source and rendered configuration are copied
there. Rerunning an installation stage restarts only that stage's services.

The installer creates a separate reader client certificate valid for 30 days. Its
RBAC can read nodes, the pilot UID, and Pods/Pod logs/Kueue Workloads only in
`prototype-slot` and `pilot-app`. It can also read the three named pilot controller Deployments for health. It
cannot read Secrets, execute in Pods, change
workloads, or use the node proxy. The application metrics proxy permits only the
named `pilot-http` Service in `pilot-app`. Run the metrics installer again before
certificate expiry to renew it; there is deliberately no stored administrator
credential in a monitoring service. The existing admin kubeconfig is used only by
installation and explicit validation commands. Certificate renewal requires that
existing credential, not an automatically elevated monitoring identity.

Collection is intentionally small:

- The laptop exporter reads node readiness, worker desired/paused/observed state,
  systemd health/restarts/memory, Pod counts, and Kueue admission conditions. It
  emits aggregate admission histograms using server transition times, with a
  15-second polling gap. Very short completed-and-deleted work may be missed.
  Counters restart with the exporter; Prometheus records their history.
- Worker metrics distinguish observed Ready transitions from retirement requests.
  Neither is claimed to be a measured physical provisioning/deletion latency.
  Stale retired nodes and the intentionally paused secondary are not outage alerts.
- Alloy discovers only Pods labelled `monitoring.homelab/pilot-logs=true` in the two
  pilot namespaces. It stores only lines matching `pilot-observe TOKEN`, with a
  bounded alphanumeric/underscore/hyphen token. Do not put secrets in diagnostic
  tokens. Ordinary output and request bodies are dropped, including in opted-in
  Pods. Lifecycle journal messages are replaced with a fixed known state word;
  raw provider errors, environment values and workload payloads are not retained.
- Loki and Prometheus retain 48 hours. Loki's TSDB compactor performs retention;
  this is not an exact wall-clock deletion guarantee. No host-wide node exporter,
  production namespace logs, full Kubernetes objects or kubeconfigs are stored
  in telemetry. The HTTP application exposes a build-info metric.

All administrative listeners use loopback, including Loki gRPC and Alertmanager
(with gossip disabled). Access them through SSH:

```sh
ssh -N -L 3000:127.0.0.1:3000 -L 9090:127.0.0.1:9090 \
  -L 3100:127.0.0.1:3100 -L 9093:127.0.0.1:9093 laptop-dell-studio
```

## Budgets and the dashboard stage

| Service | MemoryMax | Data budget |
| --- | ---: | ---: |
| Prometheus | 384 MiB | 1 GB TSDB retention; 2 GiB total stop threshold |
| Loki | 384 MiB | 2 GiB stop threshold; alert at 1.5 GiB |
| Alloy | 256 MiB | 256 MiB stop threshold |
| Metadata exporter/local receiver | 96 MiB | Two receipt files, about 1 MiB each |
| Grafana | 512 MiB | 512 MiB stop threshold |
| Alertmanager | 96 MiB | 128 MiB stop threshold |

Each unit has MemoryHigh at 80% (90% for Grafana), no cgroup swap allowance, a task limit, and a
one-core CPU ceiling. The exporter checks disk usage every collection cycle and
stops only a new monitoring writer when its budget is reached or free disk falls
below 5 GiB. This is a sampled guard, not a filesystem quota: it can overshoot
between polls, and cannot enforce its guard while the exporter is down. Installation
requires at least 10 GiB free. A 512 MiB memory reserve is required throughout the
measurement. Raw daemon journals remain subject to the host's existing journald
policy; the installer does not change the shared journal limits.

`measure.py` runs the existing smoke plus 4/8/16 bursts and four Jobs for ten minutes.
It samples memory, swap counters and the four existing controllers every 15 seconds.
A failed load run, any additional swap I/O, or less than 512 MiB available prevents
progress. Inspect `measurement.json`, `bounded-load.log`, and the validation suite's
run directory. Initial install-time paging is separate from the load measurement.

Only after a passing measurement within the last 24 hours:

```sh
python3 ~/pilot-platform/monitoring/install.py dashboards
python3 ~/pilot-platform/monitoring/acceptance.py dashboards
python3 ~/pilot-platform/monitoring/acceptance.py alerts
```

Grafana provisions Prometheus/Loki sources and the Git-versioned pilot dashboard.
Its admin password is generated into the laptop-only file
`~/.local/share/pilot-monitoring/private/grafana-password` (0600); username `admin`.
The alert proof temporarily adds a Prometheus rule, reloads it, checks the local
webhook receipt, changes its expression to false, checks the resolved receipt,
and removes the temporary rule. The local
receiver deliberately stores only alert names/status, not arbitrary annotations.
This proves local delivery only; it is not an independent outage notification path.
Email awaits a recipient, SMTP endpoint and credentials. Keep supplied credentials
outside Git and add an Alertmanager email receiver only after those are available.

The alert rule tests prove paused/retired workers remain quiet and a requested,
unpaused, unavailable worker fires after 15 minutes. Useful local checks:

```sh
systemctl --user status 'pilot-*'
journalctl --user -u pilot-alloy -u pilot-exporter --since '-10 minutes'
python3 -m unittest discover -s pilot/monitoring/tests -v
uvx ruff@0.12.12 check pilot --exclude vendor
uvx ruff@0.12.12 format --check pilot --exclude vendor
```

## Argo CD capacity gate and delivery

```sh
python3 ~/pilot-platform/argocd/bootstrap.py check
# Only if the check passes:
python3 ~/pilot-platform/argocd/bootstrap.py install \
  --repository-token-file ~/.config/pilot-monitoring/github-repo-token
```

The gate requires the recent passing load measurement, then samples the sole
management node five times over one minute. It requires 2 GiB available there
(1536 MiB of Argo CD limits plus 512 MiB reserve), sufficient unrequested memory,
900m CPU headroom (650m requests plus 250m reserve), and the laptop reserve.
Failure writes `argocd-capacity.json` and makes **no cluster changes**. Capacity is
never borrowed from disposable workers. Resolve inadequate management capacity as
a separate reviewed change, then rerun the gate.

Argo CD v3.5.3 is vendored with source URLs and hashes. Its namespace-scoped,
non-HA installation is rendered by Kustomize. Only Redis, repo-server, API server
and the application controller run; Dex, ApplicationSet and notification controllers
are disabled. Every active Pod requires the control-plane label. The default
AppProject is closed, the pilot project permits only this repository and
Deployments/Services in `pilot-app`, and Kubernetes RBAC independently restricts
application writes to that namespace. CRDs are installed by the infrastructure
bootstrap, never by the application. There is no automatic sync, pruning, app
namespace creation or public ingress. Bootstrap may report an application source
error until the reviewed manifest exists on main; it does not deploy local files
behind Git's back. This GitHub repository is private. Bootstrap requires a 0600
file containing a fine-grained token scoped to this repository with Contents read
access; it sends that credential directly to an Argo repository Secret, never into
Git or a command argument. Supply this only when the capacity gate is eligible.
Missing credentials block bootstrap before cluster changes. Application Secrets
and image-pull credentials are separate from this infrastructure Git identity.

The tiny HTTP application under `application/` is only an evaluation fixture. Its
workflow tests the container on pull requests. A manual run on main publishes to
`ghcr.io/tusharsariyaorg/pilot-http` and emits an immutable `image.json` artifact.
No workflow has a cluster kubeconfig. There is intentionally no invented digest in
the initial `image.json`: rendering refuses it until an actual build is selected.
Make the package readable by the pilot before deployment (public for this
non-sensitive fixture, or separately provision a restricted pull identity).

1. Review and merge these delivery files; dispatch `pilot-http` on main.
2. Copy the workflow's image selection into `pilot/application/image.json`.
3. Run `python3 pilot/application/render.py`; review/merge both the selection and
   `manifests/app.json`. The selected digest must change through Git.
4. Manually sync `pilot-http` without prune. Check `Synced` and `Healthy`, the
   `/healthz` response, `pilot_http_build_info` in Prometheus and the start marker
   in Loki. Application Pods use disposable workers and may wait for available
   primary capacity. This stage does not invent a new Deployment wake policy.
5. Build/select a second image through another reviewed change, then prove rollback
   with `git revert` of that selection commit, merge it, and manually sync again.
   Confirm the old digest, response and build-info metric. Record the commit SHAs
   and Argo operation results. Do not substitute `kubectl set image` or Argo's
   imperative rollback for this Git-revert acceptance test.

For temporary Argo access, forward its Service to loopback on the laptop with the
pilot kubeconfig, then forward that laptop port over SSH. No routine browser
access is enabled before private HTTPS/certificate management is designed.

Private HTTPS, secret delivery, fresh-volume replacement persistence, application
quotas/NetworkPolicies/lifecycle policy, and automatic sync remain later work.
Production migration, additional hardware, physical shutdown, backups/restore,
redundancy, tracing, service mesh and advanced rollout tooling are outside this
pilot change. Existing retained storage-proof data is never an application volume.

Upstream references used for configuration: [Loki retention](https://grafana.com/docs/loki/latest/operations/storage/retention/),
[Alloy Kubernetes logs](https://grafana.com/docs/alloy/latest/reference/components/loki/loki.source.kubernetes/),
[Alloy journal source](https://grafana.com/docs/alloy/latest/reference/components/loki/loki.source.journal/),
[Argo CD installation](https://argo-cd.readthedocs.io/en/stable/operator-manual/installation/),
and [restricted projects](https://argo-cd.readthedocs.io/en/stable/user-guide/projects/).
