output "github_oidc_provider_arn" {
  value = module.identity.github_oidc_provider_arn
}

output "github_plan_role_arn" {
  value       = module.identity.github_plan_role_arn
  description = "role-to-assume for the tofu-plan workflow (PRs)."
}

output "github_apply_role_arn" {
  value       = module.identity.github_apply_role_arn
  description = "role-to-assume for the tofu-apply workflow (main)."
}

output "github_infra_ecr_push_role_arn" {
  value       = module.identity.github_infra_ecr_push_role_arn
  description = "role-to-assume for .github/workflows/ecr-push.yml (apps/ecr images)."
}

output "github_lambda_candidate_role_arn" {
  value       = module.identity.github_lambda_candidate_role_arn
  description = "role-to-assume on PRs for candidate/<name>/<sha>.zip uploads."
}

output "github_lambda_stable_role_arn" {
  value       = module.identity.github_lambda_stable_role_arn
  description = "role-to-assume on main for stable/<name>/<sha>.zip uploads."
}

output "lambda_releases_bucket" {
  value       = module.identity.lambda_releases_bucket
  description = "Shared Lambda zip releases bucket (candidate/ and stable/ prefixes)."
}

output "github_sdk_candidate_role_arn" {
  value       = module.identity.github_sdk_candidate_role_arn
  description = "role-to-assume for SDK candidate publishes to CodeArtifact sdk-candidate."
}

output "github_sdk_stable_role_arn" {
  value       = module.identity.github_sdk_stable_role_arn
  description = "role-to-assume for SDK stable publishes (GitHub Environment sdk)."
}

output "codeartifact_domain" {
  value       = module.artifacts.domain_name
  description = "CodeArtifact domain for private SDK packages."
}

output "codeartifact_sdk_candidate_repository" {
  value = module.artifacts.sdk_candidate_repository
}

output "codeartifact_sdk_stable_repository" {
  value = module.artifacts.sdk_stable_repository
}

# IAM Roles Anywhere coordinates the homelab nodes pass to aws_signing_helper. All
# three are needed for the credential_process invocation on each kubelet host — feed
# them into the ansible inventory (kubernetes_node_ecr_rolesanywhere_*_arn).
output "ecr_pull_trust_anchor_arn" {
  value       = module.identity.ecr_pull_trust_anchor_arn
  description = "Roles Anywhere trust anchor ARN (CA registered for the homelab ECR-pull identity). null until a CA cert is supplied."
}

output "ecr_pull_profile_arn" {
  value       = module.identity.ecr_pull_profile_arn
  description = "Roles Anywhere profile ARN the node's aws_signing_helper requests against. null until a CA cert is supplied."
}

output "ecr_pull_role_arn" {
  value       = module.identity.ecr_pull_role_arn
  description = "IAM role the homelab nodes assume via Roles Anywhere to pull ECR images. null until a CA cert is supplied."
}

output "cloudtrail_arn" {
  value       = module.governance.cloudtrail_arn
  description = "Multi-region management-event trail. Confirm SNS opt-in mail for security alerts."
}

output "guardduty_detector_id" {
  value = module.governance.guardduty_detector_id
}

output "security_alerts_topic_arn" {
  value       = module.governance.security_alerts_topic_arn
  description = "SNS topic for GuardDuty findings and EventBridge IAM/root alerts. Confirm the subscription email."
}

output "budget_reports_stack_id" {
  value       = module.governance.budget_reports_stack_id
  description = "Nested stack that emails daily, weekly, and monthly Cost Explorer summaries to governance_alert_email."
}

output "manual_governance_followups" {
  value = [
    "Confirm the SNS opt-in mail for topic account-security-alerts (tushar.97@hotmail.com).",
    "Confirm Cost Anomaly mail if AWS asks to verify tushar.97@hotmail.com.",
    "Cost report Lambda uses SES; confirm tushar.97@hotmail.com if a new verification mail arrives.",
    "CDKToolkit stack and cdk-hnb659fds-* roles last used 2024-06-28; destroy with cdk bootstrap cleanup if CDK is retired.",
    "Long-lived keys remain on admin (local tofu), powerUser (MCP), and rag-backup (workload). Prefer aws login / assume TerraformDeploy where possible.",
    "Set governance_contact_phone in staging.tfvars if you want billing/security/operations alternate contacts.",
  ]
}
