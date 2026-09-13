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
   checks and review a fresh plan before live provisioning. The default readiness flag remains false and GitHub CI can deploy Proxmox using the reviewed apply-label workflow;
   see the CI setup guide for identity recovery. Rebuild the control plane, then shared worker, then CNI and
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


## Foundation etcd backup

After the cluster and Cilium are installed, run from a Mac checkout:

```bash
python3 scripts/homelab-backup.py backup --mode etcd
```

Requires Python 3, aws, age and the existing private Talos identity/config under
~/.config/aws-account-infra/talos/homelab. The helper supports macOS arm64 and
Linux amd64 and verifies pinned Talos CLI and etcdutl 3.6.12 downloads.

The script captures a fresh consistent etcd snapshot, checks its embedded SHA-256
and reads metadata with etcdutl. It packages the original Talos secret bundle,
regenerated machine configs, public Cilium/Talos reconstruction inputs and a
metadata file identifying the Git revision and Terraform state keys. It uses the
existing admin AWS profile and checks account 992382747916 before proceeding.

Enter your independently saved age passphrase locally when prompted. The script
encrypts the archive, uploads to bootstrap/etcd/ in the existing recovery bucket,
downloads that exact S3 object version, prompts again to decrypt, and compares
all archive bytes. It does not restore into or change the live cluster. Save the
receipt and metadata independently with the earlier bootstrap receipt.
bootstrap/ is the existing retained foundation prefix; scheduled etcd backups use the separately managed etcd/ prefix below.

The output directory under ~/Backups/homelab-recovery is private. Temporary tar
files are removed on exit; the plaintext snapshot/config bundle is removed on success or failure.
Only encrypted files and sanitized receipts are retained.
This verifies backup transport and decryption, not an isolated etcd restore or
full disaster recovery. Application volume data and Terraform state contents are
not included; their independent backup/recovery paths remain necessary.

For preparation without encryption or upload:

```bash
python3 scripts/homelab-backup.py capture --output "$HOME/Backups/new-etcd-bundle"
```

Use a new directory outside Git. Treat the entire bundle as sensitive. Snapshot
metadata contains only identifiers, counts, revisions and digests.


## Daily unattended etcd backups

The main-branch `homelab-etcd-backup` workflow runs daily at **06:17 UTC**, or
manually from Actions. The Mac may be off; Proxmox, the gateway laptop and the
Talos control plane must be reachable. GitHub schedules are best effort.

The workflow validates a snapshot, encrypts to the public key in
config/environments/talos/homelab/backup-recipient.txt and writes a new S3 version
of **etcd/latest.tar.gz.age**. The dedicated homelab-etcd-backup role has no delete
or retention-bypass permissions. It reads back the exact version and compares
ciphertext before publishing a success heartbeat. Raw archives and credentials
are temporary private files, never Actions artifacts. The existing prod Talos CA
secret remains admin-capable; this is not a read-only Talos security identity.

The age private identity is initially stored at
~/.config/aws-account-infra/recovery/etcd-age-key.txt (0600). Save that file in an
independent recovery location before relying on automated backup recovery. Never
put it in Git, GitHub secrets or the same backup it decrypts. The original
passphrase-encrypted bootstrap backup remains separately recoverable with its
original password. Key rotation requires retaining old identities until their
backup versions expire and testing the replacement before publishing its public
recipient.

Terraform manages the `etcd/` lifecycle rule: old versions expire **30 days after
becoming noncurrent**; the latest current version **never expires**. Deletion is
asynchronous and honors Object Lock. A failed schedule cannot age out the last
backup. Existing bootstrap, routine and monthly prefixes retain their previous
rules. Do not configure a current expiration for etcd/ or manually delete the
latest object (which would create a delete marker).

CloudWatch `homelab-etcd-backup-stale` watches approximately 30 hours of missing
success heartbeats and routes ALARM/OK changes to the existing account security
alerts topic. Multi-day alarms evaluate hourly. Initial alarm state may be
ALARM until the first verified backup. Confirm the topic's email subscription
and periodically rehearse decryption; automated readback does not prove private
key custody or a full cluster restore.

To recover, use your independent AWS admin login to download the exact VersionId
from the successful workflow receipt, then decrypt locally using:

```bash
age -d -i "$HOME/.config/aws-account-infra/recovery/etcd-age-key.txt" \
  -o restored.tar.gz downloaded.tar.gz.age
```

Use a private directory outside Git. Inspect member names before extraction and
verify snapshot-metadata.json and the embedded snapshot hash. Never restore over
a live cluster merely to test a backup. Restore drills remain separate tasks.

## Unified recovery command

`scripts/homelab-backup.py` owns capture, packaging, encryption, exact-version
upload/readback and independent verification. `backup --mode daily` is the CI
entry point; `backup --mode bootstrap` retains the original dated host/identity
backup; `backup --mode etcd` creates an interactive foundation snapshot. Older
script names remain compatibility wrappers while callers migrate.

To check a previously uploaded daily backup, save its JSON receipt from the
successful workflow log (omit the trailing PASS line from older runs), then run:

```bash
python3 scripts/homelab-backup.py verify \
  --receipt /path/to/receipt.json \
  --identity "$HOME/.config/aws-account-infra/recovery/etcd-age-key.txt"
```

For an older passphrase backup, use its `receipt.txt` and omit `--identity`;
age prompts locally. The verifier reads the recorded S3 version using the admin
profile, checks any recorded ciphertext digest, decrypts privately, and recognizes
the existing daily `homelab/`, foundation `./`, and bootstrap home-relative layouts.
Snapshot verification checks the original identity fingerprint, embedded checksum,
metadata digest and etcdutl status. This does not perform a cluster restore.

Manual backups retain both a JSON receipt and the compatible text receipt. The
schedule, age recipient, IAM permissions, heartbeat and S3 retention are unchanged.
Rollback consists of reverting this refactor commit; existing backup objects and
receipts need no conversion. Removal of compatibility wrappers and the complete
operational parity rehearsal remain task 8.5.
