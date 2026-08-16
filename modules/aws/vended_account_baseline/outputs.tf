output "state_bucket_name" {
  value = aws_s3_bucket.state.id
}

output "plan_role_arn" {
  value = aws_iam_role.github_plan.arn
}

output "apply_role_arn" {
  value = aws_iam_role.github_apply.arn
}

output "package_role_arn" {
  value = aws_iam_role.github_package.arn
}

output "lambda_releases_bucket" {
  value = aws_s3_bucket.lambda_releases.id
}
