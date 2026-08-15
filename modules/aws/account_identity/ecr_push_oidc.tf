# GitHub Actions OIDC role for THIS repo: build & push images under apps/ecr/
# with no stored AWS keys. Distinct from workloads/rag/image_push_oidc.tf, which
# trusts the excalidraw-tf-rag workload repo (role github-ci-ecr-push).

locals {
  infra_ecr_push_sub_push = "${local.github_sub_prefix}:ref:refs/heads/main"
  infra_ecr_push_sub_pr   = "${local.github_sub_prefix}:pull_request"
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
      values   = [local.infra_ecr_push_sub_push, local.infra_ecr_push_sub_pr]
    }
  }
}

resource "aws_iam_role" "github_infra_ecr_push" {
  name               = "github-ci-infra-ecr-push"
  assume_role_policy = data.aws_iam_policy_document.github_infra_ecr_push_trust.json
}

# CI discovers apps/ecr/<name> at build time and may create the repo on first
# push, so repo ARNs are not known here. The OIDC trust policy is the boundary.
data "aws_iam_policy_document" "github_infra_ecr_push" {
  # checkov:skip=CKV_AWS_111:Write access is unconstrained by resource — ECR repo names are discovered from apps/ecr/ at build time; the OIDC trust policy (this repo, main or pull_request) is the actual boundary.
  # checkov:skip=CKV_AWS_356:Same rationale as CKV_AWS_111 — "*" is required because repo ARNs are not known at plan time.
  statement {
    sid       = "EcrAuth"
    effect    = "Allow"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }

  statement {
    sid    = "EcrManage"
    effect = "Allow"
    actions = [
      "ecr:CreateRepository",
      "ecr:DescribeRepositories",
      "ecr:PutImageScanningConfiguration",
      "ecr:PutLifecyclePolicy",
      "ecr:BatchCheckLayerAvailability",
      "ecr:InitiateLayerUpload",
      "ecr:UploadLayerPart",
      "ecr:CompleteLayerUpload",
      "ecr:PutImage",
      "ecr:BatchGetImage",
    ]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "github_infra_ecr_push" {
  name   = "ecr-push"
  role   = aws_iam_role.github_infra_ecr_push.id
  policy = data.aws_iam_policy_document.github_infra_ecr_push.json
}
