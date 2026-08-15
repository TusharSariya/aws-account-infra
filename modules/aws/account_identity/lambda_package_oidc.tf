# Account-level Lambda zip releases. PRs write candidate/<name>/<sha>.zip;
# main writes stable/<name>/<sha>.zip. Live Lambdas pin a stable key in tfvars.
# Reads upace from CodeArtifact sdk-stable.

locals {
  lambda_releases_bucket_name = "lambda-releases-${var.aws_account_id}-${var.region}"
  lambda_releases_bucket_arn  = "arn:aws:s3:::${local.lambda_releases_bucket_name}"
  lambda_package_subs = {
    candidate = ["${local.github_sub_prefix}:pull_request"]
    stable    = ["${local.github_sub_prefix}:ref:refs/heads/main"]
  }
}

resource "aws_s3_bucket" "lambda_releases" {
  # checkov:skip=CKV_AWS_18:Access logs for a few Lambda zips are not worth a second bucket.
  # checkov:skip=CKV_AWS_144:Cross-region replication is unused for personal deploy artifacts.
  # checkov:skip=CKV_AWS_145:AES256 is enough for personal Lambda zips; a dedicated CMK would add a monthly KMS charge.
  # checkov:skip=CKV2_AWS_61:Lifecycle below expires old versions; a catch-all current-object expire would delete the live zip.
  # checkov:skip=CKV2_AWS_62:Event notifications are unused for a tiny artifact bucket.
  bucket = local.lambda_releases_bucket_name
}

resource "aws_s3_bucket_versioning" "lambda_releases" {
  bucket = aws_s3_bucket.lambda_releases.id
  versioning_configuration {
    status = "Enabled"
  }
}

#trivy:ignore:AVD-AWS-0132 AES256 is enough for personal Lambda zips; a dedicated CMK would add a monthly KMS charge.
resource "aws_s3_bucket_server_side_encryption_configuration" "lambda_releases" {
  # checkov:skip=CKV2_AWS_67:AES256 is enough for public SDK wheels plus this booker; a dedicated CMK would add a monthly KMS charge.
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
      noncurrent_days = 14
    }
  }
}

data "aws_iam_policy_document" "github_lambda_package_trust" {
  for_each = local.lambda_package_subs

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
      values   = each.value
    }
  }
}

resource "aws_iam_role" "github_lambda_package" {
  for_each           = local.lambda_package_subs
  name               = "github-ci-lambda-${each.key}"
  assume_role_policy = data.aws_iam_policy_document.github_lambda_package_trust[each.key].json
}

data "aws_iam_policy_document" "github_lambda_package" {
  for_each = local.lambda_package_subs

  statement {
    sid    = "AuthToken"
    effect = "Allow"
    actions = [
      "codeartifact:GetAuthorizationToken",
      "codeartifact:DescribeDomain",
      "codeartifact:ListRepositoriesInDomain",
    ]
    resources = [var.codeartifact_domain_arn]
  }

  statement {
    sid       = "BearerToken"
    effect    = "Allow"
    actions   = ["sts:GetServiceBearerToken"]
    resources = ["*"]
    condition {
      test     = "StringEquals"
      variable = "sts:AWSServiceName"
      values   = ["codeartifact.amazonaws.com"]
    }
  }

  statement {
    sid    = "ReadStable"
    effect = "Allow"
    actions = [
      "codeartifact:GetRepositoryEndpoint",
      "codeartifact:ReadFromRepository",
      "codeartifact:DescribeRepository",
      "codeartifact:ListPackages",
      "codeartifact:ListPackageVersions",
      "codeartifact:DescribePackageVersion",
      "codeartifact:GetPackageVersionReadme",
    ]
    resources = [
      var.sdk_stable_repository_arn,
      "arn:aws:codeartifact:${var.region}:${var.aws_account_id}:package/${var.codeartifact_domain_name}/${var.sdk_stable_repository_name}/*",
    ]
  }

  statement {
    sid    = "Kms"
    effect = "Allow"
    actions = [
      "kms:Decrypt",
      "kms:DescribeKey",
    ]
    resources = [var.codeartifact_kms_key_arn]
  }

  statement {
    sid       = "ZipBucketList"
    effect    = "Allow"
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.lambda_releases.arn]
    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values   = ["${each.key}/*"]
    }
  }

  statement {
    sid    = "ZipObjectRW"
    effect = "Allow"
    actions = [
      "s3:PutObject",
      "s3:GetObject",
      "s3:GetObjectVersion",
    ]
    resources = ["${aws_s3_bucket.lambda_releases.arn}/${each.key}/*"]
  }
}

resource "aws_iam_role_policy" "github_lambda_package" {
  # checkov:skip=CKV_AWS_355:sts:GetServiceBearerToken for CodeArtifact login requires Resource *; scoped by sts:AWSServiceName=codeartifact.amazonaws.com
  for_each = local.lambda_package_subs
  name     = "lambda-package-${each.key}"
  role     = aws_iam_role.github_lambda_package[each.key].id
  policy   = data.aws_iam_policy_document.github_lambda_package[each.key].json
}
