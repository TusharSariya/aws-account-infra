locals {
  functions = toset(["collector", "digester"])
}
data "aws_s3_object" "artifact" {
  bucket = local.zip_bucket_name
  key    = var.artifact_key
}
data "aws_ses_email_identity" "sender" { email = var.sender }
resource "aws_cloudwatch_log_group" "digest" {
  # checkov:skip=CKV_AWS_338:User requested 14-day log retention.
  # checkov:skip=CKV_AWS_158:AWS-managed encryption is sufficient for public-feed operational logs.
  for_each          = local.functions
  name              = "/aws/lambda/technology-digest-${each.key}"
  retention_in_days = 14
}
resource "aws_iam_role" "lambda" {
  for_each = local.functions
  name     = "technology-digest-${each.key}"
  assume_role_policy = jsonencode({ Version = "2012-10-17", Statement = [{
    Effect = "Allow", Principal = { Service = "lambda.amazonaws.com" }, Action = "sts:AssumeRole"
  }] })
}
resource "aws_iam_role_policy" "lambda" {
  for_each = local.functions
  role     = aws_iam_role.lambda[each.key].id
  policy = jsonencode({ Version = "2012-10-17", Statement = concat([
    { Effect = "Allow", Action = ["logs:CreateLogStream", "logs:PutLogEvents"], Resource = "${aws_cloudwatch_log_group.digest[each.key].arn}:*" },
    { Effect = "Allow", Action = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:DeleteItem", "dynamodb:Scan", "dynamodb:TransactWriteItems"], Resource = aws_dynamodb_table.digest.arn },
    { Effect = "Allow", Action = ["s3:PutObject", "s3:GetObject"], Resource = "${aws_s3_bucket.digest.arn}/*" },
    { Effect = "Allow", Action = ["sqs:SendMessage"], Resource = aws_sqs_queue.failures.arn }
    ], each.key == "digester" ? [{
      Effect    = "Allow", Action = ["ses:SendRawEmail"], Resource = [data.aws_ses_email_identity.sender.arn, aws_ses_configuration_set.digest.arn],
      Condition = { StringEquals = { "ses:FromAddress" = var.sender }, "ForAllValues:StringEquals" = { "ses:Recipients" = [var.recipient] } }
  }] : []) })
}
resource "aws_lambda_function" "digest" {
  # checkov:skip=CKV_AWS_50:Structured logs, durable status and alarms provide tracing for this scheduled workload.
  # checkov:skip=CKV_AWS_117:Public feeds require internet access; a VPC would require an unnecessary NAT gateway.
  # checkov:skip=CKV_AWS_173:Environment contains resource names and the delivery address, with AWS-managed encryption.
  # checkov:skip=CKV_AWS_272:Content-addressed artifacts are pinned by hash and object version; signing is not configured.
  # checkov:skip=CKV_AWS_115:Account concurrency is constrained; DynamoDB leases serialize work and expire after the Lambda maximum lifetime.
  for_each          = local.functions
  function_name     = "technology-digest-${each.key}"
  role              = aws_iam_role.lambda[each.key].arn
  handler           = "digest.handler.${each.key}"
  runtime           = "python3.12"
  architectures     = ["arm64"]
  memory_size       = 256
  timeout           = 900
  s3_bucket         = local.zip_bucket_name
  s3_key            = var.artifact_key
  s3_object_version = data.aws_s3_object.artifact.version_id
  source_code_hash  = var.artifact_sha256
  environment {
    variables = {
      SES_CONFIGURATION_SET = aws_ses_configuration_set.digest.name
      TABLE_NAME            = aws_dynamodb_table.digest.name
      BUCKET_NAME           = aws_s3_bucket.digest.id
      SENDER                = var.sender
      RECIPIENT             = var.recipient
      MONITOR_DELIVERY      = tostring(var.schedules_enabled)
    }
  }
  logging_config {
    log_format = "Text"
    log_group  = aws_cloudwatch_log_group.digest[each.key].name
  }
  dead_letter_config { target_arn = aws_sqs_queue.failures.arn }
  depends_on = [aws_iam_role_policy.lambda]
}
resource "aws_lambda_function_event_invoke_config" "digest" {
  for_each                     = local.functions
  function_name                = aws_lambda_function.digest[each.key].function_name
  maximum_event_age_in_seconds = 3600
  maximum_retry_attempts       = 2
  destination_config {
    on_failure { destination = aws_sqs_queue.failures.arn }
  }
}
