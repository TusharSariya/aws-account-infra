# Homelab recovery entry point

This guide and the linked desired state preserve the current two-VM build. They
are reconstruction inputs, not evidence of a completed full disaster recovery
rehearsal. No Talos VM has been created. OpenSpec tasks 2.7 and 2.8 remain open.

## What is recoverable today

| Input | Independent location | Verification |
| --- | --- | --- |
| Public configuration, scripts, implementation log | This repository, at the reviewed merge revision of this PR | PR #48 merged as 221f143d6d550e27875dbcdc5320e2f87ee14288; preserve the revision with the receipt |
| Original Talos secrets, two generated machine configs and talosconfig | Encrypted S3 bootstrap archive identified by the saved receipt | Same-Mac download, decryption and byte comparison passed |
| Sanitized Proxmox empty-host baseline | Inside the same encrypted archive | Archive inspection and checksum verified; not a full Proxmox backup |
| Encryption passphrase | Operator's independently accessible password manager | Independent account recovery and fresh-environment decryption still need verification |
| AWS recovery access | Existing AWS administrator login, account 992382747916 | Current administrator access verified; fresh-environment authentication still needs verification |

The current receipt is `~/Backups/homelab-recovery/backup.PHLylb4Z/receipt.txt`
on the original Mac. Save its contents independently, along with the reviewed
Git commit. It contains an S3 bucket/key, version ID and restore result, not the
passphrase. The archive is at:

```text
s3://homelab-recovery-992382747916-us-east-1/bootstrap/20260912T223455Z-backup.PHLylb4Z.tar.gz.age
Version: iNHx1NIRgZ7yitk5HvspTjjTDlJZWCwl
```

The backup bucket is managed by the existing OpenTofu CI workflow. See
[manual backup](../../live/aws/staging/workloads/homelab-recovery/MANUAL-BACKUP.md)
for encryption and retention. Do not redeploy the bucket as a restore step.

## Clean administration environment

Use an isolated macOS arm64 or Linux amd64 environment. Recover access to the
password manager, GitHub and AWS independently of the laptop, Proxmox, and future
Kubernetes services. Do not remove or overwrite working credentials as a test.

Install Git, Python 3.9+, uv, OpenTofu 1.11.5, AWS CLI v2 and age 1.3.2 from their
official distributions. The Talos generation helper downloads and checks the
pinned CLI itself. Package installation and recovery access have not yet been
rehearsed on a fresh machine. Preserve official installer verification inputs
when completing that rehearsal; current Internet availability is not an archive.

Clone this repository and check out the reviewed commit recorded independently
with the receipt:

```bash
git clone https://github.com/TusharSariyaOrg/aws-account-infra.git
cd aws-account-infra
# Set this to the reviewed commit from your recovery record.
git checkout --detach "$RECOVERY_COMMIT"
```

Authenticate the AWS CLI with the existing administrator's independently
recoverable credentials under profile `admin`. Do not create or share long-lived
keys just for this guide. The account identity check is:

```bash
aws --profile admin sts get-caller-identity --query Account --output text
```

The result must be `992382747916`. For the first fresh-environment restore, use
the saved receipt to download its exact S3 object version into a new private
directory outside this checkout. Decrypt using age and the independently saved
passphrase. Inspect archive member names before extraction; extract only into
that private directory, never directly over a home directory or a running host.
Compare the restored files privately with the recorded inventory and baseline
checksum. Do not paste YAML, keys or decrypted contents into CI logs or PRs.
Record the result and elapsed time in the implementation log.

For cluster recovery, restore the original `talos-secrets.yaml`; **do not run
`init-secrets` for an existing cluster**. See the
[Talos configuration procedure](../../config/environments/proxmox/homelab/talos/README.md)
for modes, private paths and regeneration. The backup helper
`scripts/homelab-backup-manual.sh` packages the explicitly dated bootstrap inputs;
it is not a recurring backup service or a generic restore command. Run shell
helpers as separate `bash script.sh` processes, not with `source`.

## Rebuild dependency order

1. **Administration and identity:** recover the reviewed repository, AWS access,
   password manager and encrypted inputs. Restore or reissue SSH keys, adding
   public keys through trusted local consoles. Verify host fingerprints locally
   before trusting replacement hosts; do not disable host-key checks.
2. **Gateway laptop:** recover Ubuntu, Wi-Fi Internet access and its router
   reservation; reconstruct NetworkManager shared Ethernet and dnsmasq state.
   [network-plan.md](../../openspec/changes/build-talos-proxmox-homelab/network-plan.md)
   records addresses, NICs, DHCP exclusions and validation. A replacement NIC
   requires an explicit MAC/interface update. `homelab-network-wizard.sh` is the
   original migration helper and intentionally refuses existing guest
   reservations. It is not yet a fresh-machine or repeatable reconciliation
   tool. Do not run it blindly as a restore.
3. **Proxmox host:** use the recorded hardware/storage layout, installed versions
   and verified artifact identities in the
   [implementation log](../../openspec/changes/build-talos-proxmox-homelab/implementation-log.md).
   Inspect the replacement array before installation or disk allocation. The
   baseline intentionally omits private Proxmox/SSH state and is not a full
   `/etc/pve` restore. Host installation, account reissuance and storage
   reconstruction still need an isolated rehearsal.
4. **Private remote access:** re-enroll the recovered host in Tailscale using
   independently recovered administrator access; revoke the lost device.
   Recreate private Serve, subnet advertisement/approval and forwarding. Keep
   local console/SSH access. See the network plan and
   [Tailscale policy notes](../../config/environments/proxmox/homelab/tailscale/README.md).
   The candidate restrictive policy is optional and unapplied. Enrollment,
   expiry recovery and local fallback are still task 2.11.
5. **Guests and cluster:** validate the
   [Proxmox definitions](../../live/proxmox/homelab/README.md) and restored Talos
   identity. The [API and state setup](../../live/proxmox/homelab/ACCESS.md) now supplies
   a scoped identity and separate S3 backend key. Finish remaining readiness
   checks and review a fresh plan before live provisioning. The default readiness flag remains false and cloud CI does not
   deploy Proxmox. Rebuild the control plane, then shared worker, then CNI and
   sandbox controls using the OpenSpec sequence.
6. **Persistent state:** once deployed, recover etcd and application-consistent
   worker backups using the later phase procedures. The current bootstrap
   archive contains neither etcd snapshots nor application data.

## Acceptance still required

- Public inputs merged in PR #48; retain its merge commit independently.
- Finish clean-machine laptop bootstrap and repeatable reconciliation, including
  SSH setup without pre-existing aliases (task 2.7).
- The operator deferred the clean-machine restore test. Independent administrator
  and passphrase recovery remain untested; preserve installer
  inputs, and agree measurable recovery-time/data-loss objectives (task 2.8).
- Complete address availability and guest/GPU networking checks (task 2.5).
- Verify Tailscale re-enrollment, expiry recovery and local fallback (task 2.11).
- Exercise recovery in isolation and record achieved results; do not mark these
  complete merely because files are in Git or S3.
