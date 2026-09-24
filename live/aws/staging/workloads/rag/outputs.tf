output "ecr_repo_urls" {
  value       = { for k, m in module.ecr : k => m.repository_url }
  description = "Map of image name → ECR URL for statically-declared repos only. Empty under the default ecr_repos = []; CI-created repos are not tracked here."
}

output "ecr_push_role_arn" {
  value       = aws_iam_role.github_ecr_push.arn
  description = "role-to-assume for the excalidraw-tf-rag repo's build/push CI workflow."
}
