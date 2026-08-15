# Private SDK packages. Two repositories so a PR build cannot float into
# production installs. Candidate is not an upstream of stable.

data "aws_iam_policy_document" "codeartifact_kms" {
  # checkov:skip=CKV_AWS_111:KMS key policies must use Resource *; this document is attached only to aws_kms_key.codeartifact
  # checkov:skip=CKV_AWS_356:Same as CKV_AWS_111 — KMS key policy resource is always *
  # checkov:skip=CKV_AWS_109:Root kms:* is the IAM passthrough for this CMK; CodeArtifact is encrypt/decrypt only
  statement {
    sid    = "EnableRoot"
    effect = "Allow"
    principals {
      type        = "AWS"
      identifiers = ["arn:aws:iam::${var.aws_account_id}:root"]
    }
    actions   = ["kms:*"]
    resources = ["*"]
  }

  statement {
    sid    = "AllowCodeArtifact"
    effect = "Allow"
    principals {
      type        = "Service"
      identifiers = ["codeartifact.amazonaws.com"]
    }
    actions = [
      "kms:Encrypt",
      "kms:Decrypt",
      "kms:GenerateDataKey",
      "kms:DescribeKey",
    ]
    resources = ["*"]
  }
}

resource "aws_kms_key" "codeartifact" {
  description             = "CodeArtifact domain aws-account-infra"
  deletion_window_in_days = 30
  enable_key_rotation     = true
  policy                  = data.aws_iam_policy_document.codeartifact_kms.json
}

resource "aws_kms_alias" "codeartifact" {
  name          = "alias/codeartifact-infra"
  target_key_id = aws_kms_key.codeartifact.key_id
}

resource "aws_codeartifact_domain" "infra" {
  domain         = "aws-account-infra"
  encryption_key = aws_kms_key.codeartifact.arn
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
