resource "aws_codeartifact_domain" "infra" {
  # checkov:skip=CKV_AWS_221:Owner requested AWS-managed KMS encryption to avoid customer-key fees; packages stay encrypted, with same-account consumers.
  domain = "aws-account-infra"
  # Omit encryption_key to use the AWS-managed aws/codeartifact key.
}

resource "aws_codeartifact_repository" "sdk_candidate" {
  repository  = "sdk-candidate"
  domain      = aws_codeartifact_domain.infra.domain
  description = "PR candidate SDK packages. Not for production consumers."
}

resource "aws_codeartifact_repository" "sdk_stable" {
  repository  = "sdk-stable"
  domain      = aws_codeartifact_domain.infra.domain
  description = "Stable SDK packages published apply-before-merge via environment sdk."
}
