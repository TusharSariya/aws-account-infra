# Authorized Agent NAS with Versioned S3 Recovery

> Deferred as of 2026-09-12: the active Proxmox build now has two Talos VMs and worker-local storage. This document preserves the earlier NAS proposal for possible future use; it is not an implementation requirement. See [the current plan](talos-kubernetes-rebuild.md).

## Status

Proposed design. This document does not authorize deployment or live infrastructure changes.

## Summary

Create a dedicated Debian 13 NAS VM on Proxmox instead of using a host partition or TrueNAS VM.

The design provides:

- A 1 TiB XFS data disk with project quotas.
- SMB3 access for authenticated trusted-LAN users.
- Isolated NFSv4 workspace mounts for Kubernetes agents.
- An authenticated MCP and file API for sensitive datasets and audited operations.
- Authentik for human and machine authentication.
- OpenFGA for user, agent, project, workspace, dataset, and artifact relationships.
- Kyverno for Kubernetes mount and workload enforcement.
- Isolated Git worktrees and pull requests instead of concurrent canonical-directory writes.
- An hourly one-way mirror to versioned S3.
- Ninety-day retention for noncurrent S3 versions, without Object Lock.

OpenFGA is selected over Cedar and OPA for resource relationships. Kyverno remains responsible for Kubernetes admission policy. Neither Cedar nor OPA is required for the initial implementation. OpenFGA answers relationship questions such as whether a particular agent may edit a particular workspace. See [OpenFGA concepts](https://openfga.dev/docs/concepts).

## Architecture and capacity

### Proxmox allocation

Revise the Talos VM allocation as follows:

| VM | vCPU | RAM | Disks |
|---|---:|---:|---|
| `talos-cp-01` | 2 | 4 GiB | 100 GiB |
| `talos-worker-01` | 16 | 64 GiB | 200 GiB |
| `talos-sandbox-01` | 20 | 80 GiB | 200 GiB |
| `agent-nas-01` | 2 | 8 GiB | 32 GiB OS plus 1 TiB data |

This exposes 40 guest vCPUs and 156 GiB of the server's last-observed 24 physical cores, 48 SMT threads, and 188 GiB usable memory. Guest affinity leaves eight logical CPUs representing four complete physical cores unassigned, split across the two NUMA nodes, while Proxmox retains 32 GiB of unassigned memory. The NAS receives two visible vCPUs so file serving and maintenance can run concurrently, but its aggregate CPU quota should initially be one host logical CPU with a lower CPU weight than the control plane. SMT siblings do not provide the throughput of independent physical cores.

The vCPU counts are configurable scheduling limits, not permanent hardware partitions. Assign every guest complete physical-core sibling pairs, place the control plane, trusted worker, and NAS within one NUMA locality, and place the sandbox worker within the other without sharing a physical core across the sandbox and trusted boundary. Exact affinity follows the observed `lscpu -e` sibling map. VM memory remains fixed and memory ballooning stays disabled so Kubernetes observes stable node capacity. Resize VMs during a planned shutdown after reviewing utilization and NUMA placement.

The two-core, 4 GiB control plane uses Talos's documented minimum core count and recommended memory allocation. It is intentionally below the four-core production recommendation for this small cluster. Increase it if API-server latency, etcd latency, CPU saturation, or memory pressure indicates a need. One control-plane core is below the documented minimum. See [Talos system requirements](https://docs.siderolabs.com/talos/v1.13/getting-started/system-requirements).

The virtual disks consume approximately 1,556 GiB of the last-observed 1.75 TiB thin pool and leave about 236 GiB unallocated. Capacity must be reconfirmed when Proxmox becomes reachable.

The NAS data disk will:

- Use raw LVM-thin storage and VirtIO SCSI.
- Keep discard disabled.
- Use XFS with project quotas.
- Limit aggregate directory quotas to 800 GiB.
- Reserve remaining filesystem and thin-pool capacity for metadata, recovery, and growth.
- Alert at 70%, 80%, and 90% thin-pool utilization.

### NAS layout

```text
/srv/agent-nas/
├── projects/       Canonical project metadata and read-only Git mirrors
├── workspaces/     One isolated directory per agent run
├── datasets/       Controlled datasets; sensitive entries are API-only
├── artifacts/      Per-run output and explicitly published artifacts
├── scratch/        Disposable, quota-limited, never mirrored
└── control/        ACL manifests, backup allowlist, and recovery metadata
```

Defaults:

- Workspace quota: 20 GiB.
- Maximum workspace quota without administrator approval: 100 GiB.
- Scratch retention: seven days.
- Completed workspace retention: seven days after pull request creation.
- Dataset and artifact quotas are declared individually.
- Only catalog entries with `backup_enabled: true` enter the S3 mirror.

### Network exposure

- SMB TCP 445: trusted LAN and approved tailnet users only.
- NFSv4 TCP 2049: Talos worker IPs only.
- NAS administration: Tailscale SSH only.
- Workspace-agent control endpoint: mTLS from the broker only.
- Outbound HTTPS: Authentik, GitHub, AWS APIs, and package repositories.
- No SMB guest access, SMB1, NFSv3, FTP, or direct public exposure.
- Sensitive datasets are never exported through SMB or NFS.

## Identity, authorization, and write isolation

### Identity sources

Authentik will be the OIDC issuer:

- Humans authenticate through the Authentik authorization-code flow with PKCE.
- Local CLI and MCP agents use device authorization or short-lived machine tokens.
- Kubernetes agents exchange projected service-account JWTs for Authentik tokens.
- Tokens use stable subject identifiers rather than email addresses.
- Access tokens expire after 15 minutes.
- Agent-run authorization expires after at most eight hours.
- Refresh tokens are not issued to Kubernetes workloads.

Authentik supports exchanging projected Kubernetes service-account tokens through its machine-authentication flow. See [Authentik machine authentication](https://docs.goauthentik.io/add-secure-apps/providers/oauth2/machine_to_machine).

Deploy Authentik, OpenFGA, and the broker on `talos-worker-01`. Use a separately managed single-instance CloudNativePG cluster with separate databases and roles for:

- Authentik.
- OpenFGA.
- Workspace broker state.

Database dumps are written to an allowlisted NAS backup directory and mirrored to S3. Authentik identifies PostgreSQL as its essential recovery asset. See [Authentik backup guidance](https://docs.goauthentik.io/sys-mgmt/ops/backup-restore).

### OpenFGA model

Model these resource types:

- `user`
- `agent`
- `group`
- `project`
- `run`
- `workspace`
- `dataset`
- `artifact`

Relations and implied permissions:

| Resource | Relations |
|---|---|
| Group | member |
| Project | owner, maintainer, viewer |
| Run | initiator, executor |
| Workspace | project, run, owner, writer, reader, publisher |
| Dataset | steward, reader |
| Artifact | producer, publisher, viewer |

Rules:

- Project owners inherit maintain and publish rights.
- Maintainers may start agent runs and publish results.
- An agent receives write access only to the workspace assigned to its active run.
- Each workspace has one active writer run.
- Other agents receive no access unless explicitly assigned as readers.
- Dataset access is read-only unless the subject is a data steward.
- Sensitive datasets require API access even when OpenFGA grants read permission.
- Agents cannot delegate access or publish directly.
- A run delegation has a maximum eight-hour lifetime.
- Every API authorization check supplies the current time and fails closed if the grant has expired.

OpenFGA is not exposed to users or agents. Only the broker may query or modify its store.

### Workspace broker

Implement a statically linked Go service with:

- OIDC validation against Authentik.
- Kubernetes service-account token exchange.
- OpenFGA checks.
- Git workspace creation and cleanup.
- NAS workspace-agent communication over mTLS.
- REST and MCP interfaces.
- Structured audit events and Prometheus metrics.

Public REST interface:

```text
POST   /v1/runs
GET    /v1/runs/{run_id}
DELETE /v1/runs/{run_id}
POST   /v1/runs/{run_id}/publish

GET    /v1/resources
GET    /v1/resources/{resource_id}
POST   /v1/resources/{resource_id}/grants
DELETE /v1/resources/{resource_id}/grants/{grant_id}

GET    /v1/files/{resource_id}/{path}
PUT    /v1/files/{resource_id}/{path}
PATCH  /v1/files/{resource_id}/{path}
GET    /v1/files/{resource_id}/search
```

MCP tools:

```text
workspace_list
workspace_create_run
workspace_status
workspace_read
workspace_write
workspace_patch
workspace_search
workspace_publish
workspace_close
```

All file paths are relative to an authorized resource root. The broker must reject absolute paths, traversal, magic links, and symlink escapes.

### Git workflow

When a run begins:

1. Authorize the initiating user and agent.
2. Create `/srv/agent-nas/workspaces/<run-id>`.
3. Create branch `agent/<agent-id>/<run-id>` from the requested base revision.
4. Assign the run's exclusive writer identity and quota.
5. Expose only that workspace to the assigned agent.

When publishing:

1. Verify the run still has publish delegation.
2. Validate the worktree and requested base.
3. Commit only explicitly selected changes.
4. Push the run branch using a short-lived GitHub App installation token.
5. Open a pull request.
6. Remove write access immediately.
7. Retain the workspace read-only for seven days, then delete it.

Canonical branches remain protected. Agents never write directly to them.

### Filesystem enforcement

Humans:

- Receive individual Samba accounts mapped to stable Authentik subjects.
- Set or rotate a separate SMB app password through the broker.
- Access only shares permitted by reconciled POSIX and Samba ACLs.
- Never receive administrator or guest access.

Kubernetes agents:

- Use NFSv4 through the GA NFS CSI driver.
- Receive one statically bound workspace volume per authorized run.
- Use a unique assigned UID and GID.
- Run under `root_squash`.
- Cannot request arbitrary NFS paths or dynamic tenant PVCs.
- Lose the PVC, mount authorization, and filesystem ACL when the run expires.

The official [NFS CSI driver](https://github.com/kubernetes-csi/csi-driver-nfs) supports existing NFSv4 servers and dynamically or statically provisioned volumes.

Kyverno will enforce:

- Only the broker service account may create agent NAS PVs and PVCs.
- Pods may mount only a workspace claim carrying their run and service-account identity.
- The assigned UID, GID, node selector, RuntimeClass, and namespace must match the grant.
- Sandbox agents continue to require gVisor.
- Sensitive dataset mounts are rejected.
- Privileged pods, host namespaces, and unauthorized host paths remain rejected.

The NAS workspace agent applies only typed operations: create resource directory, set quota, reconcile ACL, add or revoke export, freeze workspace, and remove expired workspace. It cannot execute arbitrary broker-supplied shell commands.

### Failure behavior

- Authentik unavailable: no new login or token exchange; existing filesystem sessions continue until expiry.
- OpenFGA unavailable: API requests and new grants fail closed; last-reconciled filesystem ACLs remain.
- Broker unavailable: existing mounts remain until their lease expiry; no new workspace or publish operation.
- Reconciliation drift: remove unauthorized access, preserve data, and alert.
- Revocation: deny API access immediately, remove ACLs and mounts, disconnect affected SMB sessions, and terminate the corresponding workload.

## Catalog and infrastructure interfaces

### Storage catalog

Add a versioned storage-resource schema integrated with the existing catalog. Static project and dataset declarations contain:

```yaml
version: 1
resources:
  - id: example
    kind: project
    owner: authentik-subject-id
    quota_gib: 20
    access_mode: hybrid
    sensitivity: standard
    backup_enabled: true
    repository: TusharSariyaOrg/example
```

Allowed values:

- `kind`: `project`, `dataset`, or `artifact`.
- `access_mode`: `mounted`, `api`, or `hybrid`.
- `sensitivity`: `standard` or `sensitive`.
- `backup_enabled`: boolean.
- `quota_gib`: 1 through 1000.

Dynamic runs, workspaces, delegations, and grant expiry remain broker state, not Git-managed catalog data.

Extend the Kubernetes cluster storage contract from `tenant_pvcs_enabled: false` to an explicit mode:

```yaml
storage:
  mode: brokered
  storage_class: agent-nas
  physical_capacity: 800Gi
  default_workspace_quota: 20Gi
```

Tenant workloads remain unable to create arbitrary PVCs. The broker is the sole storage provisioner.

### Authentik configuration

Manage Authentik applications, providers, groups, scopes, and token lifetimes through declarative Authentik blueprints:

- Workspace broker OIDC application.
- Workspace MCP OAuth application.
- OpenFGA machine client.
- Kubernetes federated OIDC source.
- Administrator, maintainer, and user groups.
- Required stable-subject and Kubernetes identity claims.

### AWS infrastructure

Create an OpenTofu-managed S3 bucket named from account and region, for example:

```text
homelab-agent-nas-992382747916-us-east-1
```

Use the existing encrypted S3 module with these additions:

- S3 Versioning enabled.
- SSE-KMS with S3 Bucket Keys enabled.
- Block Public Access enabled.
- TLS-only bucket policy.
- Noncurrent versions deleted after 90 days.
- Current versions never expire.
- Incomplete multipart uploads aborted after seven days.
- Expired delete markers removed after protected versions have aged out.
- Bucket size and object-count alarms.
- No Object Lock.

Create a dedicated IAM Roles Anywhere role for `agent-nas-01` with:

- Bucket and version listing.
- Current and versioned object reads.
- Object writes.
- Ordinary `DeleteObject`, which creates delete markers.
- Multipart upload operations.
- Required KMS data-key permissions.
- No `DeleteObjectVersion`.

Add an explicit bucket-policy denial of `s3:DeleteObjectVersion` for the NAS uploader role. AWS administrators retain version-deletion authority, matching the selected policy.

Do not reuse the repository's existing long-lived RAG IAM user pattern. The NAS uses short-lived Roles Anywhere credentials only.

Any live credential, certificate, app password, token, or secret implementation must first load the required `aws-secrets-manager` skill and use `asm-exec` runtime resolution. No secret may enter Git, Terraform output, process arguments, logs, diffs, or agent context.

## S3 mirror and recovery

Run a root-owned, low-priority systemd mirror service on `agent-nas-01`:

- Every hour, mirror only `backup_enabled` catalog resources.
- Run `aws s3 sync --delete` separately for each resource prefix.
- Serialize jobs with a lock.
- Use low CPU and I/O scheduling priority.
- Skip or postpone during RAID rebuild, patrol read, or consistency check.
- Retry transient AWS failures with bounded backoff.
- Record last successful mirror time, file count, bytes, and failures.
- Perform a full reconciliation every night.
- Alert after two consecutive hourly failures.

S3 layout:

```text
s3://<bucket>/mirror/v1/projects/<resource-id>/
s3://<bucket>/mirror/v1/datasets/<resource-id>/
s3://<bucket>/mirror/v1/artifacts/<resource-id>/
s3://<bucket>/control/acl-manifests/
s3://<bucket>/control/catalog/
s3://<bucket>/control/database-dumps/
```

The control prefix stores:

- Storage catalog revision.
- OpenFGA model version and tuple export.
- POSIX and Samba ACL manifests.
- Quota assignments.
- Authentik, OpenFGA, and broker database dumps.
- Mirror run manifests.

Implement a restore command:

```text
nas-restore --resource <id> [--at <timestamp>] --destination <path>
```

It will:

- Restore the current version by default.
- For `--at`, select the latest object version at or before the requested timestamp.
- Respect delete markers.
- Restore data into a new directory instead of overwriting the source.
- Verify object checksums.
- Reapply quotas and ACLs only after operator approval.
- Never restore secrets from ordinary file mirrors.

S3 Versioning preserves earlier versions when a mirror overwrites an object or creates a delete marker. See [S3 Versioning behavior](https://docs.aws.amazon.com/AmazonS3/latest/userguide/versioning-workflows.html).

Databases, etcd, and live application state continue to use application-native backups. They are not protected by copying live database files through the mirror.

## Rollout and testing

### Rollout sequence

1. Complete the ServeRAID passive baseline, patrol read, and consistency check.
2. Reconfirm LVM-thin capacity and reserve the NAS IP.
3. Create the NAS VM, XFS filesystem, quotas, firewall, and monitoring.
4. Prove manually managed SMB and NFS isolation using disposable users and pods.
5. Create the S3 bucket and Roles Anywhere uploader.
6. Prove overwrite, deletion, 90-day lifecycle configuration, and point-in-time restore.
7. Deploy CloudNativePG, Authentik, and OpenFGA.
8. Deploy the broker and NAS workspace agent.
9. Enable OpenFGA checks and ACL reconciliation in audit mode.
10. Enable Kyverno mount enforcement.
11. Enable Git worktree and pull-request publishing.
12. Enable the sensitive file API and MCP interface.
13. Migrate agent workspaces gradually; leave local-path storage available for disposable cluster state.

### Acceptance tests

- Two agents assigned to the same project receive different writable workspaces.
- Neither agent can read or modify the other workspace.
- An agent cannot mount an undeclared NAS path.
- A sandbox pod cannot bypass its UID, gVisor, node, namespace, or PVC restrictions.
- Sensitive datasets cannot be mounted through SMB or NFS.
- OpenFGA grants and revocations produce matching ACL and mount changes.
- Revocation blocks API access immediately and removes mounted access.
- OpenFGA or Authentik outage does not silently grant access.
- A broker outage does not corrupt existing files.
- Publishing creates a branch and pull request without modifying the canonical branch.
- An hourly mirror overwrite creates a recoverable previous S3 version.
- A mirrored deletion creates a delete marker and remains recoverable.
- The NAS uploader cannot call `DeleteObjectVersion`.
- A full workspace is restored to a selected timestamp.
- Scratch and non-allowlisted resources never appear in S3.
- Authentik, OpenFGA, and broker databases restore into a disposable environment.
- NAS disk, quota, mirror lag, S3 size, object count, authorization failures, and reconciliation drift are visible in monitoring.
- Loss of the NAS VM is recoverable from Git, OpenTofu, Ansible, database dumps, and S3 without relying on a Proxmox snapshot.

## Assumptions

- The NAS improves sharing and recoverability but does not provide physical high availability.
- Proxmox and the NAS still share one RAID controller and one server.
- Trusted-LAN users may mount SMB; agents do not inherit unrestricted human mounts.
- Kubernetes agents use isolated NFS workspaces.
- Sensitive data uses the audited API or MCP path only.
- GitHub remains the canonical source for code.
- S3 provides a 90-day version-recovery window, not permanent archival.
- Bucket administrators may delete versions because Object Lock was explicitly declined.
- The one-hour recovery point objective applies only to allowlisted NAS resources.

## References

- [Talos system requirements](https://docs.siderolabs.com/talos/v1.13/getting-started/system-requirements)
- [OpenFGA concepts](https://openfga.dev/docs/concepts)
- [Authentik machine authentication](https://docs.goauthentik.io/add-secure-apps/providers/oauth2/machine_to_machine)
- [Authentik backup guidance](https://docs.goauthentik.io/sys-mgmt/ops/backup-restore)
- [Kubernetes NFS CSI driver](https://github.com/kubernetes-csi/csi-driver-nfs)
- [Amazon S3 Versioning behavior](https://docs.aws.amazon.com/AmazonS3/latest/userguide/versioning-workflows.html)
