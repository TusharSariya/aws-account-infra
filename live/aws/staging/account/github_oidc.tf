# GitHub Actions OIDC: lets CI assume short-lived roles with NO stored AWS keys.
# Trust is pinned to this repo; the apply role is further pinned to the main branch.

resource "aws_iam_openid_connect_provider" "github" {
  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]
  # GitHub's OIDC root CA thumbprints. AWS validates OIDC tokens against its own
  # trust store for this well-known IdP, but the argument must be present.
  thumbprint_list = [
    "6938fd4d98bab03faadb97b34396831e3780aea1",
    "1c58a3a8518e8759bf075b76b750d4f2df264fca",
  ]
}

locals {
  github_sub_prefix = "repo:${var.github_owner}/${var.github_repo}"

  # State backend ARNs the CI roles need (read state + acquire the lock).
  state_bucket_arn = "arn:aws:s3:::${var.state_bucket_name}"
  lock_table_arn   = "arn:aws:dynamodb:${var.region}:${var.aws_account_id}:table/${var.lock_table_name}"
}

# Inline policy: read/write state objects + lock table. Plan needs it (lock + read);
# apply needs it too.
data "aws_iam_policy_document" "tofu_state_access" {
  statement {
    sid       = "StateBucketList"
    effect    = "Allow"
    actions   = ["s3:ListBucket"]
    resources = [local.state_bucket_arn]
  }
  statement {
    sid       = "StateObjectRW"
    effect    = "Allow"
    actions   = ["s3:GetObject", "s3:PutObject"]
    resources = ["${local.state_bucket_arn}/*"]
  }
  statement {
    sid       = "LockTable"
    effect    = "Allow"
    actions   = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:DeleteItem"]
    resources = [local.lock_table_arn]
  }
}

# ---- Plan role (PRs): read-only + state access ----------------------------
data "aws_iam_policy_document" "github_plan_trust" {
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
    # Any PR or branch in this repo may plan (read-only).
    condition {
      test     = "StringLike"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["${local.github_sub_prefix}:*"]
    }
  }
}

resource "aws_iam_role" "github_plan" {
  name               = "github-ci-tofu-plan"
  assume_role_policy = data.aws_iam_policy_document.github_plan_trust.json
}

resource "aws_iam_role_policy_attachment" "plan_readonly" {
  role       = aws_iam_role.github_plan.name
  policy_arn = "arn:aws:iam::aws:policy/ReadOnlyAccess"
}

resource "aws_iam_role_policy" "plan_state" {
  name   = "tofu-state-access"
  role   = aws_iam_role.github_plan.id
  policy = data.aws_iam_policy_document.tofu_state_access.json
}

# ---- Apply role (prod environment only): admin + state access -------------
data "aws_iam_policy_document" "github_apply_trust" {
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
    # Apply-before-merge: apply runs on the PR branch, gated by the `prod`
    # GitHub Environment (required reviewer). A job that declares `environment: prod`
    # gets sub=repo:<owner>/<repo>:environment:prod regardless of branch, so we pin
    # trust to the approved environment — tighter than a branch, and the only path
    # that can assume admin is an approved prod deployment.
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["${local.github_sub_prefix}:environment:prod"]
    }
  }
}

resource "aws_iam_role" "github_apply" {
  name               = "github-ci-tofu-apply"
  assume_role_policy = data.aws_iam_policy_document.github_apply_trust.json
}

resource "aws_iam_role_policy_attachment" "apply_admin" {
  # checkov:skip=CKV_AWS_274:The CI apply role IS the account's deploy identity and must apply arbitrary infra; AdministratorAccess is intentional. It's only assumable via OIDC from environment:prod (see the trust pin above).
  role       = aws_iam_role.github_apply.name
  policy_arn = "arn:aws:iam::aws:policy/AdministratorAccess"
}

resource "aws_iam_role_policy" "apply_state" {
  name   = "tofu-state-access"
  role   = aws_iam_role.github_apply.id
  policy = data.aws_iam_policy_document.tofu_state_access.json
}
