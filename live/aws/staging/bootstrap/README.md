# bootstrap

Creates the remote-state backend (S3 bucket + DynamoDB lock table) that every other
stack uses. This is the chicken-and-egg step: it runs with **local** state because the
backend doesn't exist yet.

```bash
AWS_PROFILE=admin tofu init
AWS_PROFILE=admin tofu apply
```

This produces:
- S3 bucket `tofu-state-992382747916-us-east-1` (versioned, encrypted, public-blocked)
- DynamoDB table `tofu-locks` (LockID hash key, on-demand)

The resulting `live/aws/staging/bootstrap/terraform.tfstate` is local and gitignored. It rarely changes,
so leaving it local is fine. (Optional: add a `backend "s3"` block here too and
`tofu init -migrate-state` to push it into S3 — note `prevent_destroy` on the bucket.)

**Never run this stack in CI.**
