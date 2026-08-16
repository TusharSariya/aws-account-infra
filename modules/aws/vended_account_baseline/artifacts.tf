locals {
  lambda_releases_bucket_name = "lambda-releases-${var.account_id}-${var.region}"
}

resource "aws_s3_bucket" "lambda_releases" {
  # checkov:skip=CKV_AWS_18:Low-volume deployment artifacts do not justify a second access-log bucket.
  # checkov:skip=CKV_AWS_144:Workloads deploy in one selected region.
  # checkov:skip=CKV2_AWS_62:GitHub Actions and CloudTrail provide publication auditing.
  # checkov:skip=CKV_AWS_145:SSE-S3 is sufficient for deployment artifacts and avoids a recurring CMK charge in every account.
  bucket = local.lambda_releases_bucket_name

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_s3_bucket_versioning" "lambda_releases" {
  bucket = aws_s3_bucket.lambda_releases.id
  versioning_configuration {
    status = "Enabled"
  }
}

#trivy:ignore:AVD-AWS-0132 Deployment artifacts use SSE-S3; per-account CMKs would create recurring cost and additional bootstrap dependencies.
resource "aws_s3_bucket_server_side_encryption_configuration" "lambda_releases" {
  bucket = aws_s3_bucket.lambda_releases.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "lambda_releases" {
  bucket                  = aws_s3_bucket.lambda_releases.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_lifecycle_configuration" "lambda_releases" {
  bucket     = aws_s3_bucket.lambda_releases.id
  depends_on = [aws_s3_bucket_versioning.lambda_releases]

  rule {
    id     = "expire-old-versions"
    status = "Enabled"
    filter {}
    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
    noncurrent_version_expiration {
      noncurrent_days = 30
    }
  }
}

data "aws_iam_policy_document" "package_trust" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]
    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github.arn]
    }
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["${local.github_sub_prefix}:environment:${var.environment}"]
    }
  }
}

resource "aws_iam_role" "github_package" {
  name               = "github-${var.service_id}-${var.environment}-package"
  assume_role_policy = data.aws_iam_policy_document.package_trust.json
}

data "aws_iam_policy_document" "package" {
  statement {
    sid       = "ListStableArtifacts"
    effect    = "Allow"
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.lambda_releases.arn]
    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values   = ["stable/${var.service_id}/*"]
    }
  }

  statement {
    sid    = "PublishStableArtifact"
    effect = "Allow"
    actions = [
      "s3:GetObject",
      "s3:GetObjectVersion",
      "s3:PutObject",
    ]
    resources = ["${aws_s3_bucket.lambda_releases.arn}/stable/${var.service_id}/*"]
  }
}

resource "aws_iam_role_policy" "package" {
  name   = "publish-stable-artifacts"
  role   = aws_iam_role.github_package.id
  policy = data.aws_iam_policy_document.package.json
}
