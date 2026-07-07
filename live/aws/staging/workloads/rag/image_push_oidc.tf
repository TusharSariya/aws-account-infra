# GitHub Actions OIDC role for the excalidraw-tf-rag workload repo: lets its CI
# build & push container images to this stack's ECR repos with NO stored AWS keys.
# The OIDC provider itself is account-level infra (created in live/aws/staging/account
# /github_oidc.tf); referenced here by data source rather than a second provider
# resource, since AWS only allows one provider per issuer URL per account.

data "aws_iam_openid_connect_provider" "github" {
  url = "https://token.actions.githubusercontent.com"
}

locals {
  ecr_push_sub = "repo:${var.ecr_push_github_owner}/${var.ecr_push_github_repo}:ref:refs/heads/master"
}

data "aws_iam_policy_document" "github_ecr_push_trust" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]
    principals {
      type        = "Federated"
      identifiers = [data.aws_iam_openid_connect_provider.github.arn]
    }
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }
    # Pinned to the workload repo's master branch only — this role can push
    # real images, so it gets the tighter (branch-pinned) trust, not the
    # broad `:*` pattern the account stack's read-only plan role uses.
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = [local.ecr_push_sub]
    }
  }
}

resource "aws_iam_role" "github_ecr_push" {
  name               = "github-ci-ecr-push"
  assume_role_policy = data.aws_iam_policy_document.github_ecr_push_trust.json
}

# Least privilege: authenticate to ECR (account-level API, no resource scoping
# available) plus push access to only this stack's repos — nothing else in the
# account.
data "aws_iam_policy_document" "github_ecr_push" {
  statement {
    sid       = "EcrAuth"
    effect    = "Allow"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }

  statement {
    sid    = "EcrPush"
    effect = "Allow"
    actions = [
      "ecr:BatchCheckLayerAvailability",
      "ecr:InitiateLayerUpload",
      "ecr:UploadLayerPart",
      "ecr:CompleteLayerUpload",
      "ecr:PutImage",
      "ecr:BatchGetImage",
    ]
    resources = [for repo in module.ecr : repo.repository_arn]
  }
}

resource "aws_iam_role_policy" "github_ecr_push" {
  name   = "ecr-push"
  role   = aws_iam_role.github_ecr_push.id
  policy = data.aws_iam_policy_document.github_ecr_push.json
}
