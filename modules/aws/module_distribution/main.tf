resource "aws_s3_bucket" "modules" {
  # checkov:skip=CKV_AWS_18:Organization CloudTrail records writes; a second access-log bucket is unnecessary.
  # checkov:skip=CKV_AWS_144:Consumers use a single selected region to avoid replication cost.
  # checkov:skip=CKV2_AWS_62:Module publishing is audited by CloudTrail and GitHub Actions.
  # checkov:skip=CKV2_AWS_61:Published module objects are write-once, object-locked release artifacts and intentionally do not expire.
  # checkov:skip=CKV_AWS_145:SSE-S3 avoids a recurring KMS charge for immutable, integrity-verified module archives.
  bucket              = var.bucket_name
  object_lock_enabled = true

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_s3_bucket_versioning" "modules" {
  bucket = aws_s3_bucket.modules.id
  versioning_configuration {
    status = "Enabled"
  }
}

#trivy:ignore:AVD-AWS-0132 Immutable module archives use SSE-S3; a dedicated CMK would add a monthly charge without changing the write-once or deletion-deny controls.
resource "aws_s3_bucket_server_side_encryption_configuration" "modules" {
  bucket = aws_s3_bucket.modules.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "modules" {
  bucket                  = aws_s3_bucket.modules.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_object_lock_configuration" "modules" {
  bucket = aws_s3_bucket.modules.id

  rule {
    default_retention {
      mode = "GOVERNANCE"
      days = var.retention_days
    }
  }

  depends_on = [aws_s3_bucket_versioning.modules]
}

data "aws_iam_policy_document" "publisher_trust" {
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
      values   = ["repo:${var.github_owner}/${var.github_repo}:environment:module-publish"]
    }
  }
}

resource "aws_iam_role" "publisher" {
  name               = "platform-components-module-publisher"
  assume_role_policy = data.aws_iam_policy_document.publisher_trust.json
}

data "aws_iam_policy_document" "publisher" {
  statement {
    sid       = "ListModules"
    effect    = "Allow"
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.modules.arn]
  }
  statement {
    sid       = "PublishNewModuleKey"
    effect    = "Allow"
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.modules.arn}/modules/*"]
  }
}

resource "aws_iam_role_policy" "publisher" {
  name   = "publish-write-once-modules"
  role   = aws_iam_role.publisher.id
  policy = data.aws_iam_policy_document.publisher.json
}

data "aws_iam_policy_document" "modules" {
  statement {
    sid    = "DenyInsecureTransport"
    effect = "Deny"
    principals {
      type        = "*"
      identifiers = ["*"]
    }
    actions = ["s3:*"]
    resources = [
      aws_s3_bucket.modules.arn,
      "${aws_s3_bucket.modules.arn}/*",
    ]
    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }

  statement {
    sid    = "DenyModuleOverwriteWithoutConditionalHeader"
    effect = "Deny"
    principals {
      type        = "*"
      identifiers = ["*"]
    }
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.modules.arn}/modules/*"]
    condition {
      test     = "Null"
      variable = "s3:if-none-match"
      values   = ["true"]
    }
  }

  statement {
    sid    = "DenyModuleOverwriteWithWrongCondition"
    effect = "Deny"
    principals {
      type        = "*"
      identifiers = ["*"]
    }
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.modules.arn}/modules/*"]
    condition {
      test     = "StringNotEquals"
      variable = "s3:if-none-match"
      values   = ["*"]
    }
  }

  statement {
    sid    = "DenyModuleDeletion"
    effect = "Deny"
    principals {
      type        = "*"
      identifiers = ["*"]
    }
    actions = [
      "s3:DeleteObject",
      "s3:DeleteObjectVersion",
    ]
    resources = ["${aws_s3_bucket.modules.arn}/modules/*"]
  }

  statement {
    sid    = "OrganizationModuleRead"
    effect = "Allow"
    principals {
      type        = "*"
      identifiers = ["*"]
    }
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.modules.arn}/modules/*"]
    condition {
      test     = "StringEquals"
      variable = "aws:PrincipalOrgID"
      values   = [var.organization_id]
    }
  }
}

resource "aws_s3_bucket_policy" "modules" {
  bucket = aws_s3_bucket.modules.id
  policy = data.aws_iam_policy_document.modules.json
}
