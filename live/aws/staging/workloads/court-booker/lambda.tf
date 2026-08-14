resource "aws_cloudwatch_log_group" "booker" {
  # checkov:skip=CKV_AWS_158:Default AWS-managed encryption is enough for a personal booker's logs.
  # checkov:skip=CKV_AWS_338:14 days is enough to debug a weekly cron; a 1-year retention floor is wasted spend.
  name              = "/aws/lambda/court-booker"
  retention_in_days = 14
}

resource "aws_lambda_function" "booker" {
  # checkov:skip=CKV_AWS_117:Playwright must reach public embed.upace.app; a VPC + NAT gateway would add idle cost.
  # checkov:skip=CKV_AWS_116:Retries live in Step Functions (3 attempts, 60s apart); a DLQ would not cancel a reservation.
  # checkov:skip=CKV_AWS_50:X-Ray is skipped to keep a once-a-week function cheap.
  # checkov:skip=CKV_AWS_173:Environment holds only the secret ARN, not credentials.
  # checkov:skip=CKV_AWS_272:Code signing is not used for this personal container image.
  # checkov:skip=CKV_AWS_115:This account's unreserved concurrency floor is 10; reserving 2 would fail PutFunctionConcurrency.
  count = var.booker_image_tag != "" ? 1 : 0

  function_name = "court-booker"
  role          = aws_iam_role.lambda.arn
  package_type  = "Image"
  image_uri     = "${module.ecr.repository_url}:${var.booker_image_tag}"
  architectures = ["arm64"]
  memory_size   = 2048
  timeout       = 180

  image_config {
    command = ["booker.handler.lambda_handler"]
  }

  ephemeral_storage {
    size = 1024
  }

  environment {
    variables = {
      SECRET_ARN      = aws_secretsmanager_secret.my_y.arn
      BOOKINGS_PATH   = "/var/task/bookings.yaml"
      TZ              = "America/St_Johns"
      BOOKER_BROWSER  = "playwright"
      HOME            = "/tmp"
      XDG_CONFIG_HOME = "/tmp"
      XDG_CACHE_HOME  = "/tmp"
    }
  }

  logging_config {
    log_format = "Text"
    log_group  = aws_cloudwatch_log_group.booker.name
  }

  depends_on = [aws_iam_role_policy.lambda]
}
