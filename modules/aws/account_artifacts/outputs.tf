output "domain_arn" {
  value = aws_codeartifact_domain.infra.arn
}

output "domain_name" {
  value = aws_codeartifact_domain.infra.domain
}

output "sdk_candidate_arn" {
  value = aws_codeartifact_repository.sdk_candidate.arn
}

output "sdk_candidate_repository" {
  value = aws_codeartifact_repository.sdk_candidate.repository
}

output "sdk_stable_arn" {
  value = aws_codeartifact_repository.sdk_stable.arn
}

output "sdk_stable_repository" {
  value = aws_codeartifact_repository.sdk_stable.repository
}

output "kms_key_arn" {
  value = aws_codeartifact_domain.infra.encryption_key
}
