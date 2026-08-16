provider "aws" {
  region  = var.region
  profile = var.aws_profile != "" ? var.aws_profile : null
}

data "aws_ssoadmin_instances" "current" {}

locals {
  instance_arn      = tolist(data.aws_ssoadmin_instances.current.arns)[0]
  identity_store_id = tolist(data.aws_ssoadmin_instances.current.identity_store_ids)[0]
}

data "aws_identitystore_group" "admin" {
  identity_store_id = local.identity_store_id
  alternate_identifier {
    unique_attribute {
      attribute_path  = "DisplayName"
      attribute_value = var.platform_admin_group_name
    }
  }
}

data "aws_identitystore_group" "operator" {
  identity_store_id = local.identity_store_id
  alternate_identifier {
    unique_attribute {
      attribute_path  = "DisplayName"
      attribute_value = var.workload_operator_group_name
    }
  }
}

data "aws_identitystore_group" "readonly" {
  identity_store_id = local.identity_store_id
  alternate_identifier {
    unique_attribute {
      attribute_path  = "DisplayName"
      attribute_value = var.readonly_group_name
    }
  }
}

resource "aws_ssoadmin_permission_set" "admin" {
  name             = "PlatformAdmin"
  description      = "Emergency platform administration for vended accounts"
  instance_arn     = local.instance_arn
  session_duration = "PT2H"
}

resource "aws_ssoadmin_managed_policy_attachment" "admin" {
  # checkov:skip=CKV_AWS_274:This two-hour PlatformAdmin permission set is the explicitly named emergency administration path.
  instance_arn       = local.instance_arn
  permission_set_arn = aws_ssoadmin_permission_set.admin.arn
  managed_policy_arn = "arn:aws:iam::aws:policy/AdministratorAccess"
}

resource "aws_ssoadmin_permission_set" "operator" {
  name             = "WorkloadOperator"
  description      = "Operate CourtBooker and populate its credential parameter"
  instance_arn     = local.instance_arn
  session_duration = "PT4H"
}

resource "aws_ssoadmin_permission_set_inline_policy" "operator" {
  # checkov:skip=CKV_AWS_355:CloudWatch DescribeAlarms and related list/read APIs require Resource "*"; mutating Step Functions access is scoped separately below.
  instance_arn       = local.instance_arn
  permission_set_arn = aws_ssoadmin_permission_set.operator.arn
  inline_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "OperateCourtBooker"
        Effect = "Allow"
        Action = [
          "cloudwatch:DescribeAlarms",
          "logs:DescribeLogStreams",
          "logs:FilterLogEvents",
          "logs:GetLogEvents",
          "states:DescribeExecution",
          "states:ListExecutions",
        ]
        Resource = "*"
      },
      {
        Sid      = "StartCourtBooker"
        Effect   = "Allow"
        Action   = ["states:StartExecution"]
        Resource = "arn:aws:states:*:*:stateMachine:court-booker*"
      },
      {
        Sid    = "WriteCourtCredentials"
        Effect = "Allow"
        Action = [
          "ssm:GetParameter",
          "ssm:PutParameter",
        ]
        Resource = "arn:aws:ssm:*:*:parameter/*/court-booker*/my-y"
      },
    ]
  })
}

resource "aws_ssoadmin_permission_set" "readonly" {
  name             = "PlatformReadOnly"
  description      = "Read infrastructure metadata without reading stored credentials"
  instance_arn     = local.instance_arn
  session_duration = "PT4H"
}

resource "aws_ssoadmin_managed_policy_attachment" "readonly" {
  instance_arn       = local.instance_arn
  permission_set_arn = aws_ssoadmin_permission_set.readonly.arn
  managed_policy_arn = "arn:aws:iam::aws:policy/ReadOnlyAccess"
}

resource "aws_ssoadmin_permission_set_inline_policy" "readonly_denies" {
  instance_arn       = local.instance_arn
  permission_set_arn = aws_ssoadmin_permission_set.readonly.arn
  inline_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid    = "DenyCredentialReads"
      Effect = "Deny"
      Action = [
        "kms:Decrypt",
        "secretsmanager:GetSecretValue",
        "secretsmanager:BatchGetSecretValue",
        "ssm:GetParameter",
        "ssm:GetParameters",
        "ssm:GetParametersByPath",
      ]
      Resource = "*"
    }]
  })
}

resource "aws_ssoadmin_account_assignment" "admin" {
  for_each = var.account_ids

  instance_arn       = local.instance_arn
  permission_set_arn = aws_ssoadmin_permission_set.admin.arn
  principal_id       = data.aws_identitystore_group.admin.group_id
  principal_type     = "GROUP"
  target_id          = each.value
  target_type        = "AWS_ACCOUNT"

  depends_on = [aws_ssoadmin_managed_policy_attachment.admin]
}

resource "aws_ssoadmin_account_assignment" "operator" {
  for_each = var.operator_account_ids

  instance_arn       = local.instance_arn
  permission_set_arn = aws_ssoadmin_permission_set.operator.arn
  principal_id       = data.aws_identitystore_group.operator.group_id
  principal_type     = "GROUP"
  target_id          = each.value
  target_type        = "AWS_ACCOUNT"

  depends_on = [aws_ssoadmin_permission_set_inline_policy.operator]
}

resource "aws_ssoadmin_account_assignment" "readonly" {
  for_each = var.account_ids

  instance_arn       = local.instance_arn
  permission_set_arn = aws_ssoadmin_permission_set.readonly.arn
  principal_id       = data.aws_identitystore_group.readonly.group_id
  principal_type     = "GROUP"
  target_id          = each.value
  target_type        = "AWS_ACCOUNT"

  depends_on = [
    aws_ssoadmin_managed_policy_attachment.readonly,
    aws_ssoadmin_permission_set_inline_policy.readonly_denies,
  ]
}
