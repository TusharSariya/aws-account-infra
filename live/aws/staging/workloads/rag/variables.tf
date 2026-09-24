# --- Environment inputs (config/environments/aws/staging/rag.tfvars) ---
variable "aws_account_id" {
  type = string
}

variable "region" {
  type    = string
  default = "us-east-1"
}

variable "aws_profile" {
  type    = string
  default = "admin"
}

variable "terraform_deploy_role_name" {
  type    = string
  default = "TerraformDeploy"
}

variable "default_tags" {
  type    = map(string)
  default = {}
}

# GitHub repo whose Actions runs are trusted to assume the ECR-push OIDC role
# (see image_push_oidc.tf) — the workload repo that builds these images, not
# this infra repo (that trust lives in the account stack's github_owner/repo).
variable "ecr_push_github_owner" {
  type    = string
  default = ""
}
variable "ecr_push_github_repo" {
  type    = string
  default = ""
}

# --- rag-specific ---
variable "ecr_repos" {
  type = list(string)
  # Statically-declared repos only — the excalidraw-tf-rag repo's CI now
  # creates workload-image repos on demand (see build-push-images.yml there
  # and this stack's image_push_oidc.tf for the IAM permissions backing it).
  # Leave empty unless a repo genuinely needs to exist before any image is
  # pushed, or needs settings CI's create-on-push flow doesn't set. Named as
  # <github-repo>/<path-to-image> if populated, so names never collide.
  default     = []
  description = "ECR repos to create statically, one per image. Usually empty — most repos are created ad-hoc by CI."
}
