# GitHub Actions OIDC role for the excalidraw-tf-rag workload repo: lets its CI
# build & push container images to this stack's ECR repos with NO stored AWS keys.
# The OIDC provider itself is account-level infra (created in live/aws/staging/account
# /github_oidc.tf); referenced here by data source rather than a second provider
# resource, since AWS only allows one provider per issuer URL per account.

data "aws_iam_openid_connect_provider" "github" {
  url = "https://token.actions.githubusercontent.com"
}

locals {
  # GitHub's OIDC `sub` claim format differs by triggering event, NOT just by
  # ref — a pull_request-triggered run's sub is "repo:OWNER/REPO:pull_request"
  # (no ref/branch info at all), completely distinct from a push-to-branch
  # run's "repo:OWNER/REPO:ref:refs/heads/BRANCH". This role is assumed by
  # both the prod build (push to master) and the staging build (pull_request
  # opened/synchronize), so both sub shapes must be allowed.
  ecr_push_sub_push = "repo:${var.ecr_push_github_owner}/${var.ecr_push_github_repo}:ref:refs/heads/master"
  ecr_push_sub_pr   = "repo:${var.ecr_push_github_owner}/${var.ecr_push_github_repo}:pull_request"
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
    # Pinned to this one workload repo only — this role can push real
    # images, so it gets tighter trust than the account stack's read-only
    # plan role (which allows any branch/PR via a broad `:*` pattern).
    # StringEquals with multiple values matches if ANY one is present (OR),
    # not all — so this allows exactly the two sub shapes above and nothing
    # else (no other repo, no other branch's push, no environment-based sub).
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = [local.ecr_push_sub_push, local.ecr_push_sub_pr]
    }
  }
}

resource "aws_iam_role" "github_ecr_push" {
  name               = "github-ci-ecr-push"
  assume_role_policy = data.aws_iam_policy_document.github_ecr_push_trust.json
}

# Deliberately unrestricted within ECR (Resource = "*" on the management + push
# actions below): CI creates repos on demand from a directory it discovers at
# build time, so repo names/ARNs aren't known to Terraform ahead of time and
# can't be prefix-scoped. The trust policy above is the real security boundary
# here — only a push to excalidraw-tf-rag's master branch, or a pull_request
# run in that same repo, can ever assume this role in the first place.
data "aws_iam_policy_document" "github_ecr_push" {
  # checkov:skip=CKV_AWS_111:Write access is intentionally unconstrained by resource — ECR repo names are created ad-hoc by CI and unknown to Terraform ahead of time; the OIDC trust policy (branch-pinned to one repo) is the actual boundary.
  # checkov:skip=CKV_AWS_356:Same rationale as CKV_AWS_111 above — "*" is required because repo ARNs don't exist yet at plan time, not an oversight.
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

resource "aws_iam_role_policy" "github_ecr_push" {
  name   = "ecr-push"
  role   = aws_iam_role.github_ecr_push.id
  policy = data.aws_iam_policy_document.github_ecr_push.json
}
