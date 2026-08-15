resource "aws_sns_topic" "security_alerts" {
  # checkov:skip=CKV_AWS_26:AWS-managed SNS encryption cannot receive EventBridge publishes; a dedicated CMK would add a monthly KMS charge.
  name = "account-security-alerts"
}

data "aws_iam_policy_document" "security_alerts" {
  statement {
    sid    = "AllowEventBridge"
    effect = "Allow"
    principals {
      type        = "Service"
      identifiers = ["events.amazonaws.com"]
    }
    actions   = ["sns:Publish"]
    resources = [aws_sns_topic.security_alerts.arn]
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [var.aws_account_id]
    }
  }
}

resource "aws_sns_topic_policy" "security_alerts" {
  arn    = aws_sns_topic.security_alerts.arn
  policy = data.aws_iam_policy_document.security_alerts.json
}

resource "aws_sns_topic_subscription" "security_alerts_email" {
  topic_arn = aws_sns_topic.security_alerts.arn
  protocol  = "email"
  endpoint  = var.governance_alert_email
}

resource "aws_cloudwatch_event_rule" "root_activity" {
  name        = "account-root-activity"
  description = "Alert on AWS account root user API or console activity"

  event_pattern = jsonencode({
    detail-type = ["AWS API Call via CloudTrail", "AWS Console Sign In via CloudTrail"]
    detail = {
      userIdentity = {
        type = ["Root"]
      }
    }
  })
}

resource "aws_cloudwatch_event_target" "root_activity" {
  rule = aws_cloudwatch_event_rule.root_activity.name
  arn  = aws_sns_topic.security_alerts.arn
}

resource "aws_cloudwatch_event_rule" "console_login_without_mfa" {
  name        = "account-console-login-without-mfa"
  description = "Alert on console sign-in when MFA was not used"

  event_pattern = jsonencode({
    detail-type = ["AWS Console Sign In via CloudTrail"]
    detail = {
      eventName = ["ConsoleLogin"]
      additionalEventData = {
        MFAUsed = ["No"]
      }
    }
  })
}

resource "aws_cloudwatch_event_target" "console_login_without_mfa" {
  rule = aws_cloudwatch_event_rule.console_login_without_mfa.name
  arn  = aws_sns_topic.security_alerts.arn
}

resource "aws_cloudwatch_event_rule" "iam_key_and_user" {
  name        = "account-iam-key-and-user"
  description = "Alert on access-key create or IAM user create"

  event_pattern = jsonencode({
    source      = ["aws.cloudtrail"]
    detail-type = ["AWS API Call via CloudTrail"]
    detail = {
      eventSource = ["iam.amazonaws.com"]
      eventName   = ["CreateAccessKey", "CreateUser", "AttachUserPolicy"]
    }
  })
}

resource "aws_cloudwatch_event_target" "iam_key_and_user" {
  rule = aws_cloudwatch_event_rule.iam_key_and_user.name
  arn  = aws_sns_topic.security_alerts.arn
}

resource "aws_cloudwatch_event_rule" "audit_tamper" {
  name        = "account-audit-tamper"
  description = "Alert on CloudTrail stop/delete or GuardDuty detector disable"

  event_pattern = jsonencode({
    source      = ["aws.cloudtrail"]
    detail-type = ["AWS API Call via CloudTrail"]
    detail = {
      eventName = ["DeleteTrail", "StopLogging", "UpdateTrail", "DeleteDetector", "UpdateDetector"]
    }
  })
}

resource "aws_cloudwatch_event_target" "audit_tamper" {
  rule = aws_cloudwatch_event_rule.audit_tamper.name
  arn  = aws_sns_topic.security_alerts.arn
}

resource "aws_cloudwatch_event_rule" "s3_bucket_policy" {
  name        = "account-s3-bucket-policy"
  description = "Alert on S3 bucket policy changes"

  event_pattern = jsonencode({
    source      = ["aws.cloudtrail"]
    detail-type = ["AWS API Call via CloudTrail"]
    detail = {
      eventSource = ["s3.amazonaws.com"]
      eventName   = ["PutBucketPolicy", "DeleteBucketPolicy", "PutBucketAcl"]
    }
  })
}

resource "aws_cloudwatch_event_target" "s3_bucket_policy" {
  rule = aws_cloudwatch_event_rule.s3_bucket_policy.name
  arn  = aws_sns_topic.security_alerts.arn
}
