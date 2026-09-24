# Preserve the existing YMCA resources and API hostname while extracting the shared module.
moved {
  from = aws_s3_object.release
  to   = module.calendar.aws_s3_object.release
}
moved {
  from = aws_s3_bucket.snapshot
  to   = module.calendar.aws_s3_bucket.snapshot
}
moved {
  from = aws_s3_bucket_versioning.snapshot
  to   = module.calendar.aws_s3_bucket_versioning.snapshot
}
moved {
  from = aws_s3_bucket_server_side_encryption_configuration.snapshot
  to   = module.calendar.aws_s3_bucket_server_side_encryption_configuration.snapshot
}
moved {
  from = aws_s3_bucket_public_access_block.snapshot
  to   = module.calendar.aws_s3_bucket_public_access_block.snapshot
}
moved {
  from = aws_s3_bucket_lifecycle_configuration.snapshot
  to   = module.calendar.aws_s3_bucket_lifecycle_configuration.snapshot
}
moved {
  from = aws_s3_bucket_policy.snapshot
  to   = module.calendar.aws_s3_bucket_policy.snapshot
}
moved {
  from = aws_sqs_queue.failures
  to   = module.calendar.aws_sqs_queue.failures
}
moved {
  from = aws_cloudwatch_log_group.lambda
  to   = module.calendar.aws_cloudwatch_log_group.lambda
}
moved {
  from = aws_iam_role.lambda
  to   = module.calendar.aws_iam_role.lambda
}
moved {
  from = aws_iam_role_policy.lambda
  to   = module.calendar.aws_iam_role_policy.lambda
}
moved {
  from = aws_lambda_function.app
  to   = module.calendar.aws_lambda_function.app
}
moved {
  from = aws_lambda_function_event_invoke_config.sync
  to   = module.calendar.aws_lambda_function_event_invoke_config.sync
}
moved {
  from = aws_iam_role.scheduler
  to   = module.calendar.aws_iam_role.scheduler
}
moved {
  from = aws_iam_role_policy.scheduler
  to   = module.calendar.aws_iam_role_policy.scheduler
}
moved {
  from = aws_scheduler_schedule.refresh
  to   = module.calendar.aws_scheduler_schedule.refresh
}
moved {
  from = aws_scheduler_schedule.health
  to   = module.calendar.aws_scheduler_schedule.health
}
moved {
  from = aws_apigatewayv2_api.feed
  to   = module.calendar.aws_apigatewayv2_api.feed
}
moved {
  from = aws_apigatewayv2_integration.feed
  to   = module.calendar.aws_apigatewayv2_integration.feed
}
moved {
  from = aws_apigatewayv2_route.feed
  to   = module.calendar.aws_apigatewayv2_route.feed
}
moved {
  from = aws_cloudwatch_log_group.api
  to   = module.calendar.aws_cloudwatch_log_group.api
}
moved {
  from = aws_apigatewayv2_stage.feed
  to   = module.calendar.aws_apigatewayv2_stage.feed
}
moved {
  from = aws_lambda_permission.api
  to   = module.calendar.aws_lambda_permission.api
}
moved {
  from = aws_cloudwatch_metric_alarm.errors
  to   = module.calendar.aws_cloudwatch_metric_alarm.errors
}
moved {
  from = aws_cloudwatch_metric_alarm.delivery
  to   = module.calendar.aws_cloudwatch_metric_alarm.delivery
}
