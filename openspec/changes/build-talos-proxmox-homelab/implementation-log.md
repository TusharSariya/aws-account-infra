# Homelab Provisioning Implementation Log

This is an append-only execution record for the OpenSpec change
`build-talos-proxmox-homelab`. Corrections must be added as new entries that
identify the sequence number they supersede. Do not place credentials, private
keys, tokens, kubeconfig contents, Talos machine secrets, or other sensitive
values in this file.

## Entry template

### LOG-NNNN - Short description

- Timestamp: RFC 3339 timestamp for when the entry was recorded
- Operator: Person or automation that performed the action
- Target: Exact host, VM, file, or service acted upon
- Task: OpenSpec task identifier
- Intended action: Planned outcome
- Sanitized command or UI path: Exact non-secret command or interface path
- Result: `success`, `failure`, `partial`, or `blocked`
- Evidence: Sanitized observed output, identifiers, versions, and digests
- Deviation: `none` or the difference from the approved plan
- Superseded entry: `none` or an earlier `LOG-NNNN`
- Rollback or recovery: How to reverse the action or reconstruct the prior state

## Execution entries

### LOG-0001 - Trusted Talos artifact acquired

- Timestamp: 2026-08-25T19:27:06-02:30
- Operator: `root` on `pve` (operator-reported evidence)
- Target: Proxmox storage volume `local:iso/talos-v1.13.9-qemu-amd64.iso`
- Task: 1.2
- Intended action: Acquire the pinned Talos v1.13.9 amd64 ISO containing only the QEMU guest agent extension for the control-plane and trusted-worker VMs.
- Sanitized command or UI path: Talos Image Factory selection URL `https://factory.talos.dev/?arch=amd64&platform=metal&schematic-id=ce4c980550dd2ab1b17bbf2b08801c7eb59418eafe8f279833297925d67c7515&target=metal&version=1.13.9`; local verification command `sha256sum /var/lib/vz/template/iso/talos-v1.13.9-qemu-amd64.iso`
- Result: success
- Evidence: Talos `v1.13.9`; architecture `amd64`; artifact type `metal-amd64.iso`; schematic `ce4c980550dd2ab1b17bbf2b08801c7eb59418eafe8f279833297925d67c7515`; extension `siderolabs/qemu-guest-agent`; source artifact `https://factory.talos.dev/image/ce4c980550dd2ab1b17bbf2b08801c7eb59418eafe8f279833297925d67c7515/v1.13.9/metal-amd64.iso`; matching installer `factory.talos.dev/metal-installer/ce4c980550dd2ab1b17bbf2b08801c7eb59418eafe8f279833297925d67c7515:v1.13.9`; local filename `talos-v1.13.9-qemu-amd64.iso`; size `336932864` bytes; locally computed SHA-256 `8c4442982791a5c4a3eb769111a1c47806975176cc1a9c32a2130cdf0996db1d`
- Deviation: The local filename describes its intended QEMU use while the upstream artifact type is `metal-amd64.iso`; content identity is captured by the schematic and digest.
- Superseded entry: none
- Rollback or recovery: Remove only the resolved Proxmox ISO volume after confirming that no VM references it; reacquire it from the recorded Image Factory URL.

### LOG-0002 - Sandbox Talos artifact acquired

- Timestamp: 2026-08-25T19:27:06-02:30
- Operator: `root` on `pve` (operator-reported evidence)
- Target: Proxmox storage volume `local:iso/talos-v1.13.9-qemu-gvisor-amd64.iso`
- Task: 1.3
- Intended action: Acquire the pinned Talos v1.13.9 amd64 ISO containing the QEMU guest agent and gVisor extensions for the sandbox-worker VM.
- Sanitized command or UI path: Talos Image Factory selection URL `https://factory.talos.dev/?arch=amd64&platform=metal&schematic-id=8e8827b5b91420728f8415f3dc200fbf23b425ec07bf27cdc92a676367ee9edf&target=metal&version=1.13.9`; local verification command `sha256sum /var/lib/vz/template/iso/talos-v1.13.9-qemu-gvisor-amd64.iso`
- Result: success
- Evidence: Talos `v1.13.9`; architecture `amd64`; artifact type `metal-amd64.iso`; schematic `8e8827b5b91420728f8415f3dc200fbf23b425ec07bf27cdc92a676367ee9edf`; extensions `siderolabs/qemu-guest-agent` and `siderolabs/gvisor`; source artifact `https://factory.talos.dev/image/8e8827b5b91420728f8415f3dc200fbf23b425ec07bf27cdc92a676367ee9edf/v1.13.9/metal-amd64.iso`; matching installer `factory.talos.dev/metal-installer/8e8827b5b91420728f8415f3dc200fbf23b425ec07bf27cdc92a676367ee9edf:v1.13.9`; local filename `talos-v1.13.9-qemu-gvisor-amd64.iso`; size `497364992` bytes; locally computed SHA-256 `d9e6b843c120ba701d90128c9da6d3d4ca03f253a561e9488368c2823e13c808`
- Deviation: The local filename describes its intended QEMU use while the upstream artifact type is `metal-amd64.iso`; content identity is captured by the schematic and digest.
- Superseded entry: none
- Rollback or recovery: Remove only the resolved Proxmox ISO volume after confirming that no VM references it; reacquire it from the recorded Image Factory URL.

### LOG-0003 - Debian installer manifest comparison

- Timestamp: 2026-08-25T19:27:06-02:30
- Operator: `root` on `pve` (operator-reported evidence)
- Target: Proxmox storage volume `local:iso/debian-13.6.0-amd64-netinst.iso`
- Task: 1.4
- Intended action: Acquire Debian 13.6 amd64 netinst and verify it against Debian's signed SHA-512 manifest.
- Sanitized command or UI path: `cd /var/lib/vz/template/iso`; `curl -fsSLO https://cdimage.debian.org/debian-cd/current/amd64/iso-cd/SHA512SUMS`; `sha512sum -c SHA512SUMS --ignore-missing`
- Result: partial
- Evidence: Local filename `debian-13.6.0-amd64-netinst.iso`; size `791674880` bytes; checksum comparison returned `debian-13.6.0-amd64-netinst.iso: OK`.
- Deviation: The downloaded `SHA512SUMS` file was used successfully, but the evidence does not show authentication of `SHA512SUMS.sign` with a Debian CD signing key and does not include the locally computed SHA-512 value. Task 1.4 remains incomplete.
- Superseded entry: none
- Rollback or recovery: No system state changed beyond downloaded files. If signature authentication or the local digest fails, quarantine the ISO and manifest and download them again from the official Debian image service.

### LOG-0004 - Proxmox ISO inventory captured

- Timestamp: 2026-08-25T19:27:06-02:30
- Operator: `root` on `pve` (operator-reported evidence)
- Target: Proxmox ISO storage `local`
- Task: 1.5
- Intended action: Confirm that the two pinned Talos ISOs and one pinned Debian ISO are each present exactly once and record local digests.
- Sanitized command or UI path: `pvesm list local --content iso`; `sha256sum /var/lib/vz/template/iso/talos-v1.13.9-qemu-amd64.iso /var/lib/vz/template/iso/talos-v1.13.9-qemu-gvisor-amd64.iso`
- Result: partial
- Evidence: Exactly three ISO volumes were listed: `debian-13.6.0-amd64-netinst.iso` (`791674880` bytes), `talos-v1.13.9-qemu-amd64.iso` (`336932864` bytes), and `talos-v1.13.9-qemu-gvisor-amd64.iso` (`497364992` bytes). Talos SHA-256 values are recorded in `LOG-0001` and `LOG-0002`.
- Deviation: The Debian ISO's computed digest was not printed in the supplied evidence. Task 1.5 remains incomplete until it is recorded.
- Superseded entry: none
- Rollback or recovery: Inventory collection is read-only. Any unwanted ISO must be resolved by exact volume ID and checked for VM references before removal.

### LOG-0005 - Debian installer authenticity and digest verified

- Timestamp: 2026-08-25T19:30:07-02:30
- Operator: `root` on `pve` (operator-reported evidence)
- Target: Proxmox storage volume `local:iso/debian-13.6.0-amd64-netinst.iso`
- Task: 1.4, 1.5
- Intended action: Authenticate the pinned Debian 13.6 amd64 netinst checksum manifest, verify the local ISO against it, and record the ISO's exact local digest.
- Sanitized command or UI path: Download pinned `SHA512SUMS` and `SHA512SUMS.sign` from `https://cdimage.debian.org/debian-cd/13.6.0/amd64/iso-cd/`; `gpgv --keyring /usr/share/keyrings/debian-role-keys.gpg SHA512SUMS.sign SHA512SUMS`; `sha512sum -c SHA512SUMS --ignore-missing`; `sha512sum debian-13.6.0-amd64-netinst.iso`
- Result: success
- Evidence: The signature was made `2026-07-11T17:55:53-02:30` using RSA key `DF9B9C49EAA9298432589D76DA87E80D6294BE9B`; `gpgv` reported a good signature from `Debian CD signing key <debian-cd@lists.debian.org>`; manifest comparison returned `debian-13.6.0-amd64-netinst.iso: OK`; locally computed SHA-512 `ce0eeee7b51fdcdbed1e5116668c1fee27e528767bdf488e5f115a67b225e5dfd0afca1d456aaa9408ceb6b8527521ff7b6b5d62fdbe6f8c5faaf8df56a96292`.
- Deviation: none
- Superseded entry: `LOG-0003`, `LOG-0004`
- Rollback or recovery: Verification is non-destructive. Reacquire the ISO, signed manifest, and signature from the pinned official Debian 13.6.0 directory if future verification differs.

### LOG-0006 - Sanitized Proxmox baseline automation added

- Timestamp: 2026-08-25T19:54:45-02:30
- Operator: Codex in the repository workspace
- Target: `scripts/proxmox-baseline-create.sh` and `scripts/proxmox-baseline-fetch.sh`
- Task: 2.1
- Intended action: Automate creation, off-host transfer, checksum verification, and required-content validation of a non-secret baseline for the currently empty Proxmox host.
- Sanitized command or UI path: Added the two repository scripts; ran `bash -n` and `shellcheck` against both scripts and `git diff --check` against their paths.
- Result: partial
- Evidence: Both scripts pass Bash syntax validation, ShellCheck, and whitespace validation. The creator explicitly excludes `/etc/pve/priv`, `/etc/pve/user.cfg`, `/etc/shadow`, `/etc/ssh`, and `/var/lib/pve-cluster/config.db`, and aborts if its selected configuration matches likely secret patterns. The fetcher requires an exact baseline archive path, compares the off-host SHA-256 value, and verifies required archive entries.
- Deviation: The original recovery-grade encrypted export was narrowed, with operator approval, to a sanitized reconstruction baseline because the Proxmox host is currently empty. Task 2.1 remains incomplete until the scripts create an archive, copy it off-host, and successfully verify it there.
- Superseded entry: none
- Rollback or recovery: Remove the two scripts if this automation is abandoned; no live Proxmox state has been changed by adding them to the repository.

### LOG-0007 - Off-host baseline fetch used an incorrect example filename

- Timestamp: 2026-08-25T20:01:16-02:30
- Operator: `tusharsariya` on the Mac (operator-reported evidence)
- Target: Intended Proxmox archive `/root/pve-empty-host-baseline-20260825T220000Z.tar.gz`
- Task: 2.1
- Intended action: Fetch the generated sanitized Proxmox baseline and checksum to the off-host Mac destination.
- Sanitized command or UI path: `./scripts/proxmox-baseline-fetch.sh root@10.0.0.92 /root/pve-empty-host-baseline-20260825T220000Z.tar.gz`
- Result: failure
- Evidence: `scp` reported that the archive and checksum did not exist. The requested timestamp was the documentation example rather than the generated archive timestamp.
- Deviation: No data was transferred because the requested source filename was incorrect. The Proxmox archive itself was unaffected.
- Superseded entry: none
- Rollback or recovery: No rollback was required; rerun the fetcher with the exact `BASELINE_FILE` printed by the creator.

### LOG-0008 - Sanitized Proxmox baseline verified off-host

- Timestamp: 2026-08-25T20:01:16-02:30
- Operator: `root` on `pve` and `tusharsariya` on the Mac (operator-reported evidence)
- Target: Proxmox archive `/root/pve-empty-host-baseline-20260825T222711Z.tar.gz` and off-host copy `/Users/tusharsariya/Backups/proxmox/pve/pve-empty-host-baseline-20260825T222711Z.tar.gz`
- Task: 2.1
- Intended action: Create a sanitized empty-host baseline, confirm the secret scan passes, transfer the archive and checksum off-host, verify SHA-256 equality, and list required reconstruction entries.
- Sanitized command or UI path: `/root/proxmox-baseline-create.sh`; `./scripts/proxmox-baseline-fetch.sh root@10.0.0.92 /root/pve-empty-host-baseline-20260825T222711Z.tar.gz`
- Result: success
- Evidence: Creator reported `SECRET_SCAN=passed`; Proxmox and Mac both reported SHA-256 `1540ee8bc367957300ea6faf8e6a6de444861d1d9e0670b493cb02d2c8f22d14`; fetcher reported `BASELINE_LISTING_VERIFIED=yes`; verified entries were `./config/etc/network/interfaces`, `./config/etc/pve/storage.cfg`, `./inventory/pve-version.txt`, and `./inventory/storage-status.txt`.
- Deviation: With operator approval, this is a sanitized reconstruction baseline for an empty host rather than an encrypted credential-bearing disaster-recovery export.
- Superseded entry: `LOG-0006`, `LOG-0007`
- Rollback or recovery: Retain the off-host Mac archive and checksum. Recreate the baseline by rerunning the repository scripts if the empty host configuration changes before stateful provisioning begins.

### LOG-0009 - Read-only ServeRAID inspection automation added

- Timestamp: 2026-08-25T20:05:06-02:30
- Operator: Codex in the repository workspace
- Target: `scripts/proxmox-serveraid-inspect.sh`
- Task: 2.2
- Intended action: Automate read-only collection of controller, logical-drive, physical-drive, cache-protection, patrol-read, and consistency-check state from the IBM ServeRAID M5110 before guest storage is allocated.
- Sanitized command or UI path: Added the repository script; ran `bash -n`, `shellcheck`, and `git diff --check` against it.
- Result: partial
- Evidence: The script passes Bash syntax, ShellCheck, and whitespace validation; detects StorCLI, PercCLI, or MegaCLI; invokes only information-display commands; retains raw hardware evidence outside Git; and emits a reduced shareable summary without intentionally selecting serial-number fields.
- Deviation: none
- Superseded entry: none
- Rollback or recovery: Remove the script if this inspection automation is abandoned. Task 2.2 remains incomplete until it runs on `pve` and every required safety condition is reviewed without an unresolved finding.

### LOG-0010 - ServeRAID inspection blocked by missing management CLI

- Timestamp: 2026-08-25T20:08:48-02:30
- Operator: `root` on `pve` (operator-reported evidence)
- Target: PCI device `1b:00.0`, IBM ServeRAID M5110 SAS/SATA Controller
- Task: 2.2
- Intended action: Run the read-only ServeRAID inspection and collect controller, logical-drive, physical-drive, cache-protection, and patrol-read evidence.
- Sanitized command or UI path: `/root/proxmox-serveraid-inspect.sh`; `lspci -nnk | grep -A3 -Ei 'raid|sas|lsi|broadcom'`
- Result: blocked
- Evidence: The script reported `RAID_CLI=not-found` and retained preliminary evidence in `/root/pve-serveraid-inspection-20260825T223609Z`. PCI inspection identified `Broadcom / LSI MegaRAID SAS 2208 [Thunderbolt] [1000:005b]`, subsystem `IBM ServeRAID M5110 SAS/SATA Controller [1014:040b]`, with kernel driver and module `megaraid_sas`.
- Deviation: The required IBM/Broadcom management utility is not installed, so controller-internal and per-disk health cannot yet be assessed. This is not evidence that the array is unsafe or healthy.
- Superseded entry: none
- Rollback or recovery: No controller state changed. Resolve StorCLI availability from a verified package, rerun the read-only script, and retain this blocked attempt in the audit history.
### LOG-0011 - Enterprise APT sources block package index refresh

- **Timestamp:** 2026-08-25T22:40:00Z
- **Task:** 2.2 (management-tool prerequisite)
- **Actor:** Operator on `pve`
- **Action:** Refreshed APT indexes and searched the configured repositories for the `storcli` package.
- **Result:** `apt-get update` failed with HTTP 401 responses from the Proxmox VE and Ceph enterprise repositories. The host does not have repository authorization, and `storcli` was not found in the remaining Debian repositories.
- **Evidence:** Operator console output retained in the implementation conversation; the previously captured baseline contains the two enterprise source definitions.
- **Deviation:** RAID inspection remains incomplete. The repository configuration must be corrected before installing the separately distributed IBM/Broadcom management utility.

### LOG-0012 - Reversible no-subscription repository correction prepared

- **Timestamp:** 2026-08-25T22:42:00Z
- **Task:** 2.2 (management-tool prerequisite)
- **Actor:** Codex
- **Action:** Added `scripts/proxmox-enable-no-subscription-repos.sh` for Proxmox VE 9 on Debian 13. The script backs up and disables the unauthorized enterprise definitions, enables the official Proxmox VE and Ceph no-subscription channels, runs `apt-get update`, and automatically restores the original definitions if the update fails.
- **Result:** Script prepared locally; execution on `pve` is pending.
- **Evidence:** `scripts/proxmox-enable-no-subscription-repos.sh`.
- **Deviation:** None. This changes only package repository channels and does not install or upgrade packages.

### LOG-0013 - No-subscription repositories enabled successfully

- Timestamp: 2026-08-25T22:45:28Z
- Operator: `root` on `pve` (operator-reported evidence)
- Target: Proxmox VE and Ceph APT source definitions on `pve`
- Task: 2.2 (management-tool prerequisite)
- Intended action: Replace unauthorized Proxmox enterprise channels with the corresponding official no-subscription channels and refresh package indexes without installing or upgrading packages.
- Sanitized command or UI path: `/root/proxmox-enable-no-subscription-repos.sh --apply`
- Result: success
- Evidence: `apt-get update` fetched signed indexes from `download.proxmox.com` for `trixie/pve-no-subscription` and `trixie/no-subscription`; the script reported `REPOSITORY_MODE=no-subscription` and `APT_UPDATE=passed`. Original sources were backed up at `/root/pve-apt-sources-before-no-subscription-20260825T224528Z`.
- Deviation: APT emitted harmless notices for the two timestamped `.disabled-*` files retained inside `/etc/apt/sources.list.d`. Move those files into the recorded backup directory to prevent recurring notices. This does not invalidate the successful index refresh.
- Superseded entry: none
- Rollback or recovery: Remove the two no-subscription source definitions and restore `pve-enterprise.sources` and `ceph.sources` from `/root/pve-apt-sources-before-no-subscription-20260825T224528Z`; enterprise index refresh will remain unavailable without a valid subscription.

### LOG-0014 - Repository switch script stops leaving APT filename notices

- Timestamp: 2026-08-25T22:47:00Z
- Operator: Codex in the repository workspace
- Target: `scripts/proxmox-enable-no-subscription-repos.sh`
- Task: 2.2 (management-tool prerequisite)
- Intended action: Retain disabled enterprise definitions outside `/etc/apt/sources.list.d` so subsequent APT operations do not warn about invalid filename extensions.
- Sanitized command or UI path: Updated the repository script; ran Bash syntax, ShellCheck, whitespace, and strict OpenSpec validation.
- Result: success
- Evidence: The script now moves both disabled definitions directly into its timestamped `/root/pve-apt-sources-before-no-subscription-*` backup directory while preserving automatic rollback paths.
- Deviation: The already-executed host copy predates this correction and requires the two explicit non-destructive moves recorded in the next operator step.
- Superseded entry: `LOG-0012` script behavior only; `LOG-0013` remains the authoritative observed host result.
- Rollback or recovery: The repository-only adjustment can be reverted through version control. Host rollback continues to use the timestamped backup directory.

### LOG-0015 - Verified StorCLI installation automation prepared

- Timestamp: 2026-08-25T22:52:00Z
- Operator: Codex in the repository workspace
- Target: `scripts/proxmox-storcli-install.sh`
- Task: 2.2 (management-tool prerequisite)
- Intended action: Acquire and install the IBM-supported StorCLI utility needed for read-only ServeRAID M5110 inspection.
- Sanitized command or UI path: Added the repository script; ran Bash syntax, ShellCheck, whitespace, and strict OpenSpec validation.
- Result: partial
- Evidence: IBM's official support page identifies StorCLI 7.1212.0000.0000 as supporting the ServeRAID M5110 and x3550 M4. The script pins the official IBM HTTPS artifact at 4,002,328 bytes with locally confirmed SHA-256 `a33b2696df36c4a56c1e8a8217ba90eb698de5a4498d58a8268c862cab4639fe`, checks archive paths, verifies the embedded RPM signature using its supplied key in an isolated RPM database, extracts only the x86-64 binary, and tests a read-only `show` invocation.
- Deviation: IBM lists historical RHEL and SLES releases rather than Debian 13 as supported operating systems. The script therefore treats successful local execution as a compatibility gate and removes the binary automatically if that gate fails.
- Superseded entry: The planned use of StorCLI 1.14.12 in the implementation conversation is superseded by IBM's later M5110-supported 7.1212 release.
- Rollback or recovery: Remove `/opt/MegaRAID/storcli/storcli64` if the utility is no longer required. The installation evidence directory is retained beneath `/root`; the script does not issue any RAID mutation command.

### LOG-0016 - StorCLI key import rejected by Debian 13 policy

- Timestamp: 2026-08-25T22:52:00Z
- Operator: `root` on `pve` (operator-reported evidence)
- Target: Isolated RPM verification database in `/root/pve-storcli-install-20260825T225156Z`
- Task: 2.2 (management-tool prerequisite)
- Intended action: Import IBM's embedded StorCLI signing certificate before verifying and extracting the vendor RPM.
- Sanitized command or UI path: `/root/proxmox-storcli-install.sh --apply`
- Result: blocked
- Evidence: RPM reported `Policy rejects 9D7562E8A120B85F: No binding signature at time 2026-08-25T22:52:00Z` and rejected the key import. The failure occurred after the official HTTPS artifact passed its pinned size and SHA-256 checks and before any StorCLI binary was installed.
- Deviation: The modern rpm-sequoia policy rejects the legacy certificate binding used by IBM's 2019 signing key. This does not establish that the archive or RPM is corrupt, but the attempted RPM signature verification did not complete.
- Superseded entry: none
- Rollback or recovery: No StorCLI binary or RAID state was changed. Retain or remove the failed `/root/pve-storcli-install-20260825T225156Z` evidence directory at the operator's discretion; supporting Debian packages installed before the key check may remain.

### LOG-0017 - StorCLI verification correction scoped to certificate binding

- Timestamp: 2026-08-25T22:56:00Z
- Operator: Codex in the repository workspace
- Target: `scripts/proxmox-storcli-install.sh`
- Task: 2.2 (management-tool prerequisite)
- Intended action: Permit verification of IBM's legacy certificate binding without weakening the host's global cryptographic policy or accepting SHA-1 payload signatures.
- Sanitized command or UI path: Updated the installer to supply a per-process rpm-sequoia policy file only during the isolated RPM database initialization, certificate import, and signature check; ran Bash syntax, ShellCheck, whitespace, and strict OpenSpec validation.
- Result: partial
- Evidence: The local policy overrides only `sha1.second_preimage_resistance`, which rpm-sequoia documents as the property required for certificate self-signatures. SHA-1 collision resistance remains governed by the default rejection cutoff, so a SHA-1 data signature is not enabled. The policy file is retained with installation evidence beneath `/root`.
- Deviation: This is an explicit compatibility exception for an IBM-supported but legacy package. Successful RPM signature verification and local binary execution are still required on `pve` before the exception is accepted.
- Superseded entry: `LOG-0015` verification behavior only; the pinned IBM source, size, SHA-256, compatibility gate, and read-only scope remain unchanged.
- Rollback or recovery: The exception exists only as environment variables applied to individual RPM commands. It creates no system-wide policy file and requires no host-policy rollback.

### LOG-0018 - ServeRAID inspection collected for raw review

- Timestamp: 2026-08-25T22:55:45Z
- Operator: `root` on `pve` (operator-reported evidence)
- Target: IBM ServeRAID M5110 controller 0 and eight attached SAS disks
- Task: 2.2
- Intended action: Run the read-only ServeRAID inspection after installing StorCLI and retain controller, logical-drive, CacheVault, patrol-read, and per-disk evidence.
- Sanitized command or UI path: `/root/proxmox-serveraid-inspect.sh`
- Result: partial
- Evidence: StorCLI 7.1212 completed required collection and created `/root/pve-serveraid-inspection-20260825T225545Z.tar.gz`. The shareable summary reports controller and virtual-disk state `Optimal`; eight `ST9300653SS` 278.464-GB SAS disks in drive group 0, all `Onln`; zero media, other, and predictive-failure counts plus no SMART alert on all eight disks; CacheVault replacement `No` and capacitance `100%`; patrol-read mode `Auto` with 168-hour recurrence; and disk cache `Disabled`.
- Deviation: The BBU-specific query failed while the CacheVault query succeeded, which is consistent with flash-backed rather than battery-backed cache but is not yet accepted without raw review. The condensed summary omitted the actual logical-drive RAID level, write-cache policy, and grown-defect field required by task 2.2.
- Superseded entry: `LOG-0010` blocker is resolved; its failed attempt remains part of the history.
- Rollback or recovery: No RAID state changed. Copy the report archive off-host, verify its archive structure, and review the omitted fields before marking task 2.2 complete. StorCLI can be removed from `/opt/MegaRAID/storcli/storcli64` after hardware inspection if desired.

### LOG-0019 - Off-host RAID archive verified and reviewed

- Timestamp: 2026-08-25T23:02:00Z
- Operator: Codex in the repository workspace using operator-provided archive
- Target: `/Users/tusharsariya/Backups/proxmox/pve/pve-serveraid-inspection-20260825T225545Z.tar.gz`
- Task: 2.2
- Intended action: Verify the off-host archive matches the Proxmox copy, validate its paths, and review the raw RAID, cache-protection, patrol-read, consistency-check, and physical-disk evidence.
- Sanitized command or UI path: Compared operator-reported and local SHA-256 values; listed the archive without extraction; read selected reports using `tar -xOzf`; aggregated non-identifying health fields.
- Result: partial
- Evidence: Both systems report SHA-256 `b4bfd68c64f37b1f8084bb7325fb426c7d09aa49e79c88231c84c0f62911f23a`, and archive paths are relative and safe. VD 0 is a consistent, optimal 1.903-TB RAID5 across eight online SAS disks. Cache mode `RWBD` means read-ahead, write-back, direct I/O; disk cache is disabled; `Cache When BBU Bad = Off`; CacheVault CVPM02 is optimal at 100% capacitance with replacement not required. Patrol read is automatic at 168 hours with two completed iterations. Every disk reports zero shield, BBM, media, other, and predictive-failure counters and no SMART alert, at 27-29 C.
- Deviation: Scheduled consistency checking is enabled at 168 hours but has completed zero iterations. The raw StorCLI report contains BBM counts but not the SAS `Elements in grown defect list` field required by the task. RAID5 also has no hot spare and tolerates only one disk failure; this risk requires explicit acceptance after direct SMART review and before stateful allocation.
- Superseded entry: `LOG-0018` is expanded by this raw review; its observed collection result remains valid.
- Rollback or recovery: No host state changed during off-host review. Keep the verified archive outside Git. Collect read-only direct SMART evidence for every disk before deciding whether a consistency check or allocation is safe.

### LOG-0020 - Direct SMART coverage added to RAID inspector

- Timestamp: 2026-08-25T23:05:00Z
- Operator: Codex in the repository workspace
- Target: `scripts/proxmox-serveraid-inspect.sh`
- Task: 2.2
- Intended action: Collect the SAS grown-defect and direct SMART evidence omitted by StorCLI while preventing silent partial-drive coverage.
- Sanitized command or UI path: Updated the repository script; ran Bash syntax, ShellCheck, whitespace, and strict OpenSpec validation.
- Result: partial
- Evidence: When `smartctl` is installed, the script uses read-only `smartctl --scan-open` enumeration and `smartctl -q noserial -a -d megaraid,N` for each discovered device. It suppresses serial and WWN output, compares SMART report count with StorCLI physical-drive count, and makes missing, failed, or incomplete SMART coverage a required collection failure. The shareable summary now includes grown-defect, SMART health, non-medium-error, BBM, and shield fields.
- Deviation: Installing the Debian `smartmontools` package and executing the revised collector on `pve` remain pending. No self-test or consistency check is started automatically.
- Superseded entry: `LOG-0009` collection scope only; prior archives remain immutable evidence of their original script version.
- Rollback or recovery: Remove the repository change through version control if direct SMART collection is abandoned. Removing `smartmontools` is optional and should be separately assessed because it is useful for ongoing disk monitoring.

### LOG-0021 - Direct SMART inspection identifies grown defects

- Timestamp: 2026-08-25T23:03:33Z
- Operator: `root` on `pve` (operator-reported evidence)
- Target: IBM ServeRAID M5110 controller 0 and all eight SAS disks
- Task: 2.2
- Intended action: Collect direct read-only SMART evidence for every physical disk through the MegaRAID passthrough interface.
- Sanitized command or UI path: `/root/proxmox-serveraid-inspect.sh`
- Result: blocked
- Evidence: Collection completed for MegaRAID device IDs 47, 48, 49, 50, 51, 53, 54, and 55 with `smart-coverage=complete count=8`. All disks report `SMART Health Status: OK`. In MegaRAID device-ID order, grown-defect counts are 0, 0, 0, 0, 7, 2, 1, and 0; non-medium-error counts are 93, 45, 15, 189, 1890, 110, 14, and 15. Device ID 51 maps to enclosure 252 slot 2, device ID 53 to slot 7, and device ID 54 to slot 6.
- Deviation: Three disks have non-zero grown-defect lists, and device ID 51 has a materially higher non-medium-error count than its peers. Overall SMART `OK` does not resolve these observed counters. Together with RAID5 single-parity, no hot spare, and zero recorded completed consistency checks, this is an unresolved storage-readiness risk.
- Superseded entry: `LOG-0019` pending direct-SMART finding is resolved with adverse evidence; its other reviewed facts remain valid.
- Rollback or recovery: No SMART self-test, consistency check, rebuild, or RAID mutation occurred. Keep VM disk allocation blocked, copy and verify the new raw archive off-host, then review per-device error logs before approving any additional disk load or replacement plan.

### LOG-0022 - SMART summary labels MegaRAID device IDs

- Timestamp: 2026-08-25T23:07:00Z
- Operator: Codex in the repository workspace
- Target: `scripts/proxmox-serveraid-inspect.sh`
- Task: 2.2
- Intended action: Prevent ambiguity when correlating SMART counters with the enclosure-slot and device-ID inventory.
- Sanitized command or UI path: Updated the shareable summary to print each SMART report filename before its health, grown-defect, and non-medium-error fields; ran Bash syntax, ShellCheck, whitespace, and strict OpenSpec validation.
- Result: success
- Evidence: Future summaries identify results as `smart-megaraid-N.txt`, allowing direct correlation with StorCLI `DID` values without exposing disk serial numbers or WWNs.
- Deviation: The already-collected `20260825T230333Z` summary predates this presentation correction, but its deterministic report ordering and collection-status list allow the mapping recorded in `LOG-0021`.
- Superseded entry: `LOG-0020` summary presentation only; collection behavior is unchanged.
- Rollback or recovery: Revert the repository-only formatting change through version control if unnecessary.

### LOG-0023 - Authorized direct SSH storage investigation

- Timestamp: 2026-08-25T23:15:00Z
- Operator: Codex over operator-authorized SSH
- Target: `root@10.0.0.92` (`pve`), IBM ServeRAID M5110 controller 0
- Task: 2.2 and capacity input for 2.6
- Intended action: Read the retained RAID archive and query current controller, direct SMART, event-log, block-device, Proxmox-storage, and LVM-thin state without starting tests or changing configuration.
- Sanitized command or UI path: Read-only `ssh`; `tar -xOzf`; `smartctl -q noserial -x -d megaraid,N /dev/sda`; `storcli64 /c0 show events` with identifiers excluded from committed evidence; `pvesm status`; `lsblk`; and `lvs`.
- Result: blocked
- Evidence: All eight 300-GB, 15K SAS disks have approximately 52,233 power-on hours. Device ID 51 has seven grown defects and 1,890 non-medium errors but zero uncorrected read/write/verify errors. Device IDs 53 and 54 have two and one grown defects respectively and each records one historical uncorrected verify error. Current SAS PHY counters show zero invalid DWORD and disparity errors, zero PHY-reset problems, and at most two historical synchronization losses, so the evidence does not presently isolate a live backplane-link fault. The current RAID5 VD was created on 2025-09-26; controller history records failed background initialization at creation and a degraded VD plus physical-disk diagnostic failure on 2025-12-09. Older controller history also includes offline VDs, missing disks, discarded pinned cache, and excessive consistency-check inconsistencies across prior configurations. Current `local-lvm` is healthy but 0% used at 1,795.99 GiB, so no guest data requires migration.
- Deviation: The current controller entitlement advertises RAID 0, 1, 5, 10, and 50; RAID6/60 requires the optional M5100 RAID6 feature and is not currently advertised. The approved 1,556-GiB guest-disk plan fits the current RAID5 thin pool but cannot retain safe headroom on an eight-disk 300-GB RAID6/RAID50-equivalent capacity and cannot fit on RAID10.
- Superseded entry: `LOG-0021` remains valid and is expanded with power-on, PHY, controller-history, and capacity evidence.
- Rollback or recovery: No live state changed. Keep guest allocation blocked. Because the host is empty and the verified reconstruction baseline is off-host, a destructive array rebuild is currently recoverable by recreating Proxmox; any selected RAID change still requires a separate explicit pre-action record and operator approval.

### LOG-0024 - Existing RAID5 risk explicitly accepted

- Timestamp: 2026-08-26T11:08:02Z
- Operator: Tushar Sariya (decision reported in conversation) and Codex (recording)
- Target: IBM ServeRAID M5110 virtual drive 0 on `pve`
- Task: 2.2
- Intended action: Resolve the storage-readiness decision after reviewing RAID level, controller protection, physical-disk health, error history, capacity, and available alternatives.
- Sanitized command or UI path: No host command; operator decision: retain the existing RAID5 configuration and proceed to the next task.
- Result: success
- Evidence: The retained array is an optimal 1.903-TiB RAID5 over eight online 300-GB 15K SAS disks. CacheVault is optimal at 100% capacitance, protected write-back is configured, disk cache is disabled, patrol read is automatic, and all disks report SMART health `OK`. The operator reviewed and explicitly accepted the remaining risk from single-parity RAID5, no hot spare, approximately 52,233 power-on hours per disk, three non-zero grown-defect lists, two historical verify errors, and no recorded completed consistency-check iteration.
- Deviation: The array is retained by explicit risk acceptance rather than eliminating every adverse counter through disk replacement, a completed consistency check, or conversion to a different RAID level. This is not high availability and does not replace backups. Before important state is placed on the host, workloads require tested application-native or VM-level backups to separate storage; storage health must be monitored.
- Superseded entry: `LOG-0023` allocation blocker is resolved by operator acceptance; all underlying observations remain valid.
- Rollback or recovery: The host is currently empty and its reconstruction baseline is stored off-host. If the accepted risk becomes unacceptable before stateful deployment, stop allocation and rebuild the array or replace disks under a separately approved destructive change. After state is introduced, restore from tested off-host backups rather than treating RAID as backup.

### LOG-0025 - Installed platform and firmware versions inventoried

- Timestamp: 2026-08-26T11:08:02Z
- Operator: Codex over operator-authorized SSH
- Target: `root@10.0.0.92` (`pve`), IBM System x3550 M4 machine type 7914
- Task: 2.3
- Intended action: Record the installed IBM UEFI, IMM2/IPMI, ServeRAID, NIC, and Proxmox versions without changing the host.
- Sanitized command or UI path: Read-only `ssh`; `dmidecode`; `/sys/devices/platform/ipmi_bmc.0`; `lspci -nnk`; `ethtool -i`; `storcli64 /c0 show all`; `pveversion -v`; `uname`; and Debian package queries. Hardware serial numbers and MAC addresses were excluded from the committed evidence.
- Result: partial
- Evidence: System `IBM System x3550 M4 Server`, machine type/model `7914AC1`; UEFI `D7E174BUS-3.20`, dated 2020-06-15; IMM2/IPMI firmware `8.41`, IPMI 2.0; ServeRAID M5110 package `23.34.0-0023`, firmware `3.460.145-8209`, BIOS `5.50.03.0_4.17.08.00_0x06110200`, Linux driver `megaraid_sas 07.734.00.00-rc1`; four Intel I350 Gigabit controllers `[8086:1521]` at firmware `1.63, 0x800009fa`; two Emulex OneConnect 10Gb controllers `[19a2:0710]`, subsystem `[10df:e729]`, at firmware `4.6.281.21`; Proxmox VE `9.2.0`, `pve-manager 9.2.2/b9984c6d90a4bd80`, kernel `7.0.2-6-pve`, Debian 13.
- Deviation: Inventory is complete, but final update disposition and recovery paths are not yet complete. No update, reboot, or configuration change was performed.
- Superseded entry: none
- Rollback or recovery: Read-only collection changed no state. Retain the verified empty-host baseline for Proxmox reconstruction; document component-specific recovery before approving any firmware flash.

### LOG-0026 - Current update disposition checked without applying updates

- Timestamp: 2026-08-26T11:08:02Z
- Operator: Codex over operator-authorized SSH and official IBM support review
- Target: `pve` software repositories and installed IBM firmware
- Task: 2.3
- Intended action: Compare installed versions with current trusted sources and identify updates that require a separately approved maintenance action.
- Sanitized command or UI path: `DEBIAN_FRONTEND=noninteractive apt-get -s full-upgrade`; official IBM support documents for System x3550 M4 UEFI 3.20, ServeRAID M5110 package 23.34.0-0023, and Emulex VFA II firmware guidance.
- Result: partial
- Evidence: The simulation completed successfully and proposed 139 package upgrades plus one new signed kernel, including `pve-manager 9.2.2` to `9.2.11` and `proxmox-kernel-7.0 7.0.2-6` to `7.0.14-14`; it made no changes. IBM identifies UEFI 3.20 build `D7E174B` as the latest x3550 M4 machine-type-7914 UEFI, matching the installed `D7E174BUS-3.20`. Lenovo's ServeRAID matrix identifies `23.34.0-0023` for M5110, matching the installed package. IBM guidance requires Emulex VFA II firmware `4.6.281.21` or later, and the installed adapters are exactly `4.6.281.21`; exact latest-applicable NIC and IMM2 bundle validation remains pending.
- Deviation: Proxmox is not current and its upgrade requires explicit approval, a maintenance window, a reboot into the new kernel, and post-update verification. No firmware or OS update was applied. Installed Emulex meets IBM's cited minimum, but it has not yet been proven to be the terminal version for subsystem `[10df:e729]`; Intel I350 and IMM2 final applicability checks also remain open.
- Superseded entry: none
- Rollback or recovery: Before a Proxmox upgrade, capture a fresh configuration baseline, confirm console/IMM access, and retain the previous kernel as a boot option. Before any firmware flash, record the exact IBM package, checksum, prerequisites, supported recovery mechanism, and an out-of-band or physical-console path. Task 2.3 remains incomplete pending disposition and separately approved updates.

### LOG-0027 - Fresh pre-upgrade baseline verified off-host

- Timestamp: 2026-08-26T11:10:35Z
- Operator: Codex over operator-authorized SSH
- Target: `root@10.0.0.92` (`pve`) and `/Users/tusharsariya/Backups/proxmox/pve/`
- Task: 2.3
- Intended action: Capture and verify a fresh recovery baseline immediately before the approved Proxmox package upgrade and reboot.
- Sanitized command or UI path: `/root/proxmox-baseline-create.sh`; `./scripts/proxmox-baseline-fetch.sh root@10.0.0.92 /root/pve-empty-host-baseline-20260826T111035Z.tar.gz`
- Result: success
- Evidence: Host creation reported `SECRET_SCAN=passed`; the off-host copy is `pve-empty-host-baseline-20260826T111035Z.tar.gz` with SHA-256 `ac09fdbf0759248f67fb20b7e521cdf93052d5b1b58bbd9762fe567c8515b3b0`. Safe archive listing succeeded and verified `./config/etc/network/interfaces`, `./config/etc/pve/storage.cfg`, `./inventory/pve-version.txt`, and `./inventory/storage-status.txt`.
- Deviation: none
- Superseded entry: none
- Rollback or recovery: Use the off-host archive to reconstruct or compare host network, storage, repository, and Proxmox configuration. Verify its recorded SHA-256 before extraction and restore only explicitly reviewed files.

### LOG-0028 - Proxmox full upgrade installed

- Timestamp: 2026-08-26T11:12:00Z
- Operator: Codex over operator-authorized SSH after explicit approval
- Target: `root@10.0.0.92` (`pve`), configured Debian and Proxmox no-subscription repositories
- Task: 2.3
- Intended action: Apply the previously simulated Proxmox and Debian package upgrade while the host contains no VMs or containers, retaining local configuration files and a complete host-side transcript.
- Sanitized command or UI path: Verified empty `qm list` and `pct list`; `apt-get update`; `DEBIAN_FRONTEND=noninteractive apt-get -y -o Dpkg::Options::=--force-confold full-upgrade`, with output retained at `/root/pve-upgrade-20260826T1112Z.log`.
- Result: success
- Evidence: A total of 139 packages were upgraded and one new signed kernel package was installed. `pve-manager` changed from 9.2.2 to 9.2.11; `proxmox-kernel-7.0` changed from 7.0.2-6 to 7.0.14-14. Package configuration and initramfs/GRUB generation completed with exit status 0. `dpkg --audit` was empty and a post-transaction simulation reported `0 upgraded, 0 newly installed, 0 to remove and 0 not upgraded`. The transcript SHA-256 is `a74202e215aff58c33c49f64fb694a6f5d60190e8c9429728cb19aadd274a26d`.
- Deviation: The installer emitted informational messages that no Proxmox boot UUID file exists, GRUB file descriptors were reported as inherited during LVM inspection, and an unused Ceph log glob did not exist. GRUB installation explicitly reported no error, the transaction completed successfully, and the targeted error scan found no package failure.
- Superseded entry: `LOG-0026` pending Proxmox update is resolved.
- Rollback or recovery: The pre-upgrade archive in `LOG-0027` preserves configuration. Both the old 7.0.2-6 and new 7.0.14-14 kernel and initramfs files remain installed, and GRUB retains an explicit 7.0.2-6 recovery entry. Select the prior kernel from GRUB through physical or IMM console if the new kernel cannot boot; use the baseline to reconstruct configuration if required.

### LOG-0029 - Post-upgrade verification command corrections retained

- Timestamp: 2026-08-26T11:16:00Z
- Operator: Codex over operator-authorized SSH
- Target: `root@10.0.0.92` (`pve`)
- Task: 2.3
- Intended action: Verify package, bootloader, API, and service state before and after reboot.
- Sanitized command or UI path: Read-only `dpkg-query`, `apt-get -s full-upgrade`, `systemctl`, `curl`, `uname`, and GRUB inspection commands.
- Result: partial
- Evidence: Two initial pre-reboot `dpkg-query` checks failed before collection because remote shell expansion treated `Version` and `binary` format tokens as unset variables. A corrected query confirmed `pve-manager 9.2.11`, `proxmox-kernel-7.0 7.0.14-14`, a clean package database, and zero pending upgrades. After reboot, the first unauthenticated API request received HTTP 401; this proves the HTTPS endpoint answered but `curl --fail` treated the expected authorization response as failure. The corrected status-only probe recorded HTTP 401 without stopping subsequent checks.
- Deviation: Verification required quoting and HTTP-status handling corrections; neither failed attempt changed host state or invalidated the successful package transaction.
- Superseded entry: none
- Rollback or recovery: No rollback is required for read-only failed probes. Reuse the corrected commands that avoid shell-expanded `dpkg-query` placeholders and treat an unauthenticated 401 as endpoint reachability rather than authenticated API success.

### LOG-0030 - Reboot and final platform state verified

- Timestamp: 2026-08-26T11:20:38Z
- Operator: Codex over operator-authorized SSH after explicit approval
- Target: `root@10.0.0.92` (`pve`), IBM System x3550 M4 machine type 7914
- Task: 2.3
- Intended action: Reboot once into the new kernel and verify final Proxmox, storage, RAID, firmware, service, package, and recovery state.
- Sanitized command or UI path: `systemctl reboot`; connectivity polling; `pveversion`; `uname -r`; package audit and simulation; `systemctl is-active` and `--failed`; local HTTPS status probe; `pvesm status`; StorCLI virtual-drive, CacheVault, controller, and firmware queries; DMI, IPMI sysfs, NIC firmware, boot-journal, `/boot`, and GRUB inspection.
- Result: success
- Evidence: The host returned on kernel `7.0.14-14-pve` with `pve-manager/9.2.11/f6997e698c7933ea`. `pve-cluster`, `pvedaemon`, `pveproxy`, `pvestatd`, and SSH are active; no failed systemd units are present; the HTTPS API endpoint answers and rejects the unauthenticated probe with HTTP 401 as expected. `local` and `local-lvm` are active and `local-lvm` remains 0% used. The ServeRAID M5110 controller and RAID5 virtual drive remain optimal; CacheVault is optimal at 100% capacitance with no replacement required. Final firmware remains UEFI `D7E174BUS-3.20`, IMM2 `8.41`, ServeRAID package `23.34.0-0023` / firmware `3.460.145-8209` / BIOS `5.50.03.0_4.17.08.00_0x06110200`, four Intel I350 ports at `1.63, 0x800009fa`, and two Emulex ports at `4.6.281.21`. Package audit is clean with zero pending upgrades.
- Deviation: No hardware firmware was flashed because the installed UEFI and ServeRAID match the identified terminal vendor releases, the Emulex firmware meets IBM guidance, and no exact applicable newer IMM2 or Intel I350 package was established. Boot journal contains platform warnings for ERST memory reservation, dbx signature parsing, a USB HID endpoint, and unused NFS block-layout plumbing; no warning corresponds to a failed unit, RAID fault, NIC fault, or Proxmox service failure.
- Superseded entry: `LOG-0025` and `LOG-0026` are completed by this final post-reboot verification; their pre-update evidence remains valid.
- Rollback or recovery: For a kernel regression, use the retained GRUB entry `Proxmox VE GNU/Linux, with Linux 7.0.2-6-pve` through physical or IMM console. For configuration recovery, verify and use the off-host baseline from `LOG-0027`. No firmware rollback is required because no firmware changed. Any future hardware flash still requires an exact supported package, checksum, prerequisites, vendor recovery method, and separately approved maintenance action.

### LOG-0031 - Virtualization, IOMMU, ECC, NUMA, and SMT state inspected

- Timestamp: 2026-08-26T11:22:22Z
- Operator: Codex over operator-authorized SSH
- Target: `root@10.0.0.92` (`pve`), two-socket Ivy Bridge CPU and memory topology
- Task: 2.4
- Intended action: Collect the read-only prerequisite evidence for the approved SMT-security decision before changing boot configuration.
- Sanitized command or UI path: `lscpu`; `/sys/devices/system/cpu/smt`; `/proc/cpuinfo`; `/sys/kernel/iommu_groups`; DMAR/IOMMU boot log; DMI type 16; `/sys/devices/system/edac/mc`; kernel EDAC/MCE log; and `/proc/cmdline`.
- Result: partial
- Evidence: VT-x is exposed on all 48 logical CPUs. Intel VT-d/IOMMU is active in translated mode with queued invalidation, interrupt remapping, two DRHD units, and 138 populated IOMMU groups. DMI reports single-bit ECC system memory across 24 device slots; Linux `sb_edac` registered four Ivy Bridge memory controllers and every controller reports zero corrected and zero uncorrected errors. Usable memory is 188.8 GiB. The system has two sockets, 12 physical cores per socket, two NUMA nodes, and 48 online logical CPUs because SMT is currently active with two threads per core.
- Deviation: The target design requires SMT disabled and 24 online physical CPUs because mixed and untrusted workloads will share this Ivy Bridge host. Current kernel command line has no SMT policy, so task 2.4 remains incomplete pending a separately approved persistent change and post-reboot verification.
- Superseded entry: none
- Rollback or recovery: The read-only inspection changed no state. The proposed reversible method is to add the documented Linux kernel parameter `nosmt=force`, regenerate GRUB, reboot, and verify 24 CPUs, one thread per core, two sockets, two NUMA nodes, IOMMU, and EDAC. Recovery is to select the prior GRUB entry or remove the parameter through console and regenerate GRUB.

### LOG-0032 - SMT retention and expanded worker allocation approved

- Timestamp: 2026-08-26T11:41:25Z
- Operator: Tushar Sariya (decision and allocation approval) and Codex (recording and plan reconciliation)
- Target: `pve` CPU topology and planned `talos-cp-01`, `talos-worker-01`, `talos-sandbox-01`, and `agent-nas-01` VM definitions
- Task: 2.4; planning input for 3.1, 3.2, 4.1, 4.2, 4.3, and 4.4
- Intended action: Retain SMT for additional compute throughput, accept its residual side-channel trade-off, and revise VM CPU allocations and later affinity requirements to match the observed 48-logical-CPU topology.
- Sanitized command or UI path: Operator decision in conversation; reconciled the OpenSpec specification, design, and tasks plus `docs/plans/talos-kubernetes-rebuild.md` and `docs/plans/authorized-agent-nas.md`. No host command was required because SMT was already enabled and verified.
- Result: success
- Evidence: `LOG-0031` verified VT-x on all 48 logical CPUs, active translated VT-d/IOMMU with 138 groups, 24 physical cores across two sockets, two threads per core, two NUMA nodes, 188.8 GiB usable ECC memory, and zero corrected and uncorrected errors on all four EDAC controllers. The approved allocation is 2 vCPUs for `talos-cp-01`, 16 for `talos-worker-01`, 20 for `talos-sandbox-01`, and 2 for `agent-nas-01`, totaling 40 of 48 logical CPUs. Later affinity must use complete sibling pairs, place sandbox and trusted guests on separate NUMA nodes without physical-core sharing, and leave eight logical CPUs representing four complete physical cores outside guest affinity.
- Deviation: This supersedes the earlier design choice to disable SMT. SMT improves throughput but does not double physical-core performance and retains residual cross-thread side-channel risk. The operator explicitly accepts that trade-off; gVisor, separate VMs, separate NUMA locality, and complete-sibling affinity reduce but do not eliminate it.
- Superseded entry: `LOG-0031` deviation and proposed `nosmt=force` action are superseded. Its observed hardware, virtualization, IOMMU, ECC, topology, and error-counter evidence remains valid.
- Rollback or recovery: No live host state changed, so no operational rollback is required. Revert the planning revision through version control if allocation policy changes. A future decision to disable SMT requires a new explicit action and post-change topology validation; VM vCPU counts or affinity can be revised during planned guest shutdowns after reviewing measured utilization.

### LOG-0033 - Proxmox network and candidate address space inspected

- Timestamp: 2026-08-26T11:48:50Z
- Operator: Codex over operator-authorized SSH
- Target: `root@10.0.0.92` (`pve`), `vmbr0`, trusted `10.0.0.0/24` LAN, and Rogers gateway `10.0.0.1`
- Task: 2.5
- Intended action: Inspect the live bridge, management path, routes, DNS, DHCP lease source, physical link, existing guest identities, MetalLB exclusion range, and candidate infrastructure addresses without changing networking.
- Sanitized command or UI path: Read-only `ip`, `bridge`, `ethtool`, `ss`, `qm list`, `pct list`, `pvesh get /cluster/nextid`, `pve-firewall status`, Tailscale presence check, DHCP lease-field extraction, gateway HTTP title check, and local-segment `nmap -sn` ARP discovery. A time-bounded gateway service-fingerprint attempt produced no retained result.
- Result: blocked
- Evidence: `vmbr0` is up at MTU 1500 over `nic0`, which is linked at 1000 Mb/s full duplex. It receives `10.0.0.92/24` by DHCP from gateway/server `10.0.0.1`; the recorded lease expires 2026-08-28T11:16:57Z and supplies DNS servers `64.71.255.204` and `64.71.255.198`. SSH and Proxmox HTTPS listen through the host network; the only configured LAN address is on `vmbr0`. Proxmox firewall service is active but policy enforcement reports disabled, and Tailscale is not installed, so management currently relies on the trusted RFC1918 LAN and Rogers gateway perimeter. No VM or container exists and VM ID 100 is the next available identifier. ARP discovery observed 13 responding hosts on the `/24`, no collision with the four proposed locally administered MAC addresses, and no responder at legacy API address `10.0.0.156`, candidate block `10.0.0.220-224`, or documented MetalLB pool `10.0.0.231-253`.
- Deviation: A one-time ARP scan demonstrates current non-use but cannot prove that sleeping devices, DHCP reservations, or the Rogers DHCP scope will not later claim an address. The Rogers login page is reachable, but reservation and scope configuration are not available without operator-authenticated router access. Exact VM identities and IPs remain proposals until the operator confirms them and the DHCP exclusions or reservations.
- Superseded entry: none
- Rollback or recovery: Read-only inspection changed no persistent state; its temporary scan file was removed. Do not create guests with candidate addresses until the router reserves the host and guest mappings and excludes the API VIP and MetalLB range. If an address conflict is later detected, stop the affected guest or VIP and revise the reservation plus repository desired state before restarting it.

### LOG-0034 - Proxmox management-address reservation prepared

- Timestamp: 2026-08-30T20:03:06-02:30
- Operator: Codex over operator-authorized SSH
- Target: NetworkManager shared connection `server-link` on `laptop-dell-studio` and Proxmox bridge `vmbr0` on `pve`
- Task: 2.5
- Intended action: Reserve `10.42.0.115` for the Proxmox bridge through the laptop's NetworkManager-managed DHCP service.
- Sanitized command or UI path: Read-only `ssh`; `ip`; `/etc/network/interfaces`; DHCP lease inspection; `nmcli`; process inspection; and non-interactive sudo capability check.
- Result: blocked
- Evidence: `pve` receives `10.42.0.115/24` on `vmbr0` through DHCP from `10.42.0.1` with a one-hour lease. The laptop owns `10.42.0.1/24` on `enp2s0`; NetworkManager connection `server-link` runs in IPv4 shared mode and starts dnsmasq with range `10.42.0.10-10.42.0.254`. The exact bridge hardware address was resolved for a dnsmasq `dhcp-host` reservation. The laptop rejected non-interactive sudo because interactive authentication is required.
- Deviation: The persistent reservation was not written or activated. No network state changed.
- Superseded entry: `LOG-0033` network description only; its observations about the former `10.0.0.0/24` path remain historical evidence.
- Rollback or recovery: No rollback is required. After the operator establishes a short-lived sudo credential on the laptop, write a single reservation file beneath `/etc/NetworkManager/dnsmasq-shared.d`, validate it, restart only `server-link`, and verify that `pve` reacquires `10.42.0.115` before accepting the reservation.

### LOG-0035 - Proxmox management address reserved and verified

- Timestamp: 2026-08-30T20:08:57-02:30
- Operator: Tushar Sariya on `laptop-dell-studio` and Codex over operator-authorized SSH
- Target: NetworkManager shared connection `server-link` on `laptop-dell-studio` and Proxmox bridge `vmbr0` on `pve`
- Task: 2.5
- Intended action: Persistently reserve `10.42.0.115` for the Proxmox bridge and verify management access after DHCP renewal.
- Sanitized command or UI path: Installed `/etc/NetworkManager/dnsmasq-shared.d/pve-reservation.conf`; restarted NetworkManager connection `server-link`; scheduled a one-shot `dhclient` release and renewal on `vmbr0`; verified SSH and `ansible.builtin.ping` through the configured jump host.
- Result: success
- Evidence: The root-owned reservation file maps the resolved `vmbr0` hardware address to `10.42.0.115`; active dnsmasq arguments include `--conf-dir=/etc/NetworkManager/dnsmasq-shared.d`; `server-link` is activated on `enp2s0`; `pve` reacquired `10.42.0.115/24` with default route through `10.42.0.1`; the dynamic dnsmasq lease database is empty after renewal, consistent with a static host binding; SSH identifies host `pve`; and Ansible returned `ping: pong` with no changed state.
- Deviation: The `dhclient` renewal logged `ipv4: Address already assigned` after the address had already been restored, but the one-shot service exited successfully and connectivity checks passed. The client continues to renew its lease hourly; the persistent MAC-to-IP binding, rather than lease duration, guarantees address selection. Broader task 2.5 remains incomplete pending approved guest identities, API endpoint, MetalLB exclusion, and startup order.
- Superseded entry: `LOG-0034` authentication blocker is resolved; its observed pre-change network facts remain valid.
- Rollback or recovery: Remove `/etc/NetworkManager/dnsmasq-shared.d/pve-reservation.conf` on the laptop and restart `server-link` to return `pve` to the dynamic pool. Confirm an alternate reachable address before removal because the current SSH and Ansible aliases depend on `10.42.0.115`.


### LOG-0036 - Laptop network inspection and DHCP change prepared

- Timestamp: 2026-09-12T02:59:24+00:00
- Operator: Codex over operator-authorized SSH; operator sudo action pending
- Target: `laptop-dell-studio` (`tushar-Studio-1458`), NetworkManager `server-link` on `enp2s0`; read-only inspection of `pve` through `server-10-42`
- Task: 2.5
- Intended action: Continue networking with the confirmed laptop Ethernet topology; resolve guest identities and prepare a recoverable DHCP exclusion and reservation change.
- Sanitized command or UI path: Read-only `nmcli`, `ip`, `hostname`, `qm list`, `pct list`, `pvesh get /cluster/nextid`, reservation-file and resolver reads; `nmap -sn -PR -n 10.42.0.200-254` from Proxmox; `sudo -n true` privilege check. Local `bash -n` and `shellcheck`; `scp` of the reviewed wizard to `/home/tushar/homelab-network-wizard.sh`; remote syntax and SHA-256 verification.
- Result: prepared; live DHCP mutation blocked on interactive sudo authentication
- Evidence: Laptop Wi-Fi is DHCP on `10.0.0.181`; shared Ethernet is `10.42.0.1/24`, NetworkManager 1.54.3, current dynamic range `.10-.254`. Existing Proxmox reservation remains `.115`, with gateway and DNS `.1`; both SSH paths succeeded. No Proxmox guests exist; next VM ID is 100. No ARP responders appeared in `.200-.254`. Reading the root-owned lease database and noninteractive sudo were denied, so no claim about lease absence is made. The wizard checks leases under sudo before mutation. Local and staged wizard SHA-256: `9d505ec63d60d8eb92de83827a228f43adf8b8c006389359e1437e746da5dc0e`. Bash syntax and ShellCheck passed.
- Deviation: Proposed addresses and operations are in `network-plan.md`; the router screenshot's `10.0.0.0/24` scope is upstream and does not control this Ethernet subnet. Task 2.5 remains incomplete. GPU-worker and LAN routing require verification beyond SSH ProxyJump. No DHCP, Wi-Fi, bridge, firewall or guest state was changed; only the operator wizard was staged on the laptop.
- Superseded entry: none; extends `LOG-0035` with current evidence and the next prepared action
- Rollback or recovery: Before live mutation the wizard creates `/var/backups/homelab-network.*` with prior DHCP snippets, changed NetworkManager property values and an executable rollback script. It changes only the shared Ethernet connection and preserves `.115`, with an expected brief Proxmox connectivity interruption. On failure it attempts rollback; the same script can be run from the laptop console. Until execution, remove the staged wizard to undo this session's remote file addition. Post-apply verification and an off-host copy of the generated baseline are pending.


### LOG-0037 - Active laptop DHCP and Proxmox connectivity validated

- Timestamp: 2026-09-12T12:05:26+00:00
- Operator: Codex performing read-only validation over SSH
- Target: `laptop-dell-studio` and `server-10-42`
- Task: 2.5; recovery evidence input for 2.7 and 2.8
- Intended action: Compare saved and active network state with the prepared address plan and verify traffic through the laptop.
- Sanitized command or UI path: `nmcli`, `ip`, per-interface `sysctl`, `pgrep -a -x dnsmasq`, reservation-file reads, `systemctl`, `ping`, `getent`, and HTTPS HEAD request to `https://deb.debian.org/debian/`. Added and ran `scripts/homelab-network-validate.sh`; Bash syntax and ShellCheck passed.
- Result: current configuration and connectivity checks passed; overall task remains partial
- Evidence: Saved `server-link` autoconnects on `enp2s0`, shared mode, explicit `10.42.0.1/24`, range `10.42.0.10,10.42.0.199`. Active dnsmasq matches the range and loads the reservation directory. Proxmox `.115` and all four prepared VM reservations `.220-.223` are present. Laptop Wi-Fi remains `10.0.0.181` via DHCP, default route `10.0.0.1`. Per-interface forwarding is 1 on both Ethernet and Wi-Fi even though global `ip_forward` and `conf.all.forwarding` are 0. Proxmox reaches its gateway, resolves `deb.debian.org`, and receives HTTP 200 over HTTPS. Both SSH paths pass. A root-only directory `/var/backups/homelab-network.9erF8WHt` exists; its contents have not been read or copied off-host in this session.
- Deviation: Live state now reflects the prepared wizard, but its execution was not performed or directly observed by Codex. No success claim is made about its pre-change lease checks or rollback contents. Sudo still requires interactive authentication. Fresh guest DHCP leases, privileged firewall inspection, reboot persistence, laptop Wi-Fi reservation, GPU-worker routing and off-host recovery of the new baseline remain unverified. The read-only validation script requires the existing SSH aliases and is not a fresh-machine bootstrap.
- Superseded entry: `LOG-0036` pending DHCP application is superseded by observation of active settings; its preparation and privilege evidence remains valid.
- Rollback or recovery: No live configuration changed during validation. The previously staged wizard reports its rollback location under the root-only backup directory; verify its contents before use. Do not reset forwarding based only on the global sysctl value: current per-interface forwarding and end-to-end traffic are verified.


### LOG-0038 - Proxmox storage capacity reconfirmed

- Timestamp: 2026-09-12T12:19:52+00:00 (recorded; command execution time not supplied)
- Operator: Tushar Sariya on `root@pve`; output supplied in conversation and assessed by Codex
- Target: Proxmox `local`, `local-lvm`, VG `pve` and PV `/dev/sda3`
- Task: 2.6
- Intended action: Reconfirm current storage layout, thin-pool usage and capacity against planned guest disks without allocating or modifying storage.
- Sanitized command or UI path: `pvesm status`; `df -h / /var/lib/vz`; `lsblk -o NAME,TYPE,SIZE,FSTYPE,MOUNTPOINTS`; `pvs --units g`; `vgs --units g`; `lvs -a --units g -o vg_name,lv_name,lv_size,lv_attr,data_percent,metadata_percent,lv_health_status`.
- Result: success for the storage-capacity gate
- Evidence: Both Proxmox stores are active. `local` reports 85,636,352 KiB available; `/` and `/var/lib/vz` share the root filesystem with approximately 82 GiB available. `local-lvm` reports 1,883,234,304 KiB (1,795.9921875 GiB), 0% data usage. Pool attributes are `twi-a-tz--`, metadata usage 0.15%, with no health status warning reported. Metadata and metadata spare are each approximately 15.88 GiB. VG `pve` is approximately 1,948 GiB with 16.25 GiB unallocated outside its LVs. The controller-exposed disk is approximately 1.9 TiB. Planned primary guest disks total 100 + 200 + 200 + 32 + 1,024 = 1,556 GiB, leaving 239.9921875 GiB (13.3627%) within the thin pool if fully written. EFI or other auxiliary guest volumes and snapshots must also fit within this margin; exact rendered VM allocation is checked in 3.1.
- Deviation: The 16.25 GiB VG free space is separate from free capacity inside the thin pool and must not be mistaken for total guest storage availability. This confirms LVM capacity and reported pool status, not a new physical-drive SMART or RAID integrity assessment. Retain the prior recorded RAID risk acceptance and monitoring requirements. Network backup verification was deferred by the operator, so task 2.5 and the recovery-foundation tasks remain open.
- Superseded entry: Refreshes capacity observations in `LOG-0023`; earlier evidence remains historical.
- Rollback or recovery: All supplied commands are read-only; no rollback is required. Re-run these exact commands immediately before guest allocation if storage state changes. Do not allocate beyond retained headroom or count thin provisioning as additional physical capacity.


### LOG-0039 - Root filesystem usage explained

- Timestamp: 2026-09-12T12:24:04+00:00
- Operator: Codex over operator-authorized read-only SSH
- Target: `server-10-42`, Proxmox root filesystem `/dev/mapper/pve-root`
- Task: 2.6 follow-up investigation
- Intended action: Identify the root filesystem's reported 9% usage without deleting or modifying files.
- Sanitized command or UI path: `df -B1 / /var/lib/vz`; `du -x -B1 --max-depth=1 /`; targeted `du` under `/usr`, `/var`, `/root`, `/boot`; `find` for files larger than 40 MiB in ISO and APT cache directories; `journalctl --disk-usage`; `uname -r`; `dpkg-query` installed-size inventory; `tune2fs -l /dev/mapper/pve-root` filtered to block counts and block size. No file contents or credentials were read.
- Result: success; root usage accounted for
- Evidence: `df` reports total 100,861,726,720 bytes, used 7,999,365,120 bytes (7.45 GiB), available 87,691,624,448 bytes (81.67 GiB). Directory allocation from `du` totals 7,997,202,432 bytes, within approximately 2.1 MiB of `df` used. `/usr` is 5,165,142,016 bytes, including kernel modules 2,034,003,968 bytes split almost equally between current `7.0.14-14-pve` and fallback `7.0.2-6-pve`, firmware 590,372,864 bytes and QEMU/VM firmware assets. ISO storage is 1,625,993,216 bytes for the two Talos installers and Debian installer. APT cache is 677,310,464 bytes, of which downloaded packages occupy 585,719,808 bytes. `/boot` is 250,769,408 bytes; all `/var/log` is 38,699,008 bytes; `/root` is 47,341,568 bytes. Filesystem reserved blocks are 1,258,291 at 4,096 bytes each (approximately 4.8 GiB), which are not application data and explain part of total-minus-used-minus-available and why `df` reports a rounded 9% rather than 7.93%.
- Deviation: No unexplained large usage or log growth was found. This inspected the root filesystem, not guest data in the separate thin pool. No cleanup or package removal was authorized or performed. The retained fallback kernel was established during the earlier upgrade for recovery.
- Superseded entry: none; expands LOG-0038 root-space evidence
- Rollback or recovery: All operations were read-only; no rollback is needed. Repeat the recorded inspection commands to compare future growth.


### LOG-0040 - Declarative Proxmox VM definitions validated locally

- Timestamp: 2026-09-12T12:30:06+00:00
- Operator: Codex in the repository workspace
- Target: `live/proxmox/homelab`, `config/environments/proxmox/homelab/vms.tfvars`, and deploy unit `proxmox-homelab`
- Task: 3.1
- Intended action: Prepare reproducible VM hardware definitions and validate their rendered plan without creating guests or accessing the live Proxmox API.
- Sanitized command or UI path: Read pinned provider v0.112.0 documentation; `./scripts/infra.sh proxmox-homelab init -backend=false`; `tofu fmt`; `./scripts/infra.sh proxmox-homelab validate`; `tofu -chdir=live/proxmox/homelab test -var-file=../../../config/environments/proxmox/homelab/vms.tfvars`; deploy-unit lookup; `git diff --check`.
- Result: success for task 3.1; no infrastructure created
- Evidence: OpenTofu 1.11.5, `bpg/proxmox` pinned to 0.112.0 with `.terraform.lock.hcl`. Schema validation passed. Two offline mocked-provider plan tests passed: default readiness gate rejection and approved hardware plan. Four guest IDs 100-103 and the reserved MAC/IP identities are declared, with 40 vCPUs, 156 GiB RAM, 1,556 GiB primary disks plus four EFI volumes. Definitions preserve OVMF, Q35, host CPU, VirtIO SCSI, raw local-lvm disks, fixed memory, disabled hotplug/discard, separate NAS OS/data disks, NAS CPU limit 1 and lower weight, distinct sandbox ISO and startup order. Guests default to stopped with host autostart disabled until their explicit lifecycle tasks; automatic update reboot is disabled. The deploy unit has `ci: false`. Existing AWS units and backend keys are unchanged.
- Deviation: This is a locally rendered/mocked plan, not a live API compatibility or boot test. CPU affinity and NUMA placement remain task 3.2; Talos configuration and broader validation remain 3.3/3.4. Creation remains gated on unfinished network, recovery, API/trusted-TLS and state-backend setup. No durable backend is configured; no real apply or provider credentials were used. Initial provider installation succeeded but warned that its publisher signing key is expired and may fail in future OpenTofu releases; this is documented as an unresolved clean-machine bootstrap limitation, with no signature-verification bypass. Planning and stopped defaults do not approve VM creation or waive prior prerequisites.
- Superseded entry: none
- Rollback or recovery: No live state changed. Preserve reviewed configuration, lockfile and input files in an independently recoverable Git revision before provisioning; establish encrypted state recovery before first apply. A destructive/replacement plan is blocked by lifecycle protection while the resource configuration remains present. Real guest restoration will require the later tested DR procedure, not merely these mock results.


### LOG-0041 - CPU and NUMA placement work deferred

- Timestamp: 2026-09-12T12:31:08+00:00
- Operator: Tushar Sariya (instruction in conversation), Codex (recording)
- Target: OpenSpec task 3.2
- Task: 3.2
- Intended action: Skip the proposed next CPU/NUMA placement step for now.
- Sanitized command or UI path: Operator instruction to skip following the announcement of task 3.2; added a deferral note under that task.
- Result: deferred, not complete
- Evidence: No CPU affinity or NUMA placement changes were made. Task 3.2 remains unchecked. Existing task 3.1 VM definitions are preserved; next independent preparation work is task 3.3.
- Deviation: The operator deferred implementation of this step. Permanent removal of the documented placement requirement is not inferred. Do not claim physical-core isolation or NUMA locality from the current VM definitions.
- Superseded entry: LOG-0040's proposed next action is deferred; its completed configuration and validation evidence remains valid.
- Rollback or recovery: No live configuration changed. Resume task 3.2 later or explicitly revise its placement contract before relying on a different policy.

### LOG-0042 - Reproducible Talos bootstrap configurations generated

- Timestamp: 2026-09-12T12:39:30Z
- Operator: Codex in the administrator workspace
- Target: Repository Talos inputs and private administrator files; no live node
- Task: 3.3
- Intended action: Generate the three Talos machine configurations from public patches and one reusable private secrets bundle.
- Sanitized command or UI path: `python3 scripts/homelab-talos-config.py init-secrets`; `python3 scripts/homelab-talos-config.py generate --output "$HOME/.config/aws-account-infra/talos/homelab/generated-20260912-final"`; repeat generation into `regeneration-check-20260912`; local parsed assertions and refusal checks; `git check-ignore`; official release metadata and Image Factory registry manifest GETs.
- Result: success; all three configurations strictly validate for metal mode
- Evidence: Talos CLI v1.13.9 darwin-arm64 checksum `ab4c27a959ff6c52f62c6cc2af07b22ca86ed27f1a138ed57582fa67f7b50f98` verified. Linux amd64 acquisition checksum also pinned in helper. Kubernetes v1.36.3, CNI none, kube-proxy retained, API VIP .224, Talos administration .220, install disk /dev/sda, per-node MAC aliases and DHCP, hostnames and role patches are recorded. Trusted installer index digest `sha256:c193e7aa60a2d79faf37ee73dbb8e00345028fd2aac02c6586674c6f519b0260`; sandbox `sha256:d44d70c735408a1e51d2899da72276d7f5cf3b6f071becbcb72a1d0252ea190c`. References retain the original ISO schematic IDs and v1.13.9 tag. Generated machine documents were identical across two runs reusing the bundle. File permissions were 0600; Git exclusions passed. Existing secrets, existing output directories and output within the checkout were rejected.
- Deviation: Initial local trials exposed a generated HostnameConfig auto/hostname conflict and single-output CLI path semantics. Setting auto to off and passing a worker output filename corrected both; subsequent strict validation passed. Partial trial outputs remain private and are not deployment inputs. CLI verification uses a pinned checksum, not Sigstore verification. Immutable installer digests were resolved over HTTPS; signature verification/archive recovery remains pending. Network identity and disk mappings have not been tested in running guests. Persistent cross-file checks remain task 3.4; user-volume provisioning and runtime acceptance remain unfinished.
- Superseded entry: none
- Rollback or recovery: No live infrastructure changed. Preserve and independently encrypt/back up the original talos-secrets.yaml before deployment. Restore that bundle and rerun the helper to regenerate machine configs; never recreate secrets for an existing cluster. Off-site backup, independently recoverable Git revision and full DR remain unverified. Generated files are outside Git and must remain private.


### LOG-0043 - Operator-approved two-VM revision and static validation

- Timestamp: 2026-09-12T18:38:28Z
- Operator: Tushar Sariya (approved layout), Codex (repository implementation)
- Target: OpenSpec proposal/design/spec/tasks, homelab plans, Proxmox definitions, Talos patches/generator and static validation; no live infrastructure
- Tasks: 3.1 and 3.3 revised; 3.4 completed
- Intended action: Replace four guests with a small control plane and one large worker, retain approximately 12 GiB host memory reserve, and complete the next configuration-validation step.
- Sanitized command or UI path: `tofu fmt`; `./scripts/infra.sh proxmox-homelab validate`; `tofu -chdir=live/proxmox/homelab test -var-file=../../../config/environments/proxmox/homelab/vms.tfvars`; `python3 scripts/homelab-talos-config.py generate --output "$HOME/.config/aws-account-infra/talos/homelab/two-vm-20260912"`; `uv run scripts/homelab-config-validate.py --generated-dir "$HOME/.config/aws-account-infra/talos/homelab/two-vm-20260912" --self-test`; Python compilation, shell syntax/ShellCheck, `git diff --check`, strict OpenSpec validation.
- Result: success; two mocked plan tests passed, both Talos configs strictly validated, cross-file checks and three deliberate-drift rejection tests passed
- Evidence: VM 100/control plane retains 2 vCPUs, 4 GiB RAM and 100-GiB OS disk; VM 102/shared worker now has 38 vCPUs, 172 GiB RAM and 100-GiB OS plus 1,200-GiB data disks. Total 40 vCPUs, 176 GiB RAM, 1,400 GiB primary disks plus two EFI volumes. Calculated reserve against prior observed host capacity: approximately 12 GiB RAM and 395.992 GiB thin-pool space before EFI overhead. Existing .220/.222 IP and MAC identities retained; startup order 1/2. The worker now uses the existing qemu-plus-gVisor ISO/schematic and immutable installer digest recorded in LOG-0042; control plane retains qemu-only. Worker label is workload.security/shared=true with no obsolete sandbox node taint. The original private secrets bundle was reused. Old three-node output directories are explicitly superseded and must not be applied.
- Deviation: Dedicated NAS/sandbox VM tasks 4.2/4.4/5.3 removed from active scope, not marked complete. Task 3.2 is deferred CPU/NUMA tuning and no longer a prerequisite; no physical-core reservation or isolation is claimed. Worker necessarily spans NUMA memory. Phase 6 now implements worker-local storage and backups, with 7.4 updated to test their recovery. The capacity calculation uses the previous host measurements and must be refreshed before disk creation. Network helpers now require/create only active identities; existing unused .221/.223 reservations remain untouched on the laptop. No data volume was formatted and no VM was created. Static validation does not prove boot, runtime isolation, backup recovery or host/API compatibility.
- Superseded entry: LOG-0040 four-VM hardware target, LOG-0042 three-node generation target and LOG-0041 placement gate are superseded by this approved layout; their historical execution evidence remains intact.
- Rollback or recovery: Regenerate two-node configs using the original secrets bundle and current public inputs. Preserve independent encrypted secrets, artifacts, state and reviewed Git revision before live provisioning; those recovery prerequisites remain unverified. Never deploy old generated configs merely because they still exist. No live changes require rollback.


### LOG-0044 - Two-VM network revalidation and privileged audit staged

- Timestamp: 2026-09-12T18:41:11Z
- Operator: Codex over read-only SSH; operator sudo execution pending
- Target: Ubuntu laptop gateway and Proxmox management path
- Task: 2.5, partial; no completion claimed
- Intended action: Recheck current networking and prepare remaining root-only inspection without changing network state.
- Sanitized command or UI path: `./scripts/homelab-network-validate.sh`; `ssh laptop-dell-studio 'sudo -n true'` with output suppressed and exit status reported; command availability and interface MAC inspection; shell syntax and ShellCheck for `scripts/homelab-network-root-audit.sh`; scp to `/home/tushar/homelab-network-root-audit.sh`; matching local/remote SHA-256 verification.
- Result: current-network validation passed; privileged audit staged, awaiting local sudo
- Evidence: Both active guest reservations .220/.222 present; saved/active gateway .1/24 and dynamic DHCP .10-.199; per-interface forwarding enabled; Proxmox SSH, gateway, DNS and outbound HTTPS passed. Laptop Ethernet MAC 00:24:e8:84:76:c9; Wi-Fi MAC 1c:65:9d:07:f3:73. NetworkManager 1.54.3 and nftables/dnsmasq tooling available. Local and staged audit script SHA-256: 33982a066babad07ca3d0d7d601489682b3c9592c21ebb106ff82f4b39106cc7. The script omits DHCP hostnames/client identifiers, rejects recorded lease conflicts and prints stateless firewall rules for review. No privileged execution result is available yet.
- Deviation: Passwordless sudo is unavailable; operator must authenticate locally. Router reservation, lease/firewall audit, reboot persistence, wider client/GPU routing and fresh-machine recovery remain unverified. The audit helper does not implement task 2.7 or prove full DR.
- Superseded entry: none; updates current network evidence after LOG-0043
- Rollback or recovery: No network change occurred. Only a non-secret audit script was staged in the laptop home directory and can be reconstructed from the repository. Run with local sudo and review the output before continuing network acceptance.


### LOG-0045 - Privileged gateway audit reviewed

- Timestamp: 2026-09-12T18:42:05Z
- Operator: Tushar Sariya (local sudo execution), Codex (review of supplied output)
- Target: tushar-Studio-1458, NetworkManager shared Ethernet enp2s0
- Task: 2.5, partial
- Intended action: Verify DHCP syntax, active leases and firewall forwarding/NAT rules.
- Sanitized command or UI path: `sudo bash ~/homelab-network-root-audit.sh`; output supplied in conversation.
- Result: DHCP syntax/range/lease checks passed; firewall review consistent with outbound shared-network connectivity
- Evidence: dnsmasq syntax OK; configured dynamic range 10.42.0.10-10.42.0.199; the only active lease is Proxmox 10.42.0.115 at 6c:ae:8b:52:ff:5a. NAT masquerades 10.42.0.0/24 traffic destined outside that subnet. Forwarding accepts related/established return traffic, traffic sourced from the server subnet on enp2s0 and same-interface forwarding; remaining traffic forwarded toward/from enp2s0 is rejected. The laptop INPUT chain has an accept policy and explicitly accepts DNS/DHCP on enp2s0; this is not evidence of a hardened laptop host firewall. No new guest leases are expected before creation.
- Deviation: New connections forwarded from the home LAN toward the server subnet are rejected by the shown rules; simply adding a client route will not establish external GPU-worker or general LAN access. Router reservation for laptop Wi-Fi 10.0.0.181, reboot persistence, required client routing and independent recovery remain unverified. Task 2.5 stays open.
- Superseded entry: LOG-0044 privileged-execution pending status is resolved by this output; other outstanding checks remain.
- Rollback or recovery: Audit only, no network changes. Preserve NetworkManager desired state and use its managed firewall mechanisms; do not directly edit the iptables-nft-managed tables shown in this output.


### LOG-0046 - Laptop Wi-Fi reservation confirmed by operator

- Timestamp: 2026-09-12T18:45:44Z
- Operator: Tushar Sariya (confirmation), Codex (recording)
- Target: Home-router DHCP reservation for laptop Wi-Fi 10.0.0.181
- Task: 2.5, partial
- Intended action: Resolve the outstanding address-stability question for the SSH gateway.
- Sanitized command or UI path: Operator response confirming the laptop has a reserved IP after being shown 10.0.0.181 and observed Wi-Fi MAC 1c:65:9d:07:f3:73.
- Result: reservation confirmed by operator; no router mutation or independent router inspection performed
- Evidence: Confirmation in conversation; laptop address and MAC were previously observed over SSH. The laptop Ethernet gateway remains separately configured at 10.42.0.1/24.
- Deviation: Reboot persistence, wider LAN/GPU routing and fresh-machine recovery remain unverified. Task 2.5 remains open; no prerequisite is waived by this confirmation.
- Superseded entry: Earlier router-reservation-unverified status in LOG-0044/0045 is resolved by operator confirmation.
- Rollback or recovery: No changes made. Preserve this address/MAC reservation in the router reconstruction inputs; adjust the MAC explicitly if replacing the laptop.


### LOG-0047 - Router screenshot and post-reboot network validation

- Timestamp: 2026-09-12T18:51:25Z
- Operator: Tushar Sariya (router screenshot, laptop reboot, Mac validation), Codex (review and record)
- Target: Laptop Wi-Fi reservation, Ubuntu gateway reboot and Proxmox management connectivity
- Task: 2.5, partial
- Intended action: Verify the router reservation visually and confirm current gateway configuration survives reboot.
- Sanitized command or UI path: Router Connected Devices > Devices > Edit Device; initial `sudo reboot`; advised `sudo systemctl reboot -i` after saving work; operator-supplied post-reboot `./scripts/homelab-network-validate.sh` output from the Mac.
- Result: post-reboot network validation passed; router screenshot matches desired identity
- Evidence: Screenshot shows host tushar-Studio-1458, Wi-Fi 2.4 GHz, Reserved IP selected, MAC 1C:65:9D:07:F3:73 and address 10.0.0.181. Following the reported reboot, validator confirms laptop Ethernet 10.42.0.1/24, Wi-Fi 10.0.0.181/24, gateway 10.0.0.1, dynamic DHCP .10-.199, reservations for Proxmox .115 and active desired VMs .220/.222, per-interface forwarding and SSH. Proxmox gateway/DNS .1, DNS lookup and outbound HTTPS pass. dnsmasq PID changed from 787248 before reboot to 5538 afterward. The reboot itself was operator-performed; no independent boot-ID capture was made.
- Deviation: Initial reboot was inhibited by GNOME's user session and logged-in users. The operator was instructed to save work before bypassing the inhibitor. Current-configuration reboot persistence is verified by the supplied post-reboot result; fresh guest leases, fresh-machine DR and wider-client/GPU routing remain unverified. Task 2.5 is not marked fully complete. Clarified the validator footer to distinguish standalone script coverage from accumulated manual evidence.
- Superseded entry: LOG-0046 router visual verification and LOG-0044/0045 reboot persistence pending statuses are resolved by this evidence; other outstanding checks remain.
- Rollback or recovery: No network configuration changed. Reboot interruption ended with working management/outbound access. Preserve current desired state and independent backups for the separate fresh-machine recovery tasks.


### LOG-0048 - Operator reports Tailscale on pve; roadmap and spec updated

- Timestamp: 2026-09-12T20:06:37Z
- Operator: Tushar Sariya (installation report), Codex (planning update)
- Target: Proxmox host pve remote-administration plan
- Tasks: 2.9-2.11 added, incomplete
- Intended action: Incorporate the operator-installed host-level Tailscale client into roadmap, specification, network design and recovery requirements.
- Sanitized command or UI path: Operator reports installing Tailscale on pve; edited existing roadmap/rebuild plan and OpenSpec proposal/design/spec/tasks/network plan; strict OpenSpec validation and whitespace checks.
- Result: installation recorded as operator-reported; planning updated
- Evidence: User statement in conversation. No installation command, package version, service/enrollment status, Tailscale IP/DNS identity, route advertisement or remote test output was supplied or independently inspected in this operation. No secrets recorded.
- Deviation: Installation alone does not prove remote access. New tasks require host access/policy verification, planned subnet-routing validation and independent recovery with local fallback. The two-VM allocation is unchanged; no guest Tailscale extension, third VM, laptop installation or Kubernetes operator is required by this revision. The laptop remains the physical internet gateway. External GPU node networking remains a separate acceptance requirement.
- Superseded entry: Adds the selected remote-access mechanism to the previously unresolved management path; does not supersede historical local-network evidence.
- Rollback or recovery: No live configuration changed by Codex. Preserve local SSH/console access while verifying Tailscale; document reproducible enrollment and revocation without committing auth keys or node private state. Restore access independently of Kubernetes.


### LOG-0049 - Tailscale host enrollment and local-client access verified

- Timestamp: 2026-09-12T20:09:37Z
- Operator: Codex over existing SSH and Tailscale from administration Mac
- Target: pve / 100.101.182.9 / pve.tail2f646b.ts.net
- Task: 2.9, partial
- Intended action: Inspect Tailscale enrollment and service state and test host management over the tailnet.
- Sanitized command or UI path: tailscale version/status/ip; systemctl is-active/is-enabled tailscaled; dpkg-query tailscale; filtered preference fields AdvertiseRoutes/RunSSH/WantRunning; tailscale ping; SSH with StrictHostKeyChecking and the existing 10.42.0.115 HostKeyAlias; certificate SAN/fingerprint inspection; curl using a temporary public CA file and --resolve pve:8006:100.101.182.9.
- Result: enrolled and online; ordinary SSH authentication and verified HTTPS 200 passed over Tailscale from the home-network Mac
- Evidence: Client and Debian package 1.102.4, backend Running, service active/enabled, empty health list, MagicDNS name pve.tail2f646b.ts.net and IPv4 100.101.182.9. No advertised subnet routes; Tailscale SSH disabled. Ping reached pve via the laptop uplink; SSH returned hostname pve using the known host key. Node key expiry reported 2027-03-11T19:51:59Z. Certificate fingerprint and trusted curl procedure recorded in network-plan.md.
- Deviation: Direct curl to the Tailscale IP failed certificate verification because the local Proxmox CA is untrusted by the default client and the certificate lacks the tailnet IP/DNS SAN. A second check with the CA obtained over trusted SSH and matching DNS SAN pve succeeded without disabling TLS verification. This does not resolve browser trust. No UI login, off-home access test, tailnet policy audit, package repository provenance check or Proxmox reboot test was performed. Task 2.9 remains incomplete. Subnet routing and recovery tasks remain pending.
- Superseded entry: LOG-0048 installation-only evidence expanded to verified enrollment, installed package version and home-network tailnet connectivity.
- Rollback or recovery: Read-only checks; only a temporary local public CA copy was created and automatically removed. No enrollment, firewall, routing, certificate or SSH configuration changed. Existing local access remains available.


### LOG-0050 - Operator confirms off-home UI access and trusted tailnet-only HTTPS

- Timestamp: 2026-09-12T20:28:08Z
- Operator: Tushar Sariya (configuration and browser tests), Codex (review and record)
- Target: pve.tail2f646b.ts.net, Tailscale Serve
- Task: 2.9, partial
- Intended action: Verify remote Proxmox UI access and remove the browser certificate warning using private Tailscale Serve.
- Sanitized command or UI path: Operator confirmed the UI worked following the off-home test instructions; supplied `tailscale funnel status` and `tailscale serve status` output; confirmed browser certificate warning disappeared at the DNS URL. Desired setup command: `tailscale serve --bg https+insecure://localhost:8006`.
- Result: operator-reported off-home UI reachability and valid browser HTTPS; supplied status explicitly tailnet-only
- Evidence: Both status commands show https://pve.tail2f646b.ts.net (tailnet only), proxying / to https+insecure://localhost:8006. Funnel permission was accidentally enabled by the operator, but the supplied effective service configuration is private, not public Funnel exposure. Browser access at the hostname without :8006 is reported free of certificate errors. The loopback upstream skips certificate verification; browser-facing TLS is supplied by Serve.
- Deviation: No full tailnet grants/ACL audit, off-home authenticated SSH test, Proxmox reboot persistence test or package-source verification is recorded. Task 2.9 remains incomplete for those criteria. Permission to use Funnel and actual public serving are distinct; no public endpoint is evidenced by the supplied status. Subnet routing and independent recovery remain pending.
- Superseded entry: LOG-0049 browser-trust and off-home UI reachability pending statuses resolved by operator evidence; other verification gaps remain.
- Rollback or recovery: Recreate the Serve mapping after recovering Tailscale enrollment and HTTPS prerequisites. Preserve direct local port 8006 and local SSH/console fallback. Keep the service tailnet-only and verify effective status after changes; do not rely solely on the Funnel capability setting.

### LOG-0051 - Subnet advertisement pre-action record

- Timestamp: 2026-09-12T20:30:00Z
- Operator: Codex, authorized by operator instruction to proceed with subnet routing
- Target: pve, vmbr0 10.42.0.115/24, Tailscale subnet 10.42.0.0/24
- Task: 2.10
- Intended action: Persist IPv4 forwarding and advertise the approved subnet with existing default SNAT; preserve other Tailscale preferences.
- Sanitized command or UI path: `bash scripts/homelab-tailscale-subnet.sh` on pve; helper stored in repository and staged over SSH.
- Preflight evidence: IPv4 forwarding 0; IPv6 forwarding 0; no advertised routes; NoSNAT false; connected route 10.42.0.0/24 on vmbr0. Host management reachable over existing SSH.
- Expected effect: Host becomes capable of forwarding approved tailnet IPv4 traffic to its server subnet. Tailnet route approval and policy verification remain separate. No IPv6 subnet or exit-node advertisement.
- Risk/recovery: IPv4 forwarding is host-wide; tailnet access policy and host filtering must be verified before acceptance. Prior state has no advertisements and IPv4 forwarding off. If this newly managed file did not exist, rollback is `tailscale set --advertise-routes=` followed by removal of /etc/sysctl.d/99-homelab-tailscale.conf and `sysctl -w net.ipv4.ip_forward=0`, provided no subsequent service depends on forwarding. No other configuration is changed.
- Result: pre-action record; execution result follows

### LOG-0052 - Host subnet routing configured; approval pending

- Timestamp: 2026-09-12T20:30:06Z
- Operator: Codex over authorized SSH
- Target: pve, Tailscale advertisement 10.42.0.0/24
- Task: 2.10, partial
- Action: Staged and ran the repository helper after confirming its sysctl destination did not exist.
- Result/evidence: net.ipv4.ip_forward=1, persistent /etc/sysctl.d/99-homelab-tailscale.conf installed; AdvertiseRoutes contains only 10.42.0.0/24, default subnet SNAT retained. Local SSH remains functional and Serve still reports tailnet only. Mac peer map does not yet contain the subnet route, so route approval/client acceptance are not proven. Helper passed bash syntax and ShellCheck.
- Deviation: Tailnet administration approval and scoped access-policy review still pending. No subnet reachability or guest networking success claimed. IPv6 forwarding remains unchanged. Task 2.10 remains open.
- Superseded entry: LOG-0051 pre-action record executed successfully.
- Rollback/recovery: Follow LOG-0051 rollback while no other service depends on forwarding. Rebuild from scripts/homelab-tailscale-subnet.sh and the public host sysctl desired state; reapprove the route after enrollment as needed. No credentials were added to Git.


### LOG-0053 - Approved subnet route and forwarding verified

- Timestamp: 2026-09-12T20:50:29+00:00
- Operator: Tushar Sariya (route approval), Codex (read-only validation)
- Target: Mac -> Tailscale -> pve -> laptop Ethernet 10.42.0.1
- Task: 2.10, partial
- Intended action: Verify route approval/client acceptance and real forwarding to a separate device before Talos guests exist.
- Sanitized command or UI path: Filtered tailscale status JSON; `route -n get 10.42.0.1`; SSH to tushar@10.42.0.1 with no ProxyJump/ProxyCommand and StrictHostKeyChecking using the existing 10.0.0.181 host-key alias. Reproducible helper: `./scripts/homelab-tailscale-route-validate.sh`.
- Result: route received and authenticated forwarding passed
- Evidence: pve peer PrimaryRoutes and AllowedIPs include 10.42.0.0/24. Mac route uses utun6. SSH returned tushar-Studio-1458 and connection source 10.42.0.115, destination 10.42.0.1:22, proving default SNAT and return traffic through the Proxmox subnet router. Helper syntax, ShellCheck and live execution passed.
- Deviation: Tailnet grants/ACL review and unauthorized-client denial are not verified. Test ran from the current Mac network, not a newly established off-home subnet test. Talos guests do not yet exist, so their endpoints and external GPU node networking remain untested. Task 2.10 remains open for scoped-policy validation.
- Superseded entry: LOG-0052 approval/client-route/forwarding pending statuses resolved; access-policy and runtime checks remain.
- Rollback or recovery: No live changes during validation. Keep approved route and host forwarding as recorded in LOG-0051/0052; recreate from the repository helper and tailnet approval. The validation helper depends on existing trusted SSH identity and is not a clean-machine bootstrap.


### LOG-0054 - Scoped Tailscale policy prepared for review

- Timestamp: 2026-09-12T20:58:10+00:00
- Operator: Codex, based on full policy supplied by operator
- Target: config/environments/proxmox/homelab/tailscale/policy.json; not applied to tailnet
- Tasks: 2.9/2.10, partial
- Action: Replace proposed wildcard network grant with account-scoped management ports/destinations; retain supplied Tailscale SSH check rule and omit Funnel node attribute. Add policy accept/deny assertions and an apply/recovery README.
- Evidence: Supplied policy permits wildcard source/destination/protocol, retains member-to-self SSH check, and grants member Funnel capability. Proposed policy permits tushar.sariya77@gmail.com user-owned devices to pve IPv4/IPv6 and local address on TCP 22/443/8006, laptop .1 on TCP 22, Talos .220/.222 on TCP 50000 and Kubernetes .220/.224 on TCP 6443. IPv6 pve address matches earlier observed identity. Other tailnet connections require explicit future grants. Existing local paths are unaffected by the proposed tailnet policy.
- Result: public policy file parses as JSON and whitespace checks pass; Tailscale semantic validation, saving and effective-policy tests pending
- Deviation: No remote policy was changed. User-account grants also cover other untagged devices owned by that user; not Mac-specific. Embedded tests check intended ports, not undeployed guest connectivity or denial to an independent unauthorized identity. Do not mark access-control acceptance complete until actual validation and tests pass.
- Superseded entry: Adds concrete replacement for wildcard policy discovered after LOG-0053; no live behavior superseded yet.
- Recovery: Preserve the original policy before replacing it; restore via independent Tailscale admin access if needed, noting original broad network/Funnel permissions. Re-enrollment requires rechecking pinned node addresses.


### LOG-0055 - Default tailnet policy accepted; restrictive grants optional

- Timestamp: 2026-09-12T21:05:51+00:00
- Operator: Tushar Sariya (explicit deferral), Codex (plan reconciliation)
- Tasks: 2.10 complete under revised acceptance; restrictive grants deferred
- Action: Updated spec/design/tasks/roadmap and candidate-policy README to keep current default allow-all tailnet policy. No remote policy change performed.
- Result/evidence: User elected to retain tailnet membership as the network trust boundary. LOG-0053 proves approved route, Mac client acceptance and authenticated subnet forwarding/SNAT. Combined with the supplied policy review and explicit acceptance, task 2.10's revised criteria are satisfied. Task 2.9 still has separate incomplete checks. Candidate policy remains unapplied and optional, with future review before adding other users/less-trusted devices. Public administration exposure remains outside scope; effective Serve was verified tailnet-only.
- Superseded entry: Earlier scoped-grant/unauthorized-identity-test deployment gates and LOG-0054 proposed adoption are deferred by operator. This does not claim those restrictions were implemented or tested.
- Recovery: Preserve current policy alongside recovery inputs; revisit optional hardening explicitly rather than applying the candidate automatically.

### LOG-0056 - Post-network Proxmox baseline copied off host

- Timestamp: 2026-09-12T21:05:51+00:00
- Operator: Codex over authorized SSH
- Task: 2.8, partial
- Target: pve sanitized configuration archive and administrator Mac backup directory
- Action: Added only /etc/sysctl.d/99-homelab-tailscale.conf to existing baseline script's configuration allowlist; syntax/ShellCheck passed. Ran baseline creation on pve and existing fetch/verification helper on Mac. Prior archives retained.
- Result/evidence: Created pve-empty-host-baseline-20260912T210507Z.tar.gz and copied to ~/Backups/proxmox/pve/. SHA-256 f4a72c8fb80e66b799a75843515181f86bfc1f00f6f03fdc714a344e14f1b833 matches remotely and locally. Secret-pattern scan and archive listing checks passed; network/storage/version inventory entries verified; new forwarding sysctl file confirmed with value 1.
- Deviation: Sanitized baseline excludes private credentials, Tailscale node state and Talos secrets. It is not a full restore or an encrypted off-site backup, and does not by itself capture Serve or control-plane tailnet policy. Independent backup destination/encryption and recovery verification remain pending; task 2.8 is not complete.
- Recovery: Retain this current archive and script revision with encrypted independent recovery material; restore using the still-pending fresh-machine recovery procedure. No live network/storage settings changed during capture. Local archives alone do not establish full DR.


### LOG-0057 - Dedicated AWS recovery storage planned and validated

- Timestamp: 2026-09-12T21:10:46+00:00
- Operator: Codex, following operator choice of AWS for independent backups
- Task: 2.8, partial
- Target: AWS account 992382747916, us-east-1; new deploy unit aws-staging-homelab-recovery
- Action: Inspected existing encrypted_s3_bucket module, RAG backups and account Roles Anywhere setup. AWS MCP documentation search used; run_script attempts rejected the assumed script/import interface, so authenticated AWS CLI supplied read-only account/bucket/trust-anchor inspection. No matching S3 skill was returned by MCP retrieval. Prepared a separate OpenTofu root reusing encrypted bucket/KMS modules, optional governance Object Lock input with null default for existing callers, prefix retention and separate unattached upload/restore policies.
- Result/evidence: Existing account identity confirmed and no homelab recovery bucket found. Existing homelab ECR Roles Anywhere trust anchor is enabled but no backup identity is inferred. New backend uses stacks/homelab-recovery/terraform.tfstate in existing independent S3 state bucket. Init and validate passed; AWS provider 6.64.0 pinned in lockfile. Live plan /tmp/homelab-recovery.tfplan contains 12 creates and no updates/deletes. Parsed plan confirms public-access blocking, versioning, 30-day governance retention, KMS rotation/30-day deletion window, no force-destroy, and three lifecycle rules. RAG dependency initialization with readonly lockfile and validation exercises unchanged default module caller behavior. JSON/deploy-unit and whitespace checks passed.
- Deviation: No apply or backup upload. Identity policies remain unattached pending certificate-scoped uploader and independent restore identity decisions; client encryption/key custody, restore verification and independent repository recovery remain required. Object Lock cannot be disabled after enabling; governance mode still permits explicitly authorized bypass. Initial RAG validation lacked downloaded modules; backend-disabled initialization corrected this. AWS MCP execution was unavailable through the attempted interface, not evidence AWS account access was absent.
- Recovery: Reviewed IaC creates homelab-recovery-992382747916-us-east-1, retaining bootstrap/ without automatic expiration, routine/ for 90 days and monthly/ for 365 days, with respective noncurrent retention. Keep KMS access and client decryption keys independently recoverable. Do not delete keys or assume bucket creation alone constitutes DR. No existing resources were mutated by this work; state-backend initialization and read-only planning only.


### LOG-0058 - Recovery storage PR and certificate authentication prepared for review

- Timestamp: 2026-09-12T21:38:38+00:00
- Operator: Codex, following operator request for reviewed PRs before deployment
- Task: 2.8, partial
- Target: isolated branches feat/homelab-recovery-storage and feat/homelab-recovery-identity in this repository
- Action: Opened storage PR #42 (commit 5c9536e). Prepared the dependent identity branch (commit 4eab84e) with dedicated backup CA public-certificate input, Roles Anywhere trust anchor/profile, certificate-CN/account/anchor-scoped upload role and upload-only permissions boundary. Added reproducible OpenSSL certificate issuance, renewal, identity replacement and emergency revocation procedure, plus CI tests. Operator selected the existing AWS administrator login for independent emergency restore; no additional human identity granted.
- Result/evidence: OpenTofu validation and five mock identity tests passed. Disposable offline certificate test verified encrypted CA, direct chain, expected CN, client-only extensions despite a malicious CSR, matching key, expiry and unrelated-CA rejection. TFLint, Trivy HIGH/CRITICAL, Checkov (648 passed, zero failed) and Gitleaks (118 commits with correct worktree mounts) passed. Initial mocks needed valid policy-document JSON; corrected before passing. No live certificate enrollment, production key creation, AWS apply or backup upload.
- Deviation: Task remains open pending deployed identity, live permission tests, fresh-computer administrator restore, client encryption/key custody and remaining DR acceptance. CA separation avoids inheriting the existing broadly CA-trusting ECR identity. Revocation replaces the allowed uploader CN; no per-serial CRL. Profile disable does not revoke existing STS sessions, so the runbook includes IAM active-session revocation. Tailscale Kubernetes Operator remains a post-bootstrap option; host subnet-router access stays independent and no Talos image changes were made.
- Supersedes: LOG-0057 only regarding proposed identity attachment; storage/deployment status remains unchanged.
- Recovery: Merge/review storage first and then identity. Required public CA input must accompany every plan/apply. Store signing key/passphrase independently and generate execution-host leaf keys locally. The independent AWS administrator login restores backups without requiring CA, uploader or Kubernetes. Reverting these code-only branches changes no live system.


### LOG-0059 - AWS recovery storage deployed through reviewed OpenTofu CI

- Timestamp: 2026-09-12T22:19:51+00:00
- Operator: Codex, explicitly authorized to plan and deploy through the repository CI workflow
- Task: 2.8, partial
- Target: account 992382747916, us-east-1, deploy unit aws-staging-homelab-recovery
- Action: Prior PRs #43/#44 added optional certificate identity, #46 enabled the operator-selected manual backup path with create_backup_identity=false. PR #47 enabled CI for this unit and corrected manual-deployment guidance. Reviewed all five CI plans: four existing units unchanged, recovery 12 creates/zero updates/zero deletes. Added the existing apply label under user authorization.
- Result/evidence: PR https://github.com/TusharSariyaOrg/aws-account-infra/pull/47 merged 2026-09-12T22:18:40Z. Apply run https://github.com/TusharSariyaOrg/aws-account-infra/actions/runs/34722208205 succeeded; recovery reported 12 added, zero changed/destroyed, other four units each zero changes. Created bucket homelab-recovery-992382747916-us-east-1 and KMS key arn:aws:kms:us-east-1:992382747916:key/3ea6e20e-be06-4a9a-bba0-03da7a35a3cc. Read-only AWS MCP S3/KMS calls verified versioning Enabled, all four public-access blocks true, default SSE-KMS using that enabled customer key, key rotation enabled/365 days, TLS-only deny policy, GOVERNANCE retention 30 days, routine current/noncurrent expiration 90 days, monthly 365 days, multipart abort seven days and no bootstrap expiration rule.
- Commands/UI: gh pr edit 47 --add-label apply; GitHub Actions tofu-plan and tofu-apply; AWS MCP GetBucketVersioning, GetBucketEncryption, GetPublicAccessBlock, GetObjectLockConfiguration, GetBucketLifecycleConfiguration, GetBucketPolicy, DescribeKey and GetKeyRotationStatus. MCP operations use AWS API PascalCase names; an initial snake_case STS operation failed before succeeding with GetCallerIdentity. An early read-back while apply was running returned NoSuchBucket; final checks all succeeded.
- Deviation: No Roles Anywhere resources or production certificates created. IAM upload/restore policies exist unattached; administrator login is the chosen initial upload/restore identity. No encrypted canary or actual backup uploaded; encryption-passphrase custody, independent restore test, recovery objectives and remaining DR tasks are still open. Deployment completion is not full DR acceptance.
- Supersedes: Earlier proposed/manual-only deployment status in LOG-0057/0058.
- Recovery: Desired storage is now on main and managed in the existing S3 state backend under stacks/homelab-recovery/terraform.tfstate. Use reviewed PR plans and the apply label for future changes. Object Lock cannot be disabled; governance bypass is deliberately not used. Preserve KMS/admin access. Next verify an age-encrypted canary upload/download and matching restore before uploading real reconstruction inputs.


### LOG-0060 - Encrypted AWS canary upload and restore passed

- Timestamp: 2026-09-12T22:21:59+00:00
- Operator: Codex, authorized to execute the test-file backup/restore
- Task: 2.8, partial
- Target: homelab-recovery-992382747916-us-east-1, routine/canary-20260912T222127Z-canary.JN3wsru7.txt.age
- Action: Installed age 1.3.2 with Homebrew. Verified AWS admin account 992382747916. Generated disposable age test identity, encrypted a harmless timestamped canary, uploaded with SHA-256 checksum via AWS CLI local-file transfer, downloaded the specific returned S3 version with checksum verification, compared ciphertext bytes, decrypted and compared plaintext bytes. Removed disposable private key on completion and verified absence. No production recovery secrets read or uploaded.
- Result/evidence: PASS. S3 version 7b9gdiA_m4MNkDwIsW.N4w3b6epDD.pC; plaintext SHA-256 c3a70b0f7c8c62133ae13810132cdeb773c46b95f66d9acf1b7ffaa65357dd62; ciphertext SHA-256 fc1a9ba7762204e2b4891ef57cd89b64abd30ab0b8fecd7d191962387a905159. GetObject confirmed aws:kms and GOVERNANCE retention until 2026-10-12T22:21:29.243000+00:00. Sanitized report and exact repeatable script: ~/Backups/homelab-recovery-tests/canary.JN3wsru7/report.json and reproduce.sh.
- Deviation: Used disposable public-key age encryption to avoid needing a human-selected production passphrase for a harmless canary. This is a same-Mac test using the existing admin login, not independent-machine restore or proof of real decryption-key custody. AWS CLI used for local file transfer.
- Supersedes: No previous result; adds evidence after LOG-0059 deployment.
- Recovery: Harmless ciphertext remains under routine retention; no Object Lock bypass or S3 deletion attempted. Test key was intentionally removed, so this object is not a durable recovery input. Next establish independently recoverable encryption credentials and upload/verify the actual selected Talos and host reconstruction material. Task 2.8 remains open.


### LOG-0061 - Actual recovery archive verified and off-home administration confirmed

- Timestamp: 2026-09-12T23:46:06+00:00
- Operator: Tushar Sariya (interactive backup and remote tests), Codex (receipt review, read-only host verification and record)
- Target: AWS recovery archive and pve.tail2f646b.ts.net
- Tasks: 2.8 partial; 2.9 complete
- Action/commands: Operator ran scripts/homelab-backup-manual.sh after earlier pasted-command attempts reportedly closed the terminal. Codex read the non-secret receipt. Operator confirmed authenticated UI and SSH following phone-hotspot test instructions. Read-only SSH command: apt-cache policy tailscale; systemctl is-enabled tailscaled; systemctl is-active tailscaled.
- Result/evidence: Receipt at ~/Backups/homelab-recovery/backup.PHLylb4Z/receipt.txt records bootstrap/20260912T223455Z-backup.PHLylb4Z.tar.gz.age in homelab-recovery-992382747916-us-east-1, version iNHx1NIRgZ7yitk5HvspTjjTDlJZWCwl, and PASS: encrypted backup restored exactly. Archive includes selected Talos reconstruction secrets/configurations and the sanitized Proxmox baseline. Off-home HTTPS login and ordinary SSH confirmed by operator. Installed Tailscale 1.102.4 resolves to https://pkgs.tailscale.com/stable/debian trixie/main amd64; tailscaled enabled and active. Combined with LOG-0049/0050 identity and TLS handling and LOG-0055 accepted policy, task 2.9 criteria are satisfied.
- Deviation: Terminal closure cause remains unconfirmed; failed attempts did not establish backup success. Successful backup is a same-Mac restore, not a clean-environment recovery test. Passphrase custody and independent account recovery are not inferred from S3 object presence. Service enabled state is verified; no Proxmox reboot performed. Tasks 2.7, 2.8 and 2.11 remain open.
- Supersedes: LOG-0060 actual archive upload pending; LOG-0049/0050 package-source and off-home SSH pending.
- Rollback/recovery: No live host settings changed. Preserve receipt and decryption passphrase independently. Rebuild private Serve and enrollment from recovery inputs; local SSH via gateway remains available. No secrets recorded in Git.


### LOG-0062 - Public rebuild inputs prepared for independent Git review

- Timestamp: 2026-09-12T23:50:19+00:00
- Operator: Codex, authorized to prepare a reviewed recovery-input PR
- Target: isolated branch feat/homelab-rebuild-inputs from origin/main
- Tasks: 2.7/2.8 partial
- Action/commands: Preserve the existing public Proxmox definitions, Talos patches/generator, host/network scripts, plans and OpenSpec evidence in an isolated worktree. Add docs/plans/homelab-recovery.md and offline CI validation. Keep the deployed AWS recovery unit enabled; add only the disabled Proxmox unit to the current manifest. Run OpenTofu fmt/init/validate/test, shell/Python syntax checks, cross-file Talos validation and drift self-tests, and strict OpenSpec validation.
- Result/evidence: Local Proxmox mock plans passed both readiness-gate and approved-hardware tests. Talos strict/cross-file validation passed; wrong schematic, data-disk install target and RAM drift were rejected. Linux amd64 and macOS arm64 provider checksums were acquired from the registry. File secret scan found no leaks. Review/merge and CI results belong to the resulting PR.
- Deviation: The provider publisher key is expired; current OpenTofu accepts it with a warning. No signature verification disabled. Public inputs alone do not complete clean-machine recovery. The original network wizard remains a migration helper, and recovery credentials, installer archival, objectives and full rehearsal remain open. No VM or AWS resource applied.
- Supersedes: Local-only publication status will be resolved after PR review/merge; historical execution evidence remains unchanged.
- Rollback/recovery: Review the PR and preserve its final merge revision independently with the receipt. Revert public configuration through Git if required. Private machine configs, secrets, state and archives remain outside Git.


### LOG-0063 - Proxmox API identity, independent backend and speculative plan

- Timestamp: 2026-09-13T00:06:51+00:00
- Operator: Codex, following authorization to set up Proxmox OpenTofu access and state
- Target: pve, VMs 100/102 (not created), existing AWS state bucket
- Tasks: 3.1 integration; 4.1 preparation only; 2.7/2.8 remain partial
- Action/commands: PR #48 merged at 221f143d6d550e27875dbcdc5320e2f87ee14288. Operator deferred the clean-machine restore test. Created isolated branch feat/proxmox-provider-access. AWS MCP GetBucketVersioning/GetBucketEncryption/GetPublicAccessBlock/DescribeTable verified existing backend controls. Added backend key proxmox/homelab/terraform.tfstate, preserving all AWS state keys. Ran scripts/proxmox-provider-bootstrap.py over trusted root SSH, then scripts/proxmox-tofu.py check/init/validate/plan.
- Result/evidence: Existing state bucket versioning Enabled, AES256 encryption, all public-access blocks true, tofu-locks table ACTIVE. Created homelab-tofu@pve and privilege-separated provider token, custom scoped roles and user/token ACLs. Credential captured directly into an external private mode-0600 file; no value printed. Authenticated trusted HTTPS API discovery passed; VM.Allocate present on /vms/100 and /vms/102 and absent on /vms/101. Speculative plan passed with 2 additions, 0 changes, 0 deletions; no saved executable plan. qm list remains empty and local-lvm remains 0 percent used.
- Verification: OpenTofu validation and both mock tests passed. Three offline tests exercise private token capture, overwrite refusal, error-output secrecy and suppression of inherited plan/log overrides. First bootstrap failed before user creation because mutation commands do not accept --output-format; corrected to use it only on JSON-returning calls. Removed only the verified-empty reserved output file before retrying. Initial unauthenticated HTTPS returned expected HTTP 401; authenticated calls subsequently passed. State list reports no state file, expected before first apply, rather than evidence of persisted VM state.
- Deviation: The former host_readiness_confirmed flag is now vm_creation_approved to avoid representing deferred recovery as completed. Default false blocks unapproved creation; preview helper assumes later approval only for an unsaved speculative plan and offers no apply action. Clean-machine restore remains untested. Actual provisioning permissions are not proven until an approved create. Proxmox CI deployment remains disabled; no GitHub token secret or tailnet CI enrollment configured.
- Supersedes: Prior pending API/HTTPS/backend setup in the Proxmox README; no claim that VM creation or full DR acceptance is complete.
- Rollback/recovery: Revoke the dedicated token through trusted root access if lost; reissue from the committed bootstrap without depending on old token recovery. Keep public roles/ACLs for recreation. ACCESS.md records scopes, state key and recovery order. No VM/disks allocated and no AWS bucket policy changed. Review the PR before relying on its revision.


### LOG-0064 - GitHub Proxmox CI enrollment and workflow prepared

- Timestamp: 2026-09-13T00:33:16+00:00
- Operator: Tushar Sariya (Tailscale setup and supplied OIDC identifiers), Codex (GitHub configuration and implementation)
- Target: GitHub repository TusharSariyaOrg/aws-account-infra, prod environment; pve API
- Tasks: 3.1 CI integration; 4.1 preparation only
- Action/commands: Added supplied TS_OIDC_CLIENT_ID and TS_OIDC_AUDIENCE as GitHub repository variables. Ran proxmox-provider-bootstrap.py --read-only to create an independent reader identity and proxmox-ci-secrets.py to transmit private API tokens directly into prod environment secrets. Extended existing plan/apply workflows to enroll ephemeral tagged runners and enabled the Proxmox deploy unit.
- Result/evidence: Private plan-credentials.json created outside Git with mode 0600; homelab-tofu-plan@pve!provider has audit privileges only. Local authenticated HTTPS/storage and plan/apply permission preflights both passed. GitHub lists PROXMOX_PLAN_API_TOKEN and PROXMOX_APPLY_API_TOKEN in prod. Six offline credential/permission tests, Python compilation, actionlint and strict OpenSpec validation passed. Live GitHub enrollment and plan remain to be verified in the resulting PR. No VM creation triggered.
- Deviation: The operator performs Tailscale admin changes; Codex inspected forms without saving them. OIDC subject must match repo:TusharSariyaOrg/aws-account-infra:environment:prod. Existing allow-all tailnet policy covers runner traffic; no restrictive policy was applied. prod has no required reviewers, so apply-label gating and trusted repository workflow authors are the current boundary. No permanent Tailscale secret added.
- Supersedes: Proxmox deployment-CI-disabled status in LOG-0063 once this workflow is reviewed and merged; local setup evidence remains valid.
- Rollback/recovery: Remove the apply label to prevent new deployment triggers, disable the unit through a PR if retiring CI, revoke the dedicated Tailscale trust or Proxmox tokens if compromised. Reissue tokens and update environment secrets with the committed helpers; CI.md records trust fields and recovery. S3 state keys and existing AWS deployment identities remain unchanged.


### LOG-0065 - Correct apply permission for VM startup order

- Timestamp: 2026-09-13
- Operator: Codex, following explicit authorization to fix the failed CI apply
- Target: pve apply identity and PR #50
- Tasks: 4.1/4.3 provisioning preparation; maintenance boots remain pending
- Cause/evidence: GitHub apply run 34728654173 failed both VM creates with permission check (/, Sys.Modify). Installed PVE API2/Qemu.pm explicitly checks this global privilege when a startup option is provided. The plan and previous preflight did not exercise this check; qm list remained empty.
- Action: Added HomelabTofuHost (Sys.Audit Sys.Modify) at / to the apply user and privilege-separated token, replacing their audit-only root ACL. The independent plan identity retains HomelabTofuAudit. Bootstrap and ACCESS.md now reproduce this configuration and document the host-wide permission. Existing secrets require no rotation.
- Verification: Two regression tests failed before the preflight fix; all eight access tests pass afterward. Live trusted-HTTPS preflights pass for both identities. CI now checks the root permission before applying and rejects host write access for the plan identity. Initial ACL cleanup used an unsupported delete option; corrected against installed CLI help to pveum acl delete and completed successfully. CI retry and VM creation remain pending at this revision.
- Rollback/recovery: Restore audit-only ACLs before removing HomelabTofuHost ACLs to revoke host modification. Startup-order operations would fail again. No administrator role or user/ACL-management permission was granted.


### LOG-0066 - Prepare CI-managed maintenance boots

- Timestamp: 2026-09-13T01:02:58.455874+00:00
- Operator: Codex, following authorization to start and verify both guests through CI
- Target: pve VM 100 talos-cp-01 (10.42.0.220, MAC 02:42:00:00:01:00), VM 102 talos-worker-01 (10.42.0.222, MAC 02:42:00:00:01:02)
- Tasks: 4.1 and 4.3; runtime verification pending
- Previous result: PR #50 merged at d629bfc. CI run 34729206740 created both stopped guests successfully (2 added, 0 changed, 0 destroyed); all five AWS applies were no-ops. Auto-merge initially failed with unstable status, then succeeded when only that failed job was retried.
- Action: Set started=true in both guest inputs, retaining on_boot=false and the pinned attached ISOs. Updated the existing lifecycle assertion and documented maintenance API checks in live/proxmox/homelab/README.md. No machine configuration is applied by this change.
- Verification: Require a live CI plan containing only two in-place start updates, then successful apply and read-only runtime checks. Tasks remain incomplete until evidence is recorded.
- Rollback/recovery: Before Talos installation, set started=false through a reviewed CI change to stop the guests. Retain definitions and disks; no deletion or new disk allocation is intended. Existing independent-recovery gaps remain recorded, not waived by boot success.


### LOG-0067 - Correct plan permission for existing volume inspection

- Timestamp: 2026-09-13T01:07:09.585689+00:00
- Operator: Codex, carrying out the authorized CI boot and verification
- Target: PR #51 and homelab-tofu-plan@pve user/token, VMs 100/102 only
- Failure/evidence: CI plan run 34729555107 failed volume GET calls with VM.Config.Disk denied. Installed PVE API2/Storage/Content.pm delegates to Storage::check_volume_access, whose images branch requires Datastore.Audit and VM.Config.Disk. The pinned provider offers no disk-inspection bypass; no start was attempted.
- Correction: Installed HomelabTofuPlanVM with VM.Audit, VM.GuestAgent.Audit and VM.Config.Disk on /vms/100 and /vms/102 for both user and privilege-separated token, replacing HomelabTofuReadVM ACLs. This adds real disk-configuration capability; prior strictly read-only descriptions are superseded. No VM allocation, power, host modification or datastore allocation was added. CI.md records the exact upgrade and rollback. Bootstrap now calls the mode --plan; --read-only is a compatibility alias.
- Verification: Nine offline access tests and both live token-scope preflights pass. Live plan retry remains required before apply. No machine configurations or secrets were printed.
- Rollback/recovery: Restore the old audit-only role ACLs before deleting the new plan-role ACLs. This restores strict read-only privileges but causes provider disk refresh to fail. No token rotation or host API patch was performed.


### LOG-0068 - Both maintenance boots verified

- Timestamp: 2026-09-13T01:13:06.012309+00:00
- Operator: Codex, following operator authorization for CI-managed boot and verification
- Target: pve VM 100 talos-cp-01 at 10.42.0.220 and VM 102 talos-worker-01 at 10.42.0.222
- Tasks: 4.1, 4.3 and 4.5 complete
- Action/evidence: PR #51 plan run 34729734996 showed only started=false -> true on both resources, 0 add/2 change/0 destroy. Added apply label after inspecting the successful Proxmox plan. Apply run 34729789671 succeeded and PR #51 merged. No local VM mutation was used.
- Verification: qm list reports both running. Direct maintenance API get machinestatus reports stage maintenance and ready=true on both nodes. Links show ens18 up with MACs 02:42:00:00:01:00 and 02:42:00:00:01:02; addresses match the reserved /24 IPs. Both expose /dev/sda as their 100-GiB OS disk; worker /dev/sdb is 1288490188800 bytes (1,200 GiB). QEMU Guest Agent 11.0.2 is present and qm agent ping succeeds on both; only worker has gVisor 20260810.0. Startup configuration orders are 1 then 2; host auto-start remains disabled. Sanitized qm configuration and Talos outputs are preserved in evidence/2026-09-13-maintenance-boot.txt.
- Result: Guest identities, rendered hardware, maintenance APIs, disk separation and extension separation verified. Talos machine configuration, installation and etcd bootstrap have not been performed. Earlier recovery gaps remain untested.
- Deviation: LOG-0067 records the necessary plan-token disk permission and supersedes strict read-only claims. Configured startup priority does not serialize Terraform's simultaneous explicit start operations; no claim of an observed ordered host reboot is made.
- Rollback/recovery: Before installation, deploy started=false through CI to stop guests. Rebuild using the committed two-VM definitions, pinned ISOs and laptop DHCP reservations; rerun the documented maintenance checks. Preserve disks and do not treat this boot evidence as full DR acceptance.


### LOG-0070 - Prepare Talos OpenTofu adoption and CI

- Timestamp: 2026-09-13T01:43:50.429951+00:00
- Operator: Codex, following explicit authorization to migrate Talos management to OpenTofu/CI
- Target: existing control plane 10.42.0.220; separate talos/homelab state key
- Action: Added pinned stable Talos provider 0.11.0 root, bootstrap import, no-reboot control-plane configuration adoption and disabled worker resource. Added guarded CI plan/apply through the existing GitHub Tailscale OIDC identity with subnet-route acceptance. Uploaded the existing Talos secret bundle directly to encrypted prod environment secret TALOS_SECRETS_YAML without printing it. No new CA/secrets or AWS resources were created.
- Verification: Strict OpenTofu validation and local authenticated plan passed. Plan imports the existing bootstrap and updates its metadata; configuration adoption creates one state resource that sends the exact previously installed YAML. Pinned bootstrap Update implementation only writes Terraform state and does not invoke bootstrap. Initial guard rejected this safe imported update; corrected to allow no-op/update while rejecting create. Config resource's optional on_destroy fields produced a provider null-conversion error; explicitly specifying all three fields fixed validation. Five guard tests pass. Live CI adoption/state secret-exclusion verification remains pending.
- Scope/limitations: Provider Read is a no-op; desired configuration changes are managed, but automatic live drift and OS/Kubernetes upgrades are not claimed. Initial adoption checks exact YAML fingerprint and live dry-run before no-reboot apply. Worker remains maintenance-only until a later reviewed installation. Both plan/apply have access to the existing CA bundle and are admin-capable; they are not read-only security identities. Write-only provider arguments and ephemeral variables are used to exclude secrets from state, with a post-apply check.
- Recovery: Retain the existing encrypted independent secret archive, recover the same S3 state key, and reissue GitHub secret via the committed helper. prevent_destroy, reset=false and plan guards reject destructive actions and repeated bootstrap. This migration does not claim the previously deferred full DR rehearsal or soft-reboot failure is resolved.


### LOG-0071 - CI identity transfer and pre-adoption recovery point

- Timestamp: 2026-09-13T01:51:35.119496+00:00
- Operator/target: Codex, Talos adoption PR #54, existing control plane
- Correction: Initial GitHub plan run 34731302321 rejected the transferred raw YAML's byte fingerprint. Changed transport to base64 (TALOS_SECRETS_B64) to preserve exact bundle bytes through secret storage; helper verifies the original fingerprint before upload and CI verifies it after decoding. Removed superseded TALOS_SECRETS_YAML secret. Base64 is transport encoding; encryption is supplied by GitHub environment-secret storage.
- Security validation: Full-history gitleaks flagged the public SHA-256 identity fingerprint as generic-api-key. Verified the value was a digest; .gitleaksignore excludes only the exact historical commit/file/rule/line finding. Full-history scan then passed. Six migration tests include recursive rejection of populated secret-bearing state attributes. No raw secret or plan output was uploaded.
- Recovery point: Saved private etcd snapshot pre-tofu-adoption-20260913T014802Z.snapshot, 1269792 bytes, under ~/.config/aws-account-infra/talos/homelab/snapshots on the Mac. This is off-host but is not claimed as an encrypted off-site snapshot or completion of task 5.6. Recorded current kernel boot ID outside Git for post-adoption comparison.
- CI status: An obsolete plan run remained in progress with an empty-step job and held the PR concurrency queue. Force-cancellation was requested for 34731347735; no live apply was cancelled. Adoption remains pending until the current plan and guarded apply pass.


### LOG-0074 - Prepare Cilium deployment and network acceptance through CI

- Timestamp: 2026-09-13T02:37:27.846228+00:00
- Operator/target/task: Codex following explicit operator instruction to implement Cilium; homelab Kubernetes API 10.42.0.224:6443; task 5.4.
- Action: Added Helm provider 3.3.0 and Cilium 1.20.1 release to the existing Talos OpenTofu root/state. Chart archive and CI kubectl are SHA-256 verified. Public values select Kubernetes IPAM, VXLAN, kubeProxyReplacement=false, Talos-managed BPF/cgroup mounts, permitted capabilities and one operator replica. Existing authenticated Talos access fetches a temporary kubeconfig, without new credentials or roles. Added post-apply acceptance that creates and removes a restricted temporary namespace, testing DNS, direct pod and Service traffic within/across both nodes.
- Verification: Local authenticated plan adds only helm_release.cilium; bootstrap and both machine configurations are no-op. Provider validation, seven plan/state guard tests, Helm render and workflow syntax passed. Rendered manifests contain no Secret resources and omit SYS_MODULE. Existing pod CIDRs are 10.244.0.0/24 and 10.244.1.0/24. Live installation and networking acceptance remain pending.
- Risk/recovery: Cilium changes pod networking on both nodes; VM, host, Talos maintenance and Tailscale management configuration are unchanged. Existing private pre-adoption etcd snapshot and independent original cluster-secret archive remain recovery inputs; full DR is not claimed. Preserve failed-install evidence and correct through a reviewed CI plan. Automatic Helm uninstall is disabled; deletion/replacement is rejected. No task completion is recorded until live checks pass. Hubble is not enabled in this foundation step; sandbox policy enforcement remains task 5.5.


### LOG-0076 - Defer sandbox controls and prepare verified etcd recovery bundle

- Timestamp: 2026-09-13T02:58:31.749177+00:00
- Operator/target/task: Codex, user instructed skipping sandbox controls and proceeding to next task; homelab control plane 10.42.0.220; tasks 5.5/5.6.
- Decision: Task 5.5 remains unchecked and explicitly deferred. No RuntimeClass enforcement or sandbox security claim is made.
- Action: Added reproducible snapshot preparation and --etcd mode to the existing interactive backup script. Uses existing original Talos identity, pinned Talos CLI and checksum-verified etcdutl 3.6.12. Captured a fresh local snapshot, verified embedded SHA-256, read metadata and regenerated machine configs. No restore or cluster configuration change occurred.
- Evidence: Snapshot is 6643744 bytes, revision 9047, 424 keys, database status hash 2204391907 and storage version 3.6.0. Live etcd reports protocol 3.6.12 with no errors. Private bundle is under ~/.config/aws-account-infra/talos/homelab/snapshots/post-cilium-20260913T0300Z. No snapshot contents or secrets are committed.
- Pending: Existing age passphrase must be entered by the operator locally; encryption/upload/exact-version download/decryption comparison is not yet executed. The script targets the existing retained bootstrap/etcd/ prefix and uses the admin AWS profile. Task 5.6 remains incomplete until off-site round-trip evidence is available. This does not claim a full etcd restore rehearsal.
- Recovery/rollback: Read-only snapshot acquisition requires no live rollback. Preserve original identity and independent bootstrap receipt. Keep local sensitive bundles private; successful interactive backup removes its own temporary plaintext bundle after comparison.
