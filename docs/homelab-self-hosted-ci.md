# Homelab GitHub execution

Status: implementation in progress. No CI manager VM, live worker resize, isolated runner job or workflow migration has been verified. The GitHub App registration is separate from activation. Unchecked OpenSpec tasks remain authoritative.

GitHub retains repositories, Actions orchestration, protected environments, artifacts and merge checks. A dedicated Ubuntu 24.04 VM runs one fresh nested KVM guest per job. It is independent of Talos, but shares Proxmox hardware and the upstream network. No physical high availability is claimed.

## Capacity and activation

The opt-in `ci_runner_enabled` variable creates VM 103, `ci-runner-01`, with 4 vCPU, 16 GiB RAM and a 100 GiB disk, and reduces `talos-worker-01` RAM from 172 to 156 GiB. Worker CPU, both worker disks and control-plane resources remain unchanged. Total assigned RAM remains 176 GiB; vCPU and primary disk budgets become 44 and 1500 GiB. `ci_runner_ssh_public_key` accepts only the administrator's public key.

Keep the original Proxmox S3 backend, DynamoDB locking and provider lockfile. Before activation, verify VM 103, MAC `02:42:00:00:01:03` and DHCP address `10.42.0.223` are unused, review the exact saved plan, stop AI and arrange worker maintenance. Pi-hole may be unavailable during that worker restart. Verify actual post-restart memory, Talos readiness, retained data and UDP/TCP DNS before starting CI.

`scripts/ci-runner-host-prepare.sh` grants the existing plan/apply identities access to VM 103 and grants only the apply identity permission to download the pinned Ubuntu image. Run through verified root SSH to pve. `scripts/ci-runner-network-prepare.py` adds the CI reservation on the existing NetworkManager DHCP router; activate it through the existing network maintenance procedure. Neither recipe changes existing disks.

## Manager and credentials

Apply `ansible/playbooks/ci-manager.yml` using `ANSIBLE_CONFIG=ansible/ansible.cfg` and a private inventory with only the `ci_manager` host. It installs libvirt/KVM, the reviewed manager, isolated NAT network and systemd services. It does not generate or embed secrets in OpenTofu.

The GitHub App is private to TusharSariyaOrg and must be installed only on `aws-account-infra`. Repository Administration write permission is required by GitHub's repository JIT registration API; it is broader than runner registration, so the signing key must remain on the manager. Metadata read is mandatory. Do not grant Contents, Secrets, Workflows or organization administration permissions. The manager exchanges its signing key for short-lived installation tokens. Each guest receives only its own JIT configuration and normal GitHub job credentials.

Root-owned `/etc/homelab-ci/config.json`, mode 0600, contains `repository`, `app_id`, `installation_id`, `app_key`, `image`, and `image_sha256`. The key itself is another root-owned 0600 file. Never commit either file or paste credentials into logs/chat. Install the App only on the one repository and retain disabled fork workflows and disabled repository forking.

## Image and operations

Build the image on the manager with `sudo python3 /opt/homelab-ci/image.py`. The Ubuntu release and runner archives are checksum-pinned. Image preparation installs OS packages from Ubuntu repositories; byte-for-byte future rebuild reproducibility is not claimed. The build receipt records the exact output digest and setup script digest. Enroll that digest before activation. Rebuild for security updates and renew the runner binary pin before GitHub stops accepting it.

The manager requires nested `/dev/kvm`, a matching image digest, installed firewall and at least 20 GiB free with filesystem usage below 80 percent. Jobs have a 70-GiB virtual disk and 14 GiB RAM inside the manager's 16-GiB budget. No job disk or Docker cache survives cleanup. Guest disk bounds and manager pressure checks do not reserve physical thin-pool capacity.

Use `sudo python3 /opt/homelab-ci/manager.py pause`, `resume` or `status`. Pause stops replenishing guests while the current guest finishes. A single JIT runner may wait for a job. Completion, failure or cancellation removes its guest and overlay; manager recovery removes surviving guests before creating another. Failure to destroy or deregister blocks replacement. A six-hour absolute guest lifetime bounds abandoned guests. Jobs retain their shorter workflow timeouts.

The guest network permits Internet access and local DHCP/DNS, denies other manager access and direct private/LAN addresses. Deployment jobs enroll with their existing Tailscale credentials; connectivity must be verified from the actual guest. Do not mount manager paths or its Docker socket into guests. Privileged quota tests run only inside the disposable guest.

## Workflow migration and rollback

Every executable job uses `[self-hosted, Linux, X64, homelab-linux-x64]`. GitHub still supplies per-job tokens, OIDC and protected environment credentials. No hosted fallback is automatic. Preserve plan-gate/apply-gate names and failure/cancellation handling. ARM image and package targets remain ARM using QEMU inside the x64 guest; test artifacts on ARM before claiming parity.

Bootstrap and repair remain available from the administration machine, independent of the runner. Pause admission before image or manager maintenance. Restore configuration and independently reissued credentials; never restore old job disks. Removing the runner from service leaves GitHub jobs queued or failed, never falsely successful. Returning to paid hosted labels requires an explicit operator decision.

Deliver foundation, manager and routing as separate review PRs. A locally applied assembled tip requires a fresh CI drift check. Never apply an intermediate review branch against the already upgraded cluster or claim the tip's check result belongs to another commit.
