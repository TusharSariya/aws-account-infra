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

output "github_lambda_candidate_role_arn" {
  value       = aws_iam_role.github_lambda_package["candidate"].arn
  description = "role-to-assume on PRs for candidate/<name>/<sha>.zip uploads."
}

output "github_lambda_stable_role_arn" {
  value       = aws_iam_role.github_lambda_package["stable"].arn
  description = "role-to-assume on main for stable/<name>/<sha>.zip uploads."
}

output "lambda_releases_bucket" {
  value       = aws_s3_bucket.lambda_releases.id
  description = "Shared Lambda zip releases bucket (candidate/ and stable/ prefixes)."
}

output "github_sdk_candidate_role_arn" {
  value       = aws_iam_role.github_sdk_candidate.arn
  description = "role-to-assume for SDK candidate publishes to CodeArtifact sdk-candidate."
}

output "github_sdk_stable_role_arn" {
  value       = aws_iam_role.github_sdk_stable.arn
  description = "role-to-assume for SDK stable publishes (GitHub Environment sdk)."
}

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
