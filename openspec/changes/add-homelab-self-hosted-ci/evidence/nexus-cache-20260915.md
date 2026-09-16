# Local Nexus cache implementation - staged rollout

Worktree: `/private/tmp/aws-account-infra-nexus-cache`, branch
`feat/local-nexus-cache`, baseline `ef0574f`. The original working checkout and
unfinished runner-cache worktree were not modified.

## Implemented but not deployed

- Revised pool 33.5 CPU / 150 GiB, platform reserve 4 CPU / 18 GiB and AI
  33.25 CPU / 77 GiB; pool validation reads configured values and status reads
  actual workload PodSet requests.
- OpenTofu-managed Helm cache service definitions, isolated Nexus/PostgreSQL
  Pods, restricted service security contexts, network policies and four retained
  local volumes totaling 64 GiB. Database credentials remain external Secrets.
- Existing XFS collector extension for the four cache quotas, fresh measured
  quota/retained-PV/physical-byte deployment checks, desired-service platform
  accounting and mandatory preloaded image checks.
- Removed explicit GitHub build caches and disabled setup-uv/setup-go automatic
  caching. Repository billing/cache settings have NOT been verified or changed.
- Scratch sizing/verification helper and rejection tests. No new smaller catalog
  budget has been adopted without measurements.
- Updated OpenSpec requirements/design/tasks while preserving original evidence.

These changes are a staged foundation, not a complete cache rollout. Repository
configuration, EULA application, credential enrollment, UI cleanup schedules,
ongoing alerting, prerequisite runner images, consumer routing, fallback and live
cache/job acceptance still require implementation or verification. Tasks remain
unchecked. No new service, quota or admission budget was applied.

## Actual storage gate failure

The private existing Kubernetes credential reached both Ready Talos nodes.
Initial root usage was 19.74 GiB, with 87.75664048 GiB allocatable ephemeral
storage. Pulled the pinned PostgreSQL image through the Talos image API. The
Nexus pull did not complete within approximately eight minutes and its local
client was interrupted after the capacity gate had already failed. Partial
image content can remain under containerd garbage collection; no manual blob
or image deletion was performed.

Fresh measurement at 2026-09-16T00:13:21Z is retained in
`nexus-storage-preflight-20260915.json`. Required root use plus 60 GiB scratch
plus 8 GiB headroom was 94,853,120,000 bytes against 94,227,975,217 allocatable:
a 625,144,783-byte (0.582 GiB) shortfall. This already fails before a complete
Nexus image/startup footprint. `verify_storage` rejected the live sample.
The user's plan explicitly requires failing deployment in this case.

No disk resize, cache service deployment, admission change, global CI routing
change or paid expansion was performed. A scope decision to increase the worker
OS disk through guarded infrastructure is pending. Shrinking scratch/headroom
or deleting unrelated images is not treated as implicitly authorized remediation.

## Local verification

- Both CI and application OpenTofu roots: init with backend disabled, validate pass.
- Runner catalog HCL/whole-Pod resource validation: pass.
- Kubernetes CEL admission: all 15 scenarios pass, including revised ceilings,
  restartable-init accounting, operational bypass and protected gate removal.
- 63 focused Python tests pass across AI packaging, Kueue foundation/catalog/
  contracts, storage/physical collectors, local-cache gates/sizing, and affected
  deploy-unit selection.
- Strict OpenSpec validation and `git diff --check`: pass.

These are local results, not GitHub checks or live cache acceptance.

## Source verification and authorizations

The user authorized EULA acceptance and supported UI cleanup/compaction setup
with deployment verification. Neither was exercised against a deployed Nexus.

- [CE usage limits](https://help.sonatype.com/en/usage-center.html): 40,000 components,
  100,000 requests/day; planned 75% warnings are 30,000 and 75,000.
- [Formats](https://help.sonatype.com/en/formats.html): requested proxy formats.
- [PostgreSQL configuration](https://help.sonatype.com/en/install-nexus-repository-with-a-postgresql-database.html).
- [Cleanup Policies API](https://help.sonatype.com/en/cleanup-policies-api.html): documented Pro-only API.
- [Supported cleanup and compaction](https://help.sonatype.com/en/cleanup-policies.html).
- [EULA API](https://help.sonatype.com/en/eula-rest-api.html).

Nexus and PostgreSQL image manifest digests were resolved from the authenticated
public Docker registry API. Full service startup compatibility is unverified.

## Authorized OS expansion completed (2026-09-16 UTC)

The user authorized extending the plan to increase the worker OS disk. The
100-GiB failure above remains historical evidence. The exact saved-plan guard
permitted only VM 102 scsi0 from 100 to 128 GiB; scsi1 remained 1200 GiB and the
control-plane disks were unchanged. Physical thin-pool checks passed, a private
state backup was retained, and the post-apply Proxmox plan was empty.

A graceful Talos shutdown and Proxmox start grew EPHEMERAL from 105,063,120,896
to 135,127,891,968 bytes, exactly 28 GiB. Its filesystem and partition UUIDs
were unchanged. STATE and the separate local-path data filesystem retained
their UUIDs, partition identities and sizes. The worker returned Ready, AI
remained Off, and Pi-hole answered over both UDP and TCP.

Private saved-plan/apply and restart receipts are retained under the existing
0700 credential tree in `nexus-os-grow-20260915-03` and
`nexus-os-reboot-20260915-01`. No credentials are included in this evidence.

Both pinned PostgreSQL and Nexus image manifests are now present. The fresh
2026-09-16T00:47:29Z measurement in `nexus-expanded-storage-20260915.json` passed:
112.96 GiB allocatable, approximately 24.44 GiB measured usage, 60 GiB declared
scratch and 8 GiB eviction headroom. Repeat this gate during cache deployment;
this sample is evidence, not an exemption from freshness checks.

The host physical-capacity collector was updated using the existing private
credentials and fixed reviewed installer; its source/result receipt is in
`nexus-capacity-host-20260915-02`. An earlier attempt timed out and was retried
only after fresh API/SSH health checks. The transient timeout cause is unknown.

Cache service deployment is still pending. Removing GitHub build-cache access
changed the AI workflow input hashes, so replacement image builds were started
on the compatibility Talos runners (runs 35041020930 and 35041022578). The
application deployment guard continues to require their successful verified
receipts before applying the updated collector and AI budget. Global Talos
routing remains disabled.

## Additional staging and cache billing verification

- Repository cache storage limit read back as 10 GB. Created a repository-scoped
  `actions_cache_storage` SKU budget at $0 with `prevent_further_usage=true` and
  read it back; see `github-cache-budget-20260915.json`. September usage returned
  no cache-storage SKU line items at this observation. The temporary $5 Actions
  product budget remains in place for original acceptance; no paid cache budget
  was enabled. Other default-branch workflows still require the staged workflow
  changes to merge before all remote cache access is disabled.
- Added a five-minute read-only CE/storage monitor with named ConfigMap access,
  a metrics-only Nexus credential, Kubernetes Warning Events at 80% filesystem
  usage or 75% CE limits, and explicit unavailable-telemetry reporting. This is
  staged code, not a claim that live Nexus warnings have passed.
- The cache preflight now renders Deployments, the configuration Job and monitor
  CronJob to account for whole-Pod resource requests. Fresh projected platform
  CPU was 3.706 against the 4-CPU reserve; memory also fit the 18-GiB reserve.
- Cache credentials were generated and enrolled privately in Kubernetes Secrets;
  the database, administrator, build writer and metrics reader have distinct
  passwords. No credentials were embedded in charts, source, plans or state.
- Added PostgreSQL `pg_trgm` initialization and a Nexus connection pool of 50
  against PostgreSQL's 100-connection limit, following Sonatype's installation
  requirements. Full startup still requires live verification.
- 79 focused Python tests passed after the monitoring and chart-accounting changes.

References: [usage API](https://help.sonatype.com/en/service-metrics-data-api.html),
[GitHub cache limits](https://docs.github.com/en/actions/reference/workflows-and-actions/dependency-caching),
[budget SKU identifiers](https://docs.github.com/en/billing/reference/product-and-sku-names).
