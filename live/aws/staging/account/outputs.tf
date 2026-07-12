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

# IAM Roles Anywhere coordinates the homelab nodes pass to aws_signing_helper. All
# three are needed for the credential_process invocation on each kubelet host — feed
# them into the ansible inventory (kubernetes_node_ecr_rolesanywhere_*_arn).
output "ecr_pull_trust_anchor_arn" {
  value       = aws_rolesanywhere_trust_anchor.ecr_pull.arn
  description = "Roles Anywhere trust anchor ARN (CA registered for the homelab ECR-pull identity)."
}

output "ecr_pull_profile_arn" {
  value       = aws_rolesanywhere_profile.ecr_pull.arn
  description = "Roles Anywhere profile ARN the node's aws_signing_helper requests against."
}

output "ecr_pull_role_arn" {
  value       = aws_iam_role.ecr_pull.arn
  description = "IAM role the homelab nodes assume via Roles Anywhere to pull ECR images."
}
