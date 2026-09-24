# CodeArtifact encryption and GuardDuty cost reduction

The owner requested AWS-managed CodeArtifact encryption and suspension of GuardDuty.
This follows the homelab historical-backup/key retirement in the same PR.

## CodeArtifact cutover

The domain `aws-account-infra` and repositories `sdk-candidate` and `sdk-stable`
retain their names, ARNs and package endpoint URLs. CodeArtifact cannot change a
domain's encryption key in place. Before replacement, exported all 40 published
npm/PyPI package versions (60 assets), verified each asset against CodeArtifact's
SHA-256 hash, and captured npm distribution tags. No SDK publish job was running.
Private exports and verification tooling are retained outside Git under
`~/.config/aws-account-infra/codeartifact-migration/`.

Applied the account root's reviewed saved plan with explicit one-time `-replace`
for `module.artifacts.aws_codeartifact_domain.infra`,
`module.artifacts.aws_codeartifact_repository.sdk_candidate` and
`module.artifacts.aws_codeartifact_repository.sdk_stable`. Repository replacement
is not a permanent lifecycle trigger. Future ordinary plans must be no-ops.

The domain omits `encryption_key`, selecting AWS's managed key. The existing
`kms_key_arn` module output now reports the domain's actual encryption key so SDK
publish and Lambda-package roles retain scoped access to the correct key.
The old customer-managed key and alias were removed through OpenTofu. AWS confirmed
`PendingDeletion`, scheduled for October 24, 2026 at 20:28 UTC; key storage charges
stop during the waiting period.

## GuardDuty

Set the existing detector's `enable` to false. AWS confirmed `DISABLED`. This
suspends monitoring and billing while retaining detector configuration and existing
findings. Optional protection plans were already disabled and there were no S3
malware protection plans. Other account logging and security alerts are unchanged.

## Validation

All 40 versions were republished. Post-cutover verification matched the SHA-256
hash of every asset and the original npm distribution tags. The ordinary account
plan reported no changes; validation, formatting, the 8 homelab backup tests and
LocalStack smoke passed. CI must pass before merge. Do not replay the replacement
plan: the restored package repositories are live.
