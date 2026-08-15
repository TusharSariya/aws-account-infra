resource "aws_cloudwatch_log_group" "booker" {
  # checkov:skip=CKV_AWS_158:Default AWS-managed encryption is enough for a personal booker's logs.
  # checkov:skip=CKV_AWS_338:14 days is enough to debug a weekly cron; a 1-year retention floor is wasted spend.
  name              = "/aws/lambda/court-booker-api"
  retention_in_days = 14
}

resource "aws_lambda_function" "booker" {
  # checkov:skip=CKV_AWS_117:The API client must reach public upace.app; a VPC + NAT gateway would add idle cost.
  # checkov:skip=CKV_AWS_116:Retries live in Step Functions (3 attempts, 60s apart); a DLQ would not cancel a reservation.
  # checkov:skip=CKV_AWS_50:X-Ray is skipped to keep a once-a-week function cheap.
  # checkov:skip=CKV_AWS_173:Environment holds only the secret ARN, not credentials.
  # checkov:skip=CKV_AWS_272:Code signing is not used for this personal zip.
  # checkov:skip=CKV_AWS_115:This account's unreserved concurrency floor is 10; reserving 2 would fail PutFunctionConcurrency.
  count = local.zip_ready ? 1 : 0

  function_name = "court-booker-api"
  role          = aws_iam_role.lambda.arn
  handler       = "booker.handler.lambda_handler"
  runtime       = "python3.14"
  architectures = ["arm64"]
  memory_size   = 256
  timeout       = 30

  s3_bucket         = data.aws_s3_bucket.zips.id
  s3_key            = var.booker_api_zip_key
  s3_object_version = data.aws_s3_object.zip[0].version_id

  environment {
    variables = {
      SECRET_ARN     = data.aws_secretsmanager_secret.my_y.arn
      BOOKINGS_PATH  = "/var/task/bookings.yaml"
      TZ             = "America/St_Johns"
      BOOKER_BROWSER = "api"
    }
  }

  logging_config {
    log_format = "Text"
    log_group  = aws_cloudwatch_log_group.booker.name
  }

  depends_on = [aws_iam_role_policy.lambda]
}
