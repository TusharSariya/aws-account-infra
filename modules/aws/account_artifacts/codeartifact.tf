resource "aws_codeartifact_domain" "infra" {
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
