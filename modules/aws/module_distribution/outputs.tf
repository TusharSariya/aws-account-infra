output "bucket_name" {
  value = aws_s3_bucket.modules.id
}

output "publisher_role_arn" {
  value = aws_iam_role.publisher.arn
}
