# RAG image publishing and retired backups

The owner retired the old RAG server and authorized deletion of its AWS backups
on 2026-09-24. This root now retains only ECR repositories (empty by default) and
the existing GitHub image-publishing role. It will not recreate backup resources.

OpenTofu applied the reviewed retirement plan (13 resources destroyed):

- `rag-backups-992382747916-us-east-1`, including all object versions and delete markers.
- `rag-backup-catalog` DynamoDB table and its index.
- Dedicated `rag-backup` IAM user, access key, and inline policy.
- Backup bucket alarms and configuration.
- Dedicated KMS key `5e153b8e-f4f6-4419-aae9-bb8fdb4fab9f`, scheduled for deletion
  on 2026-10-01 at 16:56 UTC after its existing seven-day waiting period.

Before removing the bucket module, a separate reviewed OpenTofu apply set only
its `force_destroy` state attribute to true. The subsequent deletion plan used
that state to purge the versioned bucket. This temporary option is absent from
the final shared module; other buckets retain their existing deletion protection.
The backend remains `stacks/rag/terraform.tfstate`; no state was moved or discarded.

The old desktop hostname and address are retired. The new Ubuntu desktop,
`ubuntu-gpu-01` at `10.0.0.226`, was already running. Its inspected locations and
system/user services contain no old RAG installation, consistent with the owner's
confirmation. No server was recreated or rebooted for this cleanup.

Post-apply AWS reads confirm the bucket and catalog are absent and the key is
`PendingDeletion`. The RAG root's follow-up plan has no changes.
