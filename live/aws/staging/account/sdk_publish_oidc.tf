# GitHub Actions OIDC roles that publish generated SDKs to CodeArtifact.
# Candidate: any job in this repo (PRs). Stable: GitHub Environment `sdk` only
# (same OIDC sub trick as github-ci-tofu-apply / environment:prod).

data "aws_iam_policy_document" "github_sdk_candidate_trust" {
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
      test     = "StringLike"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["${local.github_sub_prefix}:*"]
    }
  }
}

data "aws_iam_policy_document" "github_sdk_stable_trust" {
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
      values   = ["${local.github_sub_prefix}:environment:sdk"]
    }
  }
}

resource "aws_iam_role" "github_sdk_candidate" {
  name               = "github-ci-sdk-candidate"
  assume_role_policy = data.aws_iam_policy_document.github_sdk_candidate_trust.json
}

resource "aws_iam_role" "github_sdk_stable" {
  name               = "github-ci-sdk-stable"
  assume_role_policy = data.aws_iam_policy_document.github_sdk_stable_trust.json
}

data "aws_iam_policy_document" "codeartifact_publish" {
  for_each = {
    candidate = aws_codeartifact_repository.sdk_candidate
    stable    = aws_codeartifact_repository.sdk_stable
  }

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
    sid    = "PublishRepo"
    effect = "Allow"
    actions = [
      "codeartifact:GetRepositoryEndpoint",
      "codeartifact:ReadFromRepository",
      "codeartifact:DescribeRepository",
      "codeartifact:ListPackages",
      "codeartifact:ListPackageVersions",
      "codeartifact:DescribePackageVersion",
      "codeartifact:GetPackageVersionReadme",
      "codeartifact:PublishPackageVersion",
      "codeartifact:PutPackageMetadata",
    ]
    resources = [
      each.value.arn,
      "arn:aws:codeartifact:${var.region}:${var.aws_account_id}:package/${aws_codeartifact_domain.infra.domain}/${each.value.repository}/*",
    ]
  }

  statement {
    sid    = "Kms"
    effect = "Allow"
    actions = [
      "kms:Decrypt",
      "kms:DescribeKey",
      "kms:GenerateDataKey",
    ]
    resources = [aws_kms_key.codeartifact.arn]
  }
}

resource "aws_iam_role_policy" "github_sdk_candidate" {
  # checkov:skip=CKV_AWS_355:sts:GetServiceBearerToken for CodeArtifact login requires Resource *; scoped by sts:AWSServiceName=codeartifact.amazonaws.com
  name   = "codeartifact-publish-candidate"
  role   = aws_iam_role.github_sdk_candidate.id
  policy = data.aws_iam_policy_document.codeartifact_publish["candidate"].json
}

resource "aws_iam_role_policy" "github_sdk_stable" {
  # checkov:skip=CKV_AWS_355:sts:GetServiceBearerToken for CodeArtifact login requires Resource *; scoped by sts:AWSServiceName=codeartifact.amazonaws.com
  name   = "codeartifact-publish-stable"
  role   = aws_iam_role.github_sdk_stable.id
  policy = data.aws_iam_policy_document.codeartifact_publish["stable"].json
}
