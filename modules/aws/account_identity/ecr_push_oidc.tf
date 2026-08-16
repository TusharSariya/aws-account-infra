# GitHub Actions OIDC role for THIS repo: build & push images under apps/ecr/
# with no stored AWS keys. Distinct from workloads/rag/image_push_oidc.tf, which
# trusts the excalidraw-tf-rag workload repo (role github-ci-ecr-push).

locals {
  infra_ecr_push_sub = "${local.github_sub_prefix}:environment:image-publish"
  infra_ecr_repo_arn = "arn:aws:ecr:${var.region}:${var.aws_account_id}:repository/court-booker"
}

data "aws_iam_policy_document" "github_infra_ecr_push_trust" {
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
      values   = [local.infra_ecr_push_sub]
    }
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:repository"
      values   = ["${var.github_owner}/${var.github_repo}"]
    }
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:workflow"
      values   = ["ecr-push"]
    }
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:ref"
      values   = ["refs/heads/main"]
    }
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:environment"
      values   = ["image-publish"]
    }
  }
}

resource "aws_iam_role" "github_infra_ecr_push" {
  name               = "github-ci-infra-ecr-push"
  assume_role_policy = data.aws_iam_policy_document.github_infra_ecr_push_trust.json
}

# Publishing is intentionally scoped to the one repository represented in the
# service catalog. Repository creation and lifecycle management remain IaC-owned.
data "aws_iam_policy_document" "github_infra_ecr_push" {
  # checkov:skip=CKV_AWS_356:ecr:GetAuthorizationToken has no resource-level ARN.
  statement {
    sid       = "EcrAuth"
    effect    = "Allow"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }

  statement {
    sid    = "CourtBookerImagePublish"
    effect = "Allow"
    actions = [
      "ecr:DescribeRepositories",
      "ecr:DescribeImages",
      "ecr:BatchCheckLayerAvailability",
      "ecr:InitiateLayerUpload",
      "ecr:UploadLayerPart",
      "ecr:CompleteLayerUpload",
      "ecr:PutImage",
      "ecr:BatchGetImage",
    ]
    resources = [local.infra_ecr_repo_arn]
  }
}

resource "aws_iam_role_policy" "github_infra_ecr_push" {
  name   = "ecr-push"
  role   = aws_iam_role.github_infra_ecr_push.id
  policy = data.aws_iam_policy_document.github_infra_ecr_push.json
}
