output "bucket_name" { value = aws_s3_bucket.digest.id }
output "table_name" { value = aws_dynamodb_table.digest.name }
output "functions" { value = { for name, f in aws_lambda_function.digest : name => f.function_name } }
output "failure_queue_url" { value = aws_sqs_queue.failures.url }
