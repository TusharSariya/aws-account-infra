locals {
  github_subject_prefix = "repo:${var.github_owner}/${var.github_repo}"
  control_state_arn     = "arn:aws:s3:::${var.control_plane_state_bucket}"
  control_lock_arn      = "arn:aws:dynamodb:${var.region}:${data.aws_organizations_organization.current.master_account_id}:table/${var.control_plane_lock_table}"
  vending_role_arns = [
    "arn:aws:iam::${data.aws_organizations_organization.current.master_account_id}:role/github-account-vending-plan",
    "arn:aws:iam::${data.aws_organizations_organization.current.master_account_id}:role/github-account-vending-apply",
  ]
}

data "aws_iam_policy_document" "vending_plan_trust" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]
    principals {
      type        = "Federated"
      identifiers = [var.github_oidc_provider_arn]
    }
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["${local.github_subject_prefix}:environment:platform-plan"]
    }
  }
}

resource "aws_iam_role" "vending_plan" {
  name               = "github-account-vending-plan"
  assume_role_policy = data.aws_iam_policy_document.vending_plan_trust.json

  lifecycle {
    prevent_destroy = true
    # The workflow must never be able to rewrite its own trust boundary. Apply
    # reviewed trust changes with management-account administrator credentials.
    ignore_changes = [assume_role_policy]
  }
}

data "aws_iam_policy_document" "vending_plan" {
  # checkov:skip=CKV_AWS_356:Organizations List/Describe and IAM Organizations feature read APIs do not support resource-level permissions.
  statement {
    sid    = "ReadOrganization"
    effect = "Allow"
    actions = [
      "iam:GetOrganizationsAccessReport",
      "iam:ListOrganizationsFeatures",
      "organizations:Describe*",
      "organizations:List*",
    ]
    resources = ["*"]
  }

  statement {
    sid    = "ReadStateAndLock"
    effect = "Allow"
    actions = [
      "dynamodb:DeleteItem",
      "dynamodb:DescribeTable",
      "dynamodb:GetItem",
      "dynamodb:PutItem",
      "s3:GetBucketLocation",
      "s3:GetObject",
      "s3:ListBucket",
    ]
    resources = [
      local.control_lock_arn,
      local.control_state_arn,
      "${local.control_state_arn}/*",
    ]
  }

  statement {
    sid    = "DenyCredentialAndRoleAccess"
    effect = "Deny"
    actions = [
      "kms:Decrypt",
      "secretsmanager:GetSecretValue",
      "secretsmanager:BatchGetSecretValue",
      "ssm:GetParameter",
      "ssm:GetParameters",
      "ssm:GetParametersByPath",
      "sts:AssumeRole",
    ]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "vending_plan" {
  name   = "organization-plan"
  role   = aws_iam_role.vending_plan.id
  policy = data.aws_iam_policy_document.vending_plan.json

  lifecycle {
    prevent_destroy = true
    # Avoid granting the vending principal iam:PutRolePolicy on itself.
    ignore_changes = [policy]
  }
}

data "aws_iam_policy_document" "vending_apply_trust" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]
    principals {
      type        = "Federated"
      identifiers = [var.github_oidc_provider_arn]
    }
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["${local.github_subject_prefix}:environment:platform-prod"]
    }
  }
}

resource "aws_iam_role" "vending_apply" {
  name               = "github-account-vending-apply"
  assume_role_policy = data.aws_iam_policy_document.vending_apply_trust.json

  lifecycle {
    prevent_destroy = true
    ignore_changes  = [assume_role_policy]
  }
}

data "aws_iam_policy_document" "vending_apply" {
  # checkov:skip=CKV_AWS_111:Organizations account and OU vending APIs require Resource "*"; destructive organization operations are explicitly denied below.
  # checkov:skip=CKV_AWS_356:Organizations APIs and centralized-root feature APIs do not support resource-level permissions.
  statement {
    sid    = "ReadBootstrapIdentity"
    effect = "Allow"
    actions = [
      "iam:GetRole",
      "iam:GetRolePolicy",
      "iam:ListAttachedRolePolicies",
      "iam:ListInstanceProfilesForRole",
      "iam:ListRolePolicies",
      "iam:ListRoleTags",
    ]
    resources = local.vending_role_arns
  }

  statement {
    sid       = "ManageOrganization"
    effect    = "Allow"
    actions   = ["organizations:*"]
    resources = ["*"]
  }

  statement {
    sid    = "DenyOrganizationDestruction"
    effect = "Deny"
    actions = [
      "organizations:CloseAccount",
      "organizations:DeleteOrganizationalUnit",
      "organizations:DeleteOrganization",
      "organizations:DeregisterDelegatedAdministrator",
      "organizations:DisableAWSServiceAccess",
      "organizations:LeaveOrganization",
      "organizations:RemoveAccountFromOrganization",
    ]
    resources = ["*"]
  }

  statement {
    sid    = "ManageCentralizedRootAccess"
    effect = "Allow"
    actions = [
      "iam:DisableOrganizationsRootCredentialsManagement",
      "iam:DisableOrganizationsRootSessions",
      "iam:EnableOrganizationsRootCredentialsManagement",
      "iam:EnableOrganizationsRootSessions",
      "iam:GetOrganizationsAccessReport",
      "iam:ListOrganizationsFeatures",
    ]
    resources = ["*"]
  }

  statement {
    sid    = "ManageStateAndLock"
    effect = "Allow"
    actions = [
      "dynamodb:DeleteItem",
      "dynamodb:DescribeTable",
      "dynamodb:GetItem",
      "dynamodb:PutItem",
      "dynamodb:UpdateItem",
      "s3:GetBucketLocation",
      "s3:GetObject",
      "s3:ListBucket",
      "s3:PutObject",
    ]
    resources = [
      local.control_lock_arn,
      local.control_state_arn,
      "${local.control_state_arn}/*",
    ]
  }

  statement {
    sid       = "BootstrapVendedAccount"
    effect    = "Allow"
    actions   = ["sts:AssumeRole"]
    resources = ["arn:aws:iam::*:role/OrganizationAccountAccessRole"]
  }
}

resource "aws_iam_role_policy" "vending_apply" {
  name   = "organization-apply"
  role   = aws_iam_role.vending_apply.id
  policy = data.aws_iam_policy_document.vending_apply.json

  lifecycle {
    prevent_destroy = true
    ignore_changes  = [policy]
  }
}

output "account_vending_plan_role_arn" {
  value = aws_iam_role.vending_plan.arn
}

output "account_vending_apply_role_arn" {
  value = aws_iam_role.vending_apply.arn
}
