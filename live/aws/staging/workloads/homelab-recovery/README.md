# Homelab recovery storage

Dedicated OpenTofu deployment `aws-staging-homelab-recovery`, account
992382747916, us-east-1. Uses the existing encrypted S3 module and independent
state key `stacks/homelab-recovery/terraform.tfstate` in the existing AWS backend.
AWS plan/apply CI is disabled; deployment remains manual. The provider lockfile
pins the resolved AWS provider. No secrets belong in tfvars or Terraform outputs.

The proposed bucket is `homelab-recovery-992382747916-us-east-1`:

- Versioning, KMS encryption with key rotation and 30-day deletion window,
  public-access blocking and TLS-only bucket policy.
- Object Lock enabled with 30-day GOVERNANCE retention. Object Lock cannot be
  disabled after enabling; sufficiently privileged users can bypass governance
  retention, so this is not protection against every account-administrator action.
- `bootstrap/`: durable rebuild inputs and client-encrypted Talos secrets, no
  automatic expiration. Keep the independent decryption key outside this bucket.
- `routine/`: 90-day current and noncurrent retention.
- `monthly/`: 365-day current and noncurrent retention.
- Put etcd/, kubernetes/, applications/ and host/ subdirectories beneath the
  applicable retention prefix. Lifecycle expiration is eventual; noncurrent
  retention starts when a version becomes noncurrent, not original upload time.
- Incomplete multipart uploads aborted after seven days. No archive-class
  transition that would delay bootstrap recovery.

Upload and restore IAM policies are separate. An optional Roles Anywhere upload
role attaches the upload policy and uses it as a permissions boundary; the
restore policy remains unattached. See [identity setup and certificate lifecycle](IDENTITY.md). Neither grants deletion or Object
Lock bypass. Upload policy includes KMS Decrypt for S3 multipart upload support,
but no S3 GetObject. The uploader uses a dedicated CA, trust anchor and exact certificate CN.
The existing ECR CA and role are not reused. An independently recoverable human
restore login remains required. No long-lived
access keys are created by this deployment.

The checked-in tfvars use `create_backup_identity = false`: start with the
[manual encrypted backup procedure](MANUAL-BACKUP.md) using the existing AWS
administrator login. No CA is needed. To enable automated identity later, set
`create_backup_identity = true` and follow [IDENTITY.md](IDENTITY.md).
From the repo root:

```sh
./scripts/infra.sh aws-staging-homelab-recovery init
./scripts/infra.sh aws-staging-homelab-recovery validate
./scripts/infra.sh aws-staging-homelab-recovery plan
```

Review before apply, especially Object Lock's permanence and KMS recovery.
Creating the bucket alone does not complete disaster recovery. Pending work:
live identity enrollment and isolation checks; independently recoverable AWS login;
client-side encryption and independent key custody; encrypted upload/download
and restore test; explicit RPO/RTO; preservation of reviewed repository revision
and package/artifact inputs. CloudWatch capacity alarms have no notification
actions in the shared module; alert routing is separate work.

The shared module's new `object_lock_retention_days` defaults to null so existing
callers retain their current behavior. Never enable it on an unrelated bucket
without reviewing the irreversible change.
