output "repository_url" {
  value       = aws_ecr_repository.this.repository_url
  description = "e.g. 992382747916.dkr.ecr.us-east-1.amazonaws.com/graph-rag-query"
}

output "repository_arn" {
  value = aws_ecr_repository.this.arn
}

output "repository_name" {
  value = aws_ecr_repository.this.name
}
