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

output "github_infra_ecr_push_role_arn" {
  value       = aws_iam_role.github_infra_ecr_push.arn
  description = "role-to-assume for .github/workflows/ecr-push.yml (apps/ecr images)."
}

output "github_lambda_package_role_arn" {
  value       = aws_iam_role.github_lambda_package.arn
  description = "role-to-assume for .github/workflows/lambda-package.yml (apps/lambda zips)."
}

output "github_sdk_candidate_role_arn" {
  value       = aws_iam_role.github_sdk_candidate.arn
  description = "role-to-assume for SDK candidate publishes to CodeArtifact sdk-candidate."
}

output "github_sdk_stable_role_arn" {
  value       = aws_iam_role.github_sdk_stable.arn
  description = "role-to-assume for SDK stable publishes (GitHub Environment sdk)."
}

output "codeartifact_domain" {
  value       = aws_codeartifact_domain.infra.domain
  description = "CodeArtifact domain for private SDK packages."
}

output "codeartifact_sdk_candidate_repository" {
  value = aws_codeartifact_repository.sdk_candidate.repository
}

output "codeartifact_sdk_stable_repository" {
  value = aws_codeartifact_repository.sdk_stable.repository
}

# IAM Roles Anywhere coordinates the homelab nodes pass to aws_signing_helper. All
# three are needed for the credential_process invocation on each kubelet host — feed
# them into the ansible inventory (kubernetes_node_ecr_rolesanywhere_*_arn).
output "ecr_pull_trust_anchor_arn" {
  value       = one(aws_rolesanywhere_trust_anchor.ecr_pull[*].arn)
  description = "Roles Anywhere trust anchor ARN (CA registered for the homelab ECR-pull identity). null until a CA cert is supplied."
}

output "ecr_pull_profile_arn" {
  value       = one(aws_rolesanywhere_profile.ecr_pull[*].arn)
  description = "Roles Anywhere profile ARN the node's aws_signing_helper requests against. null until a CA cert is supplied."
}

output "ecr_pull_role_arn" {
  value       = one(aws_iam_role.ecr_pull[*].arn)
  description = "IAM role the homelab nodes assume via Roles Anywhere to pull ECR images. null until a CA cert is supplied."
}
