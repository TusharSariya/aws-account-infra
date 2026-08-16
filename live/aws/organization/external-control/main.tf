provider "aws" {
  region  = var.region
  profile = var.aws_profile != "" ? var.aws_profile : null

  default_tags {
    tags = {
      managed_by = "opentofu"
      repo       = "aws-account-infra"
      stack      = "external-control"
    }
  }
}

data "aws_caller_identity" "current" {}

data "aws_iam_policy_document" "external_state_key" {
  # checkov:skip=CKV_AWS_109:The account-root KMS key-policy statement is the standard delegation mechanism; operational permissions remain constrained in IAM.
  # checkov:skip=CKV_AWS_111:The account-root KMS key-policy statement enables IAM delegation and is paired with an explicit key-deletion deny.
  # checkov:skip=CKV_AWS_356:KMS key policies require Resource "*" because the policy is attached to the key itself; principals and downstream IAM are constrained.
  statement {
    sid       = "EnableAccountPolicies"
    effect    = "Allow"
    actions   = ["kms:*"]
    resources = ["*"]
    principals {
      type        = "AWS"
      identifiers = ["arn:aws:iam::${data.aws_caller_identity.current.account_id}:root"]
    }
  }

  statement {
    sid    = "DenyKeyDeletion"
    effect = "Deny"
    actions = [
      "kms:ScheduleKeyDeletion",
    ]
    resources = ["*"]
    principals {
      type        = "*"
      identifiers = ["*"]
    }
  }
}

resource "aws_kms_key" "external_state" {
  description             = "External provider state encryption"
  enable_key_rotation     = true
  deletion_window_in_days = 30
  policy                  = data.aws_iam_policy_document.external_state_key.json

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_kms_alias" "external_state" {
  name          = "alias/external-provider-state"
  target_key_id = aws_kms_key.external_state.key_id
}

resource "aws_s3_bucket" "external_state" {
  # checkov:skip=CKV_AWS_18:State access is audited by the organization CloudTrail.
  # checkov:skip=CKV_AWS_144:This personal control plane is intentionally single-region.
  # checkov:skip=CKV2_AWS_61:All object versions are retained; automated expiry is forbidden.
  # checkov:skip=CKV2_AWS_62:State mutation is monitored through CloudTrail, not S3 events.
  bucket = var.state_bucket_name

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_s3_bucket_versioning" "external_state" {
  bucket = aws_s3_bucket.external_state.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "external_state" {
  bucket = aws_s3_bucket.external_state.id
  rule {
    bucket_key_enabled = true
    apply_server_side_encryption_by_default {
      kms_master_key_id = aws_kms_key.external_state.arn
      sse_algorithm     = "aws:kms"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "external_state" {
  bucket                  = aws_s3_bucket.external_state.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "external_state" {
  bucket = aws_s3_bucket.external_state.id
  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

data "aws_iam_policy_document" "external_state" {
  statement {
    sid     = "DenyInsecureTransport"
    effect  = "Deny"
    actions = ["s3:*"]
    resources = [
      aws_s3_bucket.external_state.arn,
      "${aws_s3_bucket.external_state.arn}/*",
    ]
    principals {
      type        = "*"
      identifiers = ["*"]
    }
    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }

  statement {
    sid    = "DenyStateDeletion"
    effect = "Deny"
    actions = [
      "s3:DeleteBucket",
      "s3:DeleteObject",
      "s3:DeleteObjectVersion",
    ]
    resources = [
      aws_s3_bucket.external_state.arn,
      "${aws_s3_bucket.external_state.arn}/*",
    ]
    principals {
      type        = "*"
      identifiers = ["*"]
    }
  }
}

resource "aws_s3_bucket_policy" "external_state" {
  bucket = aws_s3_bucket.external_state.id
  policy = data.aws_iam_policy_document.external_state.json
}

resource "aws_dynamodb_table" "journal" {
  name         = var.journal_table_name
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "binding_id"

  attribute {
    name = "binding_id"
    type = "S"
  }

  point_in_time_recovery {
    enabled = true
  }

  server_side_encryption {
    enabled     = true
    kms_key_arn = aws_kms_key.external_state.arn
  }

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_dynamodb_table" "state_locks" {
  # The OpenTofu backend deletes lock rows during normal unlock, so this table is
  # intentionally separate from the durable reconciliation journal.
  # checkov:skip=CKV_AWS_28:State locks are ephemeral and reconstructable.
  name         = var.state_lock_table_name
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "LockID"

  attribute {
    name = "LockID"
    type = "S"
  }

  server_side_encryption {
    enabled     = true
    kms_key_arn = aws_kms_key.external_state.arn
  }
}

data "aws_iam_policy_document" "reconciler_trust" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "AWS"
      identifiers = var.reconciler_principal_arns
    }
  }
}

resource "aws_iam_role" "reconciler" {
  name                 = "local-external-provider-reconciler"
  assume_role_policy   = data.aws_iam_policy_document.reconciler_trust.json
  max_session_duration = 3600
}

data "aws_iam_policy_document" "reconciler" {
  statement {
    sid    = "ManageReconciliationJournal"
    effect = "Allow"
    actions = [
      "dynamodb:DescribeTable",
      "dynamodb:GetItem",
      "dynamodb:PutItem",
      "dynamodb:UpdateItem",
    ]
    resources = [aws_dynamodb_table.journal.arn]
  }

  statement {
    sid    = "ManageOpenTofuStateLocks"
    effect = "Allow"
    actions = [
      "dynamodb:DeleteItem",
      "dynamodb:DescribeTable",
      "dynamodb:GetItem",
      "dynamodb:PutItem",
    ]
    resources = [aws_dynamodb_table.state_locks.arn]
  }

  statement {
    sid    = "ManageSensitiveProviderState"
    effect = "Allow"
    actions = [
      "s3:GetBucketLocation",
      "s3:ListBucket",
      "s3:GetObject",
      "s3:PutObject",
    ]
    resources = [
      aws_s3_bucket.external_state.arn,
      "${aws_s3_bucket.external_state.arn}/*",
    ]
  }

  statement {
    sid    = "UseStateEncryptionKey"
    effect = "Allow"
    actions = [
      "kms:Decrypt",
      "kms:DescribeKey",
      "kms:Encrypt",
      "kms:GenerateDataKey",
    ]
    resources = [aws_kms_key.external_state.arn]
  }

  statement {
    sid       = "ResolveSupabaseCredentialAtRuntime"
    effect    = "Allow"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [var.supabase_runtime_secret_arn]
  }
}

resource "aws_iam_role_policy" "reconciler" {
  name   = "external-provider-reconciliation"
  role   = aws_iam_role.reconciler.id
  policy = data.aws_iam_policy_document.reconciler.json
}
