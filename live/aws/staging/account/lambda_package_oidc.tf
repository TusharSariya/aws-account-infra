# GitHub Actions OIDC role that packages apps/lambda zip functions and uploads
# them to the court-booker-api artifact bucket. Reads upace from sdk-stable.

locals {
  lambda_package_sub_push          = "${local.github_sub_prefix}:ref:refs/heads/main"
  lambda_package_sub_pr            = "${local.github_sub_prefix}:pull_request"
  court_booker_api_zip_bucket_name = "court-booker-api-lambda-${var.aws_account_id}-${var.region}"
  court_booker_api_zip_bucket_arn  = "arn:aws:s3:::${local.court_booker_api_zip_bucket_name}"
}

data "aws_iam_policy_document" "github_lambda_package_trust" {
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
      values   = [local.lambda_package_sub_push, local.lambda_package_sub_pr]
    }
  }
}

resource "aws_iam_role" "github_lambda_package" {
  name               = "github-ci-lambda-package"
  assume_role_policy = data.aws_iam_policy_document.github_lambda_package_trust.json
}

data "aws_iam_policy_document" "github_lambda_package" {
  statement {
    sid    = "AuthToken"
    effect = "Allow"
    actions = [
      "codeartifact:GetAuthorizationToken",
      "codeartifact:DescribeDomain",
      "codeartifact:ListRepositoriesInDomain",
    ]
    resources = [aws_codeartifact_domain.infra.arn]
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
      aws_codeartifact_repository.sdk_stable.arn,
      "arn:aws:codeartifact:${var.region}:${var.aws_account_id}:package/${aws_codeartifact_domain.infra.domain}/${aws_codeartifact_repository.sdk_stable.repository}/*",
    ]
  }

  statement {
    sid    = "Kms"
    effect = "Allow"
    actions = [
      "kms:Decrypt",
      "kms:DescribeKey",
    ]
    resources = [aws_kms_key.codeartifact.arn]
  }

  statement {
    sid       = "ZipBucketList"
    effect    = "Allow"
    actions   = ["s3:ListBucket"]
    resources = [local.court_booker_api_zip_bucket_arn]
  }

  statement {
    sid    = "ZipObjectRW"
    effect = "Allow"
    actions = [
      "s3:PutObject",
      "s3:GetObject",
      "s3:GetObjectVersion",
    ]
    resources = ["${local.court_booker_api_zip_bucket_arn}/*"]
  }
}

resource "aws_iam_role_policy" "github_lambda_package" {
  # checkov:skip=CKV_AWS_355:sts:GetServiceBearerToken for CodeArtifact login requires Resource *; scoped by sts:AWSServiceName=codeartifact.amazonaws.com
  name   = "lambda-package"
  role   = aws_iam_role.github_lambda_package.id
  policy = data.aws_iam_policy_document.github_lambda_package.json
}
