# Seven-Day WAN Partition Resilience

## Status

Proposed design. This document does not authorize deployment, migration, or
live credential operations. Revalidate component versions and compatibility
against official documentation before apply.

## Summary

Make the home site the authoritative runtime failure domain:

- Run the application database locally with CloudNativePG.
- Retire Supabase as a runtime dependency after migration.
- Keep ECR as the build and provenance registry, but run workloads from a local
  OCI mirror.
- Materialize AWS secrets into retained Kubernetes Secrets before an outage.
- Keep local DNS, time, authentication, authorization, monitoring, images, and
  database backups functional for seven disconnected days.
- Support serving and restarting existing releases during an outage. New
  deployments and full cluster rebuilds wait for connectivity.

This avoids split-brain by retaining exactly one writable database primary.
The cloud never accepts parallel writes. If the local network later splits,
the database favors consistency: only a safe primary or quorum may write; an
isolated minority becomes unavailable.

Supabase read replicas are not sufficient because they are asynchronous,
read-only, cloud-hosted, and do not provide offline Auth, Storage, or Realtime.
See [Supabase read
replicas](https://supabase.com/docs/guides/platform/read-replicas).

## Architecture changes

### Local database authority

- Deploy a single-instance CloudNativePG cluster on `talos-worker-01`, backed
  by local POSIX storage rather than NFS.
- Use separate databases and roles for applications, Authentik, OpenFGA, and
  the workspace broker.
- Move KEDA's PostgreSQL scaler DSN and application database connections to
  cluster-local services.
- Replace direct Supabase REST or service-role access with direct server-side
  PostgreSQL access or a local authenticated API. Browsers never connect
  directly to PostgreSQL.
- Use Authentik for user authentication. Migrate any Supabase Auth users
  through password-reset enrollment rather than attempting to export password
  material.
- Pause internet-dependent ingestion jobs during a partition while preserving
  their local queue and completed data.

Do not add PostgreSQL replicas on the current single physical server merely to
claim high availability. They would share the same RAID, host, power, and
network failure domain.

When three independent physical failure domains become available, expand to
three CloudNativePG instances with:

- One writable primary and two standbys.
- Synchronous replication using `ANY 1`.
- `dataDurability: required`.
- CloudNativePG quorum-based failover enabled.
- Hard topology anti-affinity across physical hosts.
- No forced promotion when quorum safety cannot be proven.

CloudNativePG's quorum failover is designed to refuse promotion when a
partition may have isolated the replica holding acknowledged writes. See
[CloudNativePG automated
failover](https://cloudnative-pg.io/docs/1.28/failover/).

### Supabase migration

1. Inventory schemas, extensions, functions, RLS policies, triggers, Auth
   users, and direct REST or Realtime dependencies.
2. Provision matching local PostgreSQL schemas through migrations committed to
   the application repository.
3. Restore a Supabase backup into local PostgreSQL.
4. Configure one-way logical replication from Supabase to the local subscriber
   and monitor LSN lag.
5. Enter a maintenance window and reject new Supabase writes.
6. Wait for replication to reach the final source LSN, then compare row counts,
   constraints, representative checksums, and application queries.
7. Disable the subscription and switch applications and KEDA to local
   endpoints.
8. Resume writes locally. From this point, rollback to Supabase is prohibited
   without a new forward migration because Supabase is no longer current.
9. Retain the Supabase project without writes for 30 days, then archive or
   remove it after local restore exercises pass.

### Local OCI registry

- Run a lightweight OCI registry such as zot directly under systemd on
  `agent-nas-01`, outside Kubernetes, avoiding a registry bootstrap loop.
- Store registry data on NAS XFS with a quota equal to the greater of 100 GiB
  or 2.5 times the compressed allowlisted image set.
- Use an internal TLS certificate and a read-only node credential that grants
  no ECR or registry-push authority.
- Permit pushes only from the NAS mirror process.
- Configure Talos/containerd and the Ubuntu GPU worker to pull runtime images
  from the local registry.
- Pin every image by digest and use `imagePullPolicy: IfNotPresent`.
- Mirror application, controller, CNI, CSI, Gateway, policy, observability,
  database, and pause images before enabling a release.
- Preserve at least the current and previous known-good digest for each image.
- Pre-pull partition-critical images onto every eligible node as a second line
  of protection.

ECR remains the upstream publication and provenance store. A NAS systemd job
uses IAM Roles Anywhere only while connected, obtains ECR authorization at
runtime, and copies allowlisted digests plus OCI signatures and attestations
into the local registry. No long-lived AWS access key is introduced.

A release is eligible for deployment only after its digest and verification
artifacts exist locally. Kubernetes documents that digest-pinned images with
`IfNotPresent` can restart from local cache without contacting the upstream
registry. See [Kubernetes image
behavior](https://kubernetes.io/docs/concepts/containers/images/).

### Secrets and identity

- Keep AWS Secrets Manager authoritative for rotation and connected-state
  recovery.
- Configure partition-critical `ExternalSecret` resources with periodic
  refresh, `creationPolicy: Orphan`, and `deletionPolicy: Retain`.
- Do not delete a usable local Secret merely because AWS, Roles Anywhere, or
  ESO refresh is unavailable.
- Encrypt Kubernetes Secrets in etcd and restrict access through RBAC.
- Ensure database, registry, internal TLS, Authentik, OpenFGA, and broker
  credentials remain valid for longer than the seven-day window.
- Alert at least 21 days before a required certificate expires.
- Treat AWS session credentials as unavailable during a partition. Runtime
  service paths must not depend on cached STS credentials.
- Preserve offline Talos, Kubernetes, PKI, and database break-glass material
  outside Git for disaster recovery, but do not promise a full offline rebuild.

External Secrets can retain the target Secret while refresh fails; its
lifecycle policies must be tested against deletion and GitOps recreation. See
the [External Secrets lifecycle](https://external-secrets.io/main/api/externalsecret/).

Any implementation involving live certificates, credentials, passwords, or
secret values must first load the repository-required `aws-secrets-manager`
skill and use `asm-exec`. Values must never enter Git, command arguments, logs,
diffs, Terraform output, or agent context.

### Local backup buffer

- Install Barman on `agent-nas-01`.
- Give Barman dedicated least-privilege backup and streaming roles in
  PostgreSQL.
- Stream WAL asynchronously from CloudNativePG to Barman and take daily base
  backups.
- Retain at least eight days locally, providing one day of safety beyond the
  partition objective.
- Size the backup quota as two full database backups plus eight days of
  measured peak WAL generation plus 20% headroom.
- Keep Barman locks and backup data on the NAS XFS filesystem.
- Mirror completed and checksum-verified Barman backups to a dedicated S3
  prefix when connectivity exists.
- Never delete the local backup because an upload merely started; delete only
  after remote verification and retention eligibility.
- After reconnection, upload the backlog oldest-first with bounded bandwidth
  and retry.

Barman supports streaming WAL collection and `pg_basebackup`-based backups
without copying live database files. See the [Barman backup
documentation](https://docs.pgbarman.org/release/3.18.0/user_guide/backup.html).

### Local infrastructure dependencies

- Keep the homelab DNS zone authoritative locally. Add static Talos host
  entries for the NAS registry and other bootstrap-critical endpoints.
- Run a local time source on Proxmox or the NAS and point Talos, Kubernetes,
  and NAS services at it.
- Keep LAN application endpoints independent of Cloudflare Tunnel and public
  DNS.
- Authentik, OpenFGA, PostgreSQL, registry, monitoring, NAS, and broker
  endpoints remain LAN-local.
- Argo CD retains the last applied state but freezes deployments while GitHub
  is unreachable.
- Alertmanager continues local evaluation. An external dead-man monitor sends
  email when the home heartbeat disappears; local dashboards show detailed
  partition state.
- Buffer NAS S3 mirrors, database backups, and other cloud uploads locally and
  drain them after reconnection.

## Declarative interfaces and enforcement

Extend the cluster catalog with a continuity contract:

```yaml
continuity:
  partition_scope: wan
  offline_window: 168h
  offline_operations: serve-and-restart
  runtime_registry: registry.homelab.tfdraw.dev
  image_policy: mirrored-digest
```

Extend each Kubernetes service declaration with:

```yaml
continuity:
  wan_partition: serve
```

Allowed service behaviors:

- `serve`: all runtime dependencies are local and the release can restart
  offline.
- `read-only`: local reads remain available while mutations are rejected.
- `suspend`: the controller or job stops cleanly because its purpose requires
  the internet.

Enforcement must:

- Reject `serve` services that reference hosted Supabase, direct ECR image
  names, mutable tags, unmirrored digests, or partition-critical external DNS
  dependencies.
- Require a retained local Secret contract for every `serve` service secret.
- Require local readiness probes that do not call cloud services.
- Require explicit egress declarations and identify which egress loss triggers
  degraded or suspended behavior.
- Render a partition-critical workload inventory for image prefetching,
  restart tests, monitoring, and capacity calculations.

Initial classifications:

- PostgreSQL, Authentik, OpenFGA, broker, registry, DNS, NAS, Prometheus,
  Grafana, Loki, and internal ingress: `serve`.
- Internet harvesters, AWS uploaders, Cloudflare Tunnel, email delivery, and
  external synthetic probes: `suspend`.
- Applications with a proven local cache but no local write path: `read-only`.

## Failure behavior

| Failure | Expected behavior |
|---|---|
| Internet, AWS, ECR, GitHub, and Supabase unavailable | Local services continue; cloud sync, deploys, ingestion, email delivery, and uploads pause |
| Existing pod restarts | It pulls from node cache or the local registry and mounts the retained local Secret |
| Worker VM restarts | Talos rejoins locally and retrieves required images without AWS |
| ESO or Roles Anywhere unavailable | Existing Secrets remain; refresh alerts fire; no Secret is deleted |
| NAS unavailable | Database continues on local storage; cached critical images permit restarts; registry and backup lag alert locally |
| Local PostgreSQL pod fails | Kubernetes restarts it on its existing local PV; the application is unavailable during restart |
| Supabase becomes reachable again | No writes return to Supabase; local PostgreSQL remains authoritative |
| WAN reconnects | Image, backup, and S3 queues drain with verification and bounded load |
| LAN partition isolates the database | No second writer is promoted; the isolated service becomes unavailable |
| Proxmox host or RAID fails | Local service is unavailable; recovery uses verified off-site backups after connectivity and hardware return |

This design tolerates a WAN partition, not loss of the single physical server.
Adding VMs on that server does not change the physical failure domain.

## Rollout

1. Measure the current database size, daily WAL volume, complete image set,
   Secret refresh behavior, DNS dependencies, and seven-day local storage
   requirement.
2. Deploy the local registry and prove digest mirroring, signature
   preservation, node authentication, garbage-collection safety, and restart
   from an empty node cache.
3. Deploy CloudNativePG and Barman, then prove local point-in-time recovery
   without AWS.
4. Migrate Supabase into CloudNativePG using the one-way cutover procedure and
   remove all runtime Supabase endpoints and service-role keys.
5. Move KEDA and application database connections to local services.
6. Apply continuity schema validation and classify every workload.
7. Configure retained ESO Secrets and prove that provider failure never removes
   a usable Secret.
8. Simulate a WAN partition by blocking all non-LAN traffic at the router or
   test firewall while preserving the LAN.
9. During the partition:
   - Restart every `serve` workload.
   - Restart each worker VM individually.
   - Delete one critical image from a worker cache and prove retrieval from the
     NAS registry.
   - Expire cached AWS sessions and prove no local runtime path depends on them.
   - Perform local database writes and reads.
   - Restore PostgreSQL to a timestamp using only local Barman data.
   - Verify internet-dependent jobs suspend without data corruption or retry
     storms.
10. Run a full 168-hour partition soak while recording database integrity,
    image availability, secret staleness, clock drift, registry capacity, WAL
    growth, and local alerts.
11. Restore WAN connectivity and verify ordered backlog upload, S3 checksums,
    ESO refresh, registry reconciliation, alert recovery, and absence of any
    Supabase writes.
12. Repeat the partition test quarterly and after database, registry, identity,
    CNI, or secret-controller upgrades.

## Acceptance tests

- Every `serve` workload can restart without internet.
- No runtime image pull contacts ECR.
- No critical Secret disappears or expires during seven days.
- Local writes remain consistent and no cloud copy accepts writes.
- PostgreSQL restores locally to a selected timestamp.
- Buffered backups and mirrors upload after reconnection without overwriting
  newer data.
- An internal LAN partition never produces two writable primaries.
- The external dead-man path sends email when the home site stops reporting.

## Assumptions

- The protected event is a WAN outage while Proxmox, the LAN, NAS, and
  Kubernetes nodes remain mutually reachable.
- The required disconnected window is seven days.
- Existing services must serve and restart; new deployments and full offline
  rebuilds are out of scope.
- Local PostgreSQL is authoritative after cutover.
- Supabase runtime APIs, Auth, Realtime, and Storage are retired.
- Remote users normally access the home-hosted service through approved tunnel
  or tailnet paths.
- During a WAN outage, remote access is unavailable unless an independent
  network path exists.
- Consistency is preferred over write availability during an internal network
  split.
- One physical server cannot provide host, RAID, power, switch, or site high
  availability.

## References

- [Supabase read replicas](https://supabase.com/docs/guides/platform/read-replicas)
- [Supabase database replication](https://supabase.com/docs/guides/database/replication)
- [CloudNativePG automated failover](https://cloudnative-pg.io/docs/1.28/failover/)
- [PostgreSQL high availability and replication](https://www.postgresql.org/docs/current/high-availability.html)
- [Kubernetes images](https://kubernetes.io/docs/concepts/containers/images/)
- [External Secrets lifecycle](https://external-secrets.io/main/api/externalsecret/)
- [Barman backups](https://docs.pgbarman.org/release/3.18.0/user_guide/backup.html)
- [zot OCI registry](https://github.com/project-zot/zot)
