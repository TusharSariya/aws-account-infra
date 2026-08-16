provider "aws" {
  region  = var.region
  profile = var.aws_profile != "" ? var.aws_profile : null

  default_tags {
    tags = {
      managed_by = "opentofu"
      repo       = "aws-account-infra"
      stack      = "organization-security"
    }
  }
}

provider "aws" {
  alias   = "security"
  region  = var.region
  profile = var.aws_profile != "" ? var.aws_profile : null

  assume_role {
    role_arn     = "arn:aws:iam::${var.security_account_id}:role/OrganizationAccountAccessRole"
    session_name = "organization-security"
  }

  default_tags {
    tags = {
      managed_by = "opentofu"
      repo       = "aws-account-infra"
      stack      = "organization-security"
    }
  }
}

locals {
  trail_name = "organization-management-events"
  trail_arn  = "arn:aws:cloudtrail:${var.region}:${var.management_account_id}:trail/${local.trail_name}"
}

resource "aws_s3_bucket" "cloudtrail" {
  # checkov:skip=CKV_AWS_18:A second log bucket would add cost and another security boundary.
  # checkov:skip=CKV_AWS_144:The organization trail is multi-region; its destination remains in the home region.
  # checkov:skip=CKV2_AWS_62:CloudTrail owns delivery into this bucket.
  # checkov:skip=CKV_AWS_145:SSE-S3 is the reviewed low-cost encryption choice for the organization management trail.
  bucket = var.cloudtrail_bucket_name

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_s3_bucket_versioning" "cloudtrail" {
  bucket = aws_s3_bucket.cloudtrail.id
  versioning_configuration {
    status = "Enabled"
  }
}

#trivy:ignore:AVD-AWS-0132 The organization trail uses SSE-S3 to avoid a recurring management-account CMK charge.
resource "aws_s3_bucket_server_side_encryption_configuration" "cloudtrail" {
  bucket = aws_s3_bucket.cloudtrail.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "cloudtrail" {
  bucket                  = aws_s3_bucket.cloudtrail.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_lifecycle_configuration" "cloudtrail" {
  bucket     = aws_s3_bucket.cloudtrail.id
  depends_on = [aws_s3_bucket_versioning.cloudtrail]

  rule {
    id     = "expire-management-events"
    status = "Enabled"
    filter {}
    expiration {
      days = 90
    }
    noncurrent_version_expiration {
      noncurrent_days = 30
    }
    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }
}

data "aws_iam_policy_document" "cloudtrail" {
  statement {
    sid    = "CloudTrailAclCheck"
    effect = "Allow"
    principals {
      type        = "Service"
      identifiers = ["cloudtrail.amazonaws.com"]
    }
    actions   = ["s3:GetBucketAcl"]
    resources = [aws_s3_bucket.cloudtrail.arn]
    condition {
      test     = "StringEquals"
      variable = "aws:SourceArn"
      values   = [local.trail_arn]
    }
  }

  statement {
    sid    = "CloudTrailOrganizationWrite"
    effect = "Allow"
    principals {
      type        = "Service"
      identifiers = ["cloudtrail.amazonaws.com"]
    }
    actions = ["s3:PutObject"]
    resources = [
      "${aws_s3_bucket.cloudtrail.arn}/AWSLogs/${var.management_account_id}/*",
      "${aws_s3_bucket.cloudtrail.arn}/AWSLogs/${var.organization_id}/*",
    ]
    condition {
      test     = "StringEquals"
      variable = "s3:x-amz-acl"
      values   = ["bucket-owner-full-control"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceArn"
      values   = [local.trail_arn]
    }
  }

  statement {
    sid    = "DenyInsecureTransport"
    effect = "Deny"
    principals {
      type        = "*"
      identifiers = ["*"]
    }
    actions = ["s3:*"]
    resources = [
      aws_s3_bucket.cloudtrail.arn,
      "${aws_s3_bucket.cloudtrail.arn}/*",
    ]
    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

resource "aws_s3_bucket_policy" "cloudtrail" {
  bucket = aws_s3_bucket.cloudtrail.id
  policy = data.aws_iam_policy_document.cloudtrail.json
}

resource "aws_organizations_aws_service_access" "cloudtrail" {
  service_principal = "cloudtrail.amazonaws.com"
}

#trivy:ignore:AVD-AWS-0015 The trail bucket uses SSE-S3 intentionally; validation, object lock, and deletion protection preserve audit integrity.
resource "aws_cloudtrail" "organization" {
  # checkov:skip=CKV_AWS_35:S3 retention is sufficient for this low-volume organization trail.
  # checkov:skip=CKV_AWS_36:SSE-S3 avoids a monthly customer-managed KMS key charge.
  # checkov:skip=CKV_AWS_252:The trail is delivered to a protected S3 bucket; SNS delivery would add another notification boundary.
  # checkov:skip=CKV2_AWS_10:This low-volume organization trail is retained in S3 rather than duplicated to paid CloudWatch Logs.
  name                          = local.trail_name
  s3_bucket_name                = aws_s3_bucket.cloudtrail.id
  include_global_service_events = true
  is_multi_region_trail         = true
  is_organization_trail         = true
  enable_log_file_validation    = true
  enable_logging                = true

  event_selector {
    read_write_type           = "All"
    include_management_events = true
  }

  depends_on = [
    aws_organizations_aws_service_access.cloudtrail,
    aws_s3_bucket_policy.cloudtrail,
  ]

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_organizations_aws_service_access" "access_analyzer" {
  service_principal = "access-analyzer.amazonaws.com"
}

resource "aws_organizations_delegated_administrator" "access_analyzer" {
  account_id        = var.security_account_id
  service_principal = aws_organizations_aws_service_access.access_analyzer.service_principal
}

resource "aws_accessanalyzer_analyzer" "organization_external" {
  provider = aws.security

  analyzer_name = "organization-external-access"
  type          = "ORGANIZATION"

  depends_on = [aws_organizations_delegated_administrator.access_analyzer]
}

resource "aws_organizations_aws_service_access" "guardduty" {
  count = var.enable_guardduty ? 1 : 0

  service_principal = "guardduty.amazonaws.com"
}

resource "aws_guardduty_detector" "security" {
  count    = var.enable_guardduty ? 1 : 0
  provider = aws.security
  enable   = true
}

resource "aws_guardduty_organization_admin_account" "security" {
  count = var.enable_guardduty ? 1 : 0

  admin_account_id = var.security_account_id

  depends_on = [
    aws_guardduty_detector.security,
    aws_organizations_aws_service_access.guardduty,
  ]
}

resource "aws_guardduty_organization_configuration" "security" {
  count    = var.enable_guardduty ? 1 : 0
  provider = aws.security

  auto_enable_organization_members = "ALL"
  detector_id                      = aws_guardduty_detector.security[0].id

  depends_on = [aws_guardduty_organization_admin_account.security]
}

output "organization_trail_arn" {
  value = aws_cloudtrail.organization.arn
}

output "guardduty_enabled" {
  value = var.enable_guardduty
}
