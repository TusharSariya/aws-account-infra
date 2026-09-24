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
  versions were initially retained, then deleted in the separately authorized
  retirement described below.
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

The owner subsequently authorized deletion of all 19 noncurrent KMS-encrypted
homelab versions and retirement of their two dedicated keys. The nine current
SSE-S3 objects remain. See [the retirement record](../../workloads/homelab-recovery/README.md#kms-retirement---2026-09-24).
The private migration manifest contains historical source IDs that no longer exist.
Do not replay the example copy configuration.

## PostgreSQL writer deployment status

The backup writer explicitly requests AES256 for both staging upload and multipart
promotion. After normal coordinator restoration of the primary server, GitHub CI
successfully reconciled the initially failed Helm upgrade. PostgreSQL reported
`deployed`, and all deployment and acceptance gates passed before PR #219 merged.

Sources:
- https://aws.amazon.com/blogs/storage/encrypting-existing-amazon-s3-objects-with-the-aws-cli/
- https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/s3_object_copy
