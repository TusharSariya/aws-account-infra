resource "aws_guardduty_detector" "this" {
  # checkov:skip=CKV2_AWS_3:This is a single-account detector in us-east-1; org-delegated GuardDuty does not apply.
  enable                       = true
  finding_publishing_frequency = "SIX_HOURS"
}

# Foundational detection only. Extra plans that GuardDuty auto-enables on first
# turn-on would meter S3/Lambda/EKS/RDS/malware traffic against a $20 budget.
locals {
  guardduty_disabled_features = [
    "S3_DATA_EVENTS",
    "EKS_AUDIT_LOGS",
    "EBS_MALWARE_PROTECTION",
    "RDS_LOGIN_EVENTS",
    "LAMBDA_NETWORK_LOGS",
  ]
}

resource "aws_guardduty_detector_feature" "disabled" {
  for_each = toset(local.guardduty_disabled_features)

  detector_id = aws_guardduty_detector.this.id
  name        = each.value
  status      = "DISABLED"
}

resource "aws_guardduty_detector_feature" "runtime_monitoring" {
  detector_id = aws_guardduty_detector.this.id
  name        = "RUNTIME_MONITORING"
  status      = "DISABLED"

  additional_configuration {
    name   = "EKS_ADDON_MANAGEMENT"
    status = "DISABLED"
  }
  additional_configuration {
    name   = "ECS_FARGATE_AGENT_MANAGEMENT"
    status = "DISABLED"
  }
  additional_configuration {
    name   = "EC2_AGENT_MANAGEMENT"
    status = "DISABLED"
  }
}

resource "aws_cloudwatch_event_rule" "guardduty_findings" {
  name        = "account-guardduty-findings"
  description = "Forward GuardDuty findings to the security alerts topic"

  event_pattern = jsonencode({
    source      = ["aws.guardduty"]
    detail-type = ["GuardDuty Finding"]
  })
}

resource "aws_cloudwatch_event_target" "guardduty_findings" {
  rule = aws_cloudwatch_event_rule.guardduty_findings.name
  arn  = aws_sns_topic.security_alerts.arn
}
