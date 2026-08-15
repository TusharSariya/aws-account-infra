# Inputs for the AWS staging RAG root only.

aws_account_id             = "992382747916"
region                     = "us-east-1"
aws_profile                = "admin"
terraform_deploy_role_name = "TerraformDeploy"

default_tags = {
  managed_by = "opentofu"
  repo       = "aws-account-infra"
}

# Workload repo trusted to assume this stack's ECR-push OIDC role.
ecr_push_github_owner = "TusharSariyaOrg"
ecr_push_github_repo  = "excalidraw-tf-rag"
