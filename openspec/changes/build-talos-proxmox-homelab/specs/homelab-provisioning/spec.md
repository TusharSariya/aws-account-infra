## Purpose

Defines observable safety, reproducibility, trust-boundary, evidence, and recovery behavior for provisioning the Proxmox-hosted Talos cluster and worker-local storage.

## ADDED Requirements

### Requirement: Completed operations have reproducible recovery paths
Every completed provisioning operation SHALL have versioned desired state and repeatable automation, or an exact manual procedure where hardware or console interaction is necessary. Its recovery record SHALL identify prerequisite artifacts, dependencies, secret recovery or reissuance, and a verification method. Full disaster recovery SHALL include the administrator environment, laptop network, Proxmox host, guests, cluster and accepted durable data. Recovery-critical material SHALL be available off-site independently of the homelab, with explicit recovery-time and data-loss objectives.

#### Scenario: A completed operation is audited for reconstruction
- **WHEN** an operator needs to repeat a completed step after losing its original machine
- **THEN** the preserved recovery inputs and procedure identify how to reconstruct and verify the intended state without conversation history, an untracked checkout, or inaccessible host-local files

#### Scenario: Network bootstrap is recovered
- **WHEN** the laptop providing Proxmox network access is lost
- **THEN** the operator can establish replacement administration access and recreate the gateway, DHCP exclusions and reservations from independently available inputs without first reaching Proxmox through the lost laptop

#### Scenario: Sensitive recovery material is required
- **WHEN** rebuilding requires an administrator credential, private key, vault password or cluster secret
- **THEN** a verified encrypted off-site recovery or reissuance path exists and its access does not depend solely on the failed platform

#### Scenario: Full disaster recovery is declared ready
- **WHEN** the platform is accepted as recoverable after total homelab loss
- **THEN** an isolated rehearsal from a clean administration environment has exercised the dependency-ordered rebuild and data restore, measured achieved recovery time and data loss against the declared objectives, and recorded any unresolved blocker

### Requirement: Installation artifacts are pinned and attributable
The provisioning record SHALL identify every operating-system artifact by upstream source, exact version, architecture, image type, and locally computed digest. Each custom Talos artifact SHALL also record its Image Factory schematic ID, selected extensions, and matching installer image reference.

#### Scenario: Talos artifacts are accepted
- **WHEN** a Talos ISO is made available in Proxmox storage
- **THEN** the record identifies Talos v1.13.9, amd64, the official Image Factory URL, the schematic ID, the local digest, and the matching installer image reference

### Requirement: Host readiness gates guest creation
The provisioning workflow SHALL prevent guest creation until the operator records the Proxmox configuration export, RAID level and cache-protection state, physical disk health, thin-pool capacity, firmware state, virtualization settings, network bridge state, and the decision on SMT.

#### Scenario: Preflight evidence is incomplete
- **WHEN** any required host-readiness result is absent or reports an unresolved unsafe condition
- **THEN** VM-creation tasks remain incomplete and the implementation log identifies the blocking condition

#### Scenario: Storage capacity is confirmed
- **WHEN** the operator is ready to allocate VM disks
- **THEN** the recorded observed capacity demonstrates that the planned allocations retain host and thin-pool recovery headroom

#### Scenario: SMT-enabled topology is accepted
- **WHEN** the operator elects to retain SMT for additional compute throughput
- **THEN** the record verifies 24 physical cores, 48 online logical CPUs, two threads per core, two NUMA nodes, VT-x, active VT-d or IOMMU translation, and zero corrected or uncorrected EDAC errors

### Requirement: VM topology matches the simplified capacity and isolation contract
The topology SHALL contain one non-workload Talos control-plane VM with 2 vCPUs, 4 GiB RAM and a 100-GiB OS disk, and one shared Talos worker with 38 vCPUs, 172 GiB RAM, a 100-GiB OS disk and a separate 1,200-GiB data disk. Total configured guest RAM SHALL NOT exceed 176 GiB on the observed 188-GiB host. There SHALL be no dedicated NAS or sandbox VM. The system SHALL NOT claim physical high availability, exclusive CPU cores or separate VM isolation for workloads sharing the worker. CPU/NUMA tuning is deferred.

#### Scenario: Configurations are statically validated
- **WHEN** the two-VM desired state and generated Talos configuration are checked
- **THEN** capacity, identities, install/data disk separation, startup order, Talos/Kubernetes pins, matching ISO/installer schematics, labels, taints and Git secret exclusions match the approved inputs

#### Scenario: Node extensions are inspected
- **WHEN** the two Talos nodes are enumerated
- **THEN** both have QEMU Guest Agent, only the worker has gVisor, and application scheduling is disabled on the control plane

#### Scenario: Workloads share the worker
- **WHEN** trusted services and sandbox workloads are deployed
- **THEN** both can schedule on the shared worker, while sandbox namespaces require gVisor, restricted privileges, worker placement, resource limits and explicit network policy

#### Scenario: Worker storage is recovered
- **WHEN** the worker VM or host is lost
- **THEN** versioned configuration reconstructs the worker and its separate local data volume, and independently retained application-consistent backups restore accepted durable data without relying on a NAS VM or the failed worker

### Requirement: Provisioning actions have an append-only audit record
Every performed manual or automated provisioning action SHALL add a timestamped implementation-log entry containing the operator, target, intended action, commands or UI operation, result, sanitized evidence reference, deviation, and rollback information. A correction SHALL append a superseding entry instead of silently rewriting historical results.

#### Scenario: An action succeeds
- **WHEN** an operator completes a provisioning action
- **THEN** its evidence is recorded before the corresponding task is marked complete

#### Scenario: An action fails or deviates from plan
- **WHEN** the observed result differs from the planned result
- **THEN** the log records the failure or deviation, its impact, and the next safe action without marking the task complete

#### Scenario: Evidence contains sensitive material
- **WHEN** evidence includes a password, token, private key, kubeconfig credential, machine secret, or other secret value
- **THEN** the committed log contains only a redacted description or non-sensitive digest and never the secret value

### Requirement: Live mutations are controlled and recoverable
The workflow SHALL identify destructive or difficult-to-reverse operations before execution, capture the exact target using a read-only check, and record a rollback or recovery procedure. Proxmox snapshots SHALL NOT be treated as disaster-recovery backups.

#### Scenario: A material live mutation is proposed
- **WHEN** the next action changes firmware, RAID state, disk allocation, networking, an installed operating system, or cluster state
- **THEN** the operator sees the resolved target, expected effect, risk, prerequisite backup, and recovery action before execution

#### Scenario: Provisioning reaches an acceptance gate
- **WHEN** an implementation phase is declared complete
- **THEN** its configuration can be reconstructed from Git and its stated recovery procedure has been exercised or is explicitly recorded as an unresolved blocker

### Requirement: Remote administration is independent of Kubernetes
The platform SHALL support authorized remote Proxmox UI and SSH access through host-level Tailscale without requiring a running Kubernetes cluster or public administration ports. Installation, enrollment, remote connectivity and subnet routing SHALL be recorded as distinct states. Local console and trusted local-network access SHALL remain documented recovery paths.

#### Scenario: Host installation is reported
- **WHEN** the operator reports Tailscale installed on pve
- **THEN** the record identifies that evidence as operator-reported and does not mark service persistence, enrollment, remote access or subnet routes verified without their own checks

#### Scenario: Remote host administration is accepted
- **WHEN** an authorized administrator connects from outside the home network
- **THEN** Proxmox HTTPS and authenticated SSH work over Tailscale, the current access policy is recorded with the operator-approved tailnet-membership trust boundary, and the record identifies the tested endpoint, TLS handling and service persistence

#### Scenario: Subnet access is enabled
- **WHEN** Proxmox advertises 10.42.0.0/24 to the tailnet
- **THEN** route approval, client acceptance, host forwarding, access policy and return traffic are verified for intended management endpoints, without assuming that guest Tailscale installation or public exposure is required

#### Scenario: Remote access must be rebuilt
- **WHEN** the administrator device, Proxmox host or tailnet device identity is lost
- **THEN** independently available instructions and credentials permit local recovery and Tailscale re-enrollment, with old identity revocation and policy/route restoration, without plaintext secrets in Git or dependency on the failed Kubernetes cluster

#### Scenario: External GPU worker connectivity is evaluated
- **WHEN** management subnet access works
- **THEN** the external worker still requires separate verification of bidirectional Kubernetes node and Cilium networking before joining; management success alone does not satisfy that acceptance gate

### Requirement: Restrictive tailnet grants are optional hardening
The initial build MAY retain the operator-approved default allow-all tailnet policy. Adoption of account/port-scoped grants and removal of Funnel capability SHALL be tracked as optional improvements rather than prerequisites for VM creation. The record SHALL distinguish tailnet-wide access from public exposure; management Serve endpoints SHALL remain tailnet-only.

#### Scenario: Restrictive policy is deferred
- **WHEN** the operator chooses to retain the default policy
- **THEN** the proposed restrictive policy remains unapplied, subnet access can be accepted under the documented membership trust boundary, and remaining deployment/recovery requirements are unchanged

### Requirement: Daily encrypted etcd backups retain the latest recovery point
The homelab SHALL capture and validate an etcd snapshot daily through a versioned GitHub Actions workflow, with manual dispatch available. The workflow SHALL use the existing private Tailscale management path and Talos identity, encrypt to an age public recipient, and upload through a dedicated GitHub OIDC AWS role. The private age identity SHALL remain outside Git and CI and SHALL be saved independently for recovery. No long-lived AWS key or interactive passphrase SHALL be required for scheduled runs.

#### Scenario: Daily backup succeeds
- **WHEN** a scheduled or manually dispatched main-branch backup runs
- **THEN** it verifies the snapshot metadata and embedded integrity checksum, packages original Talos identity and reconstruction inputs, encrypts locally, uploads a new version of etcd/latest.tar.gz.age, downloads that exact version and compares ciphertext before emitting a success heartbeat

#### Scenario: Old backup versions expire
- **WHEN** an etcd backup version has been noncurrent for more than 30 days
- **THEN** S3 Lifecycle makes it eligible for permanent deletion, subject to asynchronous processing and Object Lock; no current-version expiration applies to the etcd prefix

#### Scenario: Backups stop
- **WHEN** no new backup is produced for more than 30 days
- **THEN** the latest current backup remains available indefinitely and an independent CloudWatch missing-heartbeat alarm detects the absence of success after approximately 30 hours

#### Scenario: Backup credentials are limited
- **WHEN** the backup runner assumes its AWS role
- **THEN** its S3 permissions are scoped to upload/readback of the one backup key, it cannot delete objects or versions or bypass retention, and KMS/metric permissions are scoped to the recovery key and metric namespace

#### Scenario: Recovery encryption is verified
- **WHEN** the first automated backup is accepted
- **THEN** the operator downloads the exact object version and verifies local decryption with the private recovery key; ciphertext readback alone is not claimed as a restore test, and independent key custody remains explicit until confirmed

Retention is scoped to the daily etcd backup set. Existing independent bootstrap/host archives and routine/monthly backup sets keep their existing rules; this change does not purge unrelated recovery material.

### Requirement: Deployment and selected acceptance must pass before merge
The required merge gate SHALL require a successful CI apply for every selected
infrastructure deployment and successful completion of all selected acceptance
jobs. An absent apply label SHALL NOT count as a successful infrastructure
apply. Test-only changes SHALL trigger their affected acceptance suite without
requiring an infrastructure apply.

#### Scenario: Infrastructure PR has no apply label
- **WHEN** deploy-unit detection selects an infrastructure root but apply is skipped
- **THEN** the required apply-gate fails with an explicit pending-apply diagnostic and automatic merge is not enabled

#### Scenario: Selected acceptance fails or is skipped
- **WHEN** an affected network/PVC acceptance job fails, is cancelled or unexpectedly skips
- **THEN** the required merge gate fails even if apply succeeded or the PR changed only tests

#### Scenario: Routine deployment completes
- **WHEN** Talos configuration is applied routinely
- **THEN** both nodes use no_reboot mode, readiness checks are read-only and no hidden persistence reboot occurs

#### Scenario: Worker persistence rehearsal is requested
- **WHEN** the operator explicitly labels a deployment for worker reboot or confirms a main-branch maintenance dispatch
- **THEN** a separate job checks the existing worker data disk, reboots only that worker, compares OS/data partition identities and verifies readiness without forced reset; first-provision acceptance requires this evidence

### Requirement: Enforced AI storage boundaries
AI models, workspace and vector data SHALL use separate project-quota directories on the existing shared XFS worker filesystem and retained static local volumes with worker affinity. Initial enforced hard limits SHALL be 300 GiB, 20 GiB and 10 GiB respectively. Stable project IDs SHALL be 31001, 31002 and 31003. Declared limits MAY exceed physical capacity and MUST NOT reserve or preallocate space. Existing disks, unrelated provisioner claims and data MUST remain unchanged. Temporary storage MUST have separate limits. Provisioning and startup MUST account for physical thin-pool data and metadata capacity as well as guest filesystem space. Missing mounts or unavailable capacity checks MUST block AI startup. An AI reset MUST affect only those three application volumes and preserve unrelated data, including Pi-hole.

#### Scenario: Write exceeds an application boundary
- **WHEN** an AI application reaches its project hard limit
- **THEN** writes fail with quota enforcement while another project below its limit remains writable when physical headroom remains

#### Scenario: Storage evidence unavailable
- **WHEN** physical capacity or mount identity cannot be verified
- **THEN** AI startup is rejected instead of assuming thin provisioning or a directory constitutes usable capacity

### Requirement: Secondary join preserves the existing cluster and storage
The secondary worker SHALL join using the existing cluster secrets and API VIP
10.0.0.231 without reinstalling the control plane or repeating etcd bootstrap.
It SHALL retain worker-role=secondary and stateless-compute=true under the
homelab.tfdraw.dev label prefix, with no local-storage label, local PV or
secondary StorageClass. The 200-GiB secondary Nexus OCI cache disk and instance,
Docker Hub/ECR proxying, registry mirrors, Roles Anywhere refresher and
cache-registry.homelab.tfdraw.dev SHALL remain deferred.

#### Scenario: Secondary creation is attempted
- **WHEN** VM 103 is about to be created
- **THEN** power, IMM/PVE access, host memory reserves, ECC and storage health are verified, VM ID 103 is unused, and same-LAN checks immediately before creation confirm .225 is unused

#### Scenario: Secondary capacity is accepted
- **WHEN** worker-02 is declared active
- **THEN** it is Ready with unique identity/IP, expected resources and extensions, Talos health, successful Cilium pod-to-pod and Service connectivity, a successful stateless placement test and continuous access through the API VIP

#### Scenario: Protected storage is checked after joining
- **WHEN** the join acceptance inventory is compared with the preflight inventory
- **THEN** Pi-hole, CNPG/PostgreSQL, Nexus and Nexus PostgreSQL PVC/PV identities and bindings are preserved, their consuming Pods remain primary-pinned, and no new PVC, local PV or Nexus cache workload is created on worker-02

#### Scenario: Secondary gVisor execution is accepted
- **WHEN** a stateless acceptance Pod is scheduled onto worker-02 using the runsc handler
- **THEN** worker-02 has the extension prerequisite user.max_user_namespaces=11255, the Pod starts under gVisor with restricted privileges and resource limits, bidirectional cross-node Pod and Service requests succeed, and temporary test resources are removed afterward
- **AND** the user-namespace hardening trade-off is documented without claiming a permanent sandbox admission or network-policy rollout
