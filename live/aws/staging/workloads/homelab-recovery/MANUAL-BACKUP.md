# First encrypted backup and restore

Use this procedure after merging the manual-backup change. The staging tfvars set
`create_backup_identity = false`, so storage can be deployed without certificates.
The existing AWS `admin` profile supplies access for both upload and restore.
The separate upload/restore policies remain available for later automation.

## Deploy storage through the reviewed CI workflow

AWS resources are deployed by OpenTofu in GitHub Actions. Review the pull request's
`tofu-plan` output, then add the `apply` label to run the existing apply workflow.
The workflow uses the repository's OIDC roles and enables auto-merge after success.
Verify the apply job succeeded before uploading backups. Creating storage does not
upload any files or prove disaster recovery.

Confirm account **992382747916** and region **us-east-1**. The fresh recovery plan
must contain no Roles Anywhere resources and no unexpected changes or deletion.
Changing the deployment manifest currently plans all enabled units; inspect those
plans too before approving apply. If an identity was previously deployed, disabling
its creation removes it; preserve creation and provide its public CA instead.

Object Lock is permanent once enabled. Its 30-day GOVERNANCE retention protects
object versions from ordinary deletion, but sufficiently privileged administrators
can bypass it.

For manual backup uploads after CI deployment, use the reviewed checkout on your
Mac and verify `aws --profile admin sts get-caller-identity`. Local OpenTofu apply
is not needed. The bucket name is fixed for this account and region below.

## Encrypt a harmless test file, upload it, and restore it

Install `age` on the Mac: `brew install age`. These are sequential commands; stop
on any error. Use a new test directory per run. Keep it outside the checkout.

```sh
umask 077
BACKUP_TEST_DIR=$(mktemp -d "$HOME/backup-restore-test.XXXXXXXX")
BACKUP_BUCKET=homelab-recovery-992382747916-us-east-1
BACKUP_TEST_KEY="routine/manual-test-$(date -u +%Y%m%dT%H%M%SZ)-$(basename "$BACKUP_TEST_DIR").txt.age"
printf 'Homelab encrypted backup restore test\n' > "$BACKUP_TEST_DIR/original.txt"
age -p -o "$BACKUP_TEST_DIR/test.txt.age" "$BACKUP_TEST_DIR/original.txt"
aws --profile admin --region us-east-1 s3 cp \
  "$BACKUP_TEST_DIR/test.txt.age" "s3://$BACKUP_BUCKET/$BACKUP_TEST_KEY"
aws --profile admin --region us-east-1 s3 cp \
  "s3://$BACKUP_BUCKET/$BACKUP_TEST_KEY" "$BACKUP_TEST_DIR/downloaded.txt.age"
age -d -o "$BACKUP_TEST_DIR/restored.txt" "$BACKUP_TEST_DIR/downloaded.txt.age"
cmp "$BACKUP_TEST_DIR/original.txt" "$BACKUP_TEST_DIR/restored.txt" && echo 'PASS: restored file matches'
```

`age` prompts for the encryption passphrase without putting it in command history.
Save that passphrase in an independently accessible password manager **before**
uploading real recovery material. S3/KMS encryption does not replace this passphrase;
your AWS login alone cannot decrypt an age archive. The canary is harmless and can
expire through the `routine/` lifecycle; no deletion test or retention bypass is needed.

## Back up real recovery inputs only after the canary succeeds

Build an archive in a private directory outside Git from explicitly selected Talos
secrets/configuration and host-baseline files. Do not sweep the entire home directory.
Encrypt the archive with `age -p` before uploading. Durable reconstruction inputs go
under `bootstrap/` (no automatic expiration), not `routine/`. Preserve a manifest of
source filenames, capture time, reviewed Git revision, object key/version and checksum
without including secret contents. Retain the encryption passphrase independently.

Download, decrypt and inspect the archive into another private directory. Finally
repeat the restore from a clean administration environment using the independently
recovered AWS login and passphrase. A same-Mac canary proves the basic data path, not
full disaster recovery. Before declaring DR ready, finish independent credential
recovery, off-site preservation and the platform restore rehearsal.

No backup scheduler or certificate service is required for this first manual path.
Source: [age encryption tool](https://github.com/FiloSottile/age).
