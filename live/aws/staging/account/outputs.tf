output "github_oidc_provider_arn" {
  value = aws_iam_openid_connect_provider.github.arn
}

output "github_plan_role_arn" {
  value       = aws_iam_role.github_plan.arn
  description = "role-to-assume for the tofu-plan workflow (PRs)."
}

output "github_apply_role_arn" {
  value       = aws_iam_role.github_apply.arn
  description = "role-to-assume for the tofu-apply workflow (main)."
}

output "ecr_pull_user_name" {
  value       = aws_iam_user.ecr_pull.name
  description = "IAM user the homelab nodes pull ECR images as; mint its access key manually and store in Ansible Vault."
}
