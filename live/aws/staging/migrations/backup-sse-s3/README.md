# Backup encryption migration - 2026-09-24

## Applied

- The homelab-recovery and homelab-postgres bucket roots now select SSE-S3.
- The obsolete RAG backup stack was subsequently retired at the owner's request;
  see [the retirement record](../../workloads/rag/README.md).
- This one-time OpenTofu root copied all 9 current homelab backup objects in place
  using AES256, preserving metadata, tags, content type, storage class and original
  Object Lock retention. Copy preconditions required the inventoried source ETags.
- Every copied version was verified against its original using streamed SHA-256,
  metadata/tag/retention equality and HeadObject encryption metadata. Original
  versions remain intact and decryptable.
- Copy resources are then forgotten with `destroy = false`. They must not stay
  under ordinary Terraform object management: backup writers and lifecycle rules
  own their subsequent versions. The completed migration must never recreate an
  expired backup or delete a backup on destroy.

The migration backend is `migrations/backup-sse-s3/terraform.tfstate`. The original
copy configuration is retained as `objects.tf.example` for review only. The exact
source/destination version mapping and SHA-256 evidence are in the private local
`~/.config/aws-account-infra/cost-cleanup/copy-verification.json`; the input manifest
is beside it as `objects-manifest.json`. S3 state-bucket versioning also retains
pre-forget migration state. No backup content is stored in this repository.

## Legacy homelab versions

Keep the existing homelab KMS keys enabled. SSE-S3 CopyObject creates a new version;
it cannot rewrite an existing version ID. Recovery Object Lock versions remain
retained, and old homelab versions still need their keys until their references
and retention are resolved. No homelab KMS storage savings are claimed yet.

## PostgreSQL writer deployment status

The backup writer now explicitly requests AES256 for both staging upload and
multipart promotion. Its unit tests and chart tests pass. OpenTofu's Helm update
updated the live ConfigMap and CronJob, but the overall release is FAILED because
the pre-existing CNPG operator is scaled to zero and its webhook is unavailable.
The primary worker is NotReady/cordoned and apps-db is explicitly hibernated.
No maintenance settings were changed. A fresh end-to-end database backup was not
run against the hibernated database.

Once the normal wake/maintenance restoration workflow finishes, run the existing
`main_cluster_guard.require_primary_ready` preflight, then re-plan/apply
`helm_release.postgres` through the homelab OpenTofu root. Do not reuse the stale
saved plan. This work used the verified main cluster UID
`43b9d80f-4676-49c0-84ab-87d3666691dc`, reached through the documented laptop host.

Sources:
- https://aws.amazon.com/blogs/storage/encrypting-existing-amazon-s3-objects-with-the-aws-cli/
- https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/s3_object_copy
