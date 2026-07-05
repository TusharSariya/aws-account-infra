locals {
  terraform_deploy_role_arn = "arn:aws:iam::${var.aws_account_id}:role/${var.terraform_deploy_role_name}"
  default_tags              = merge(var.default_tags, { stack = "account" })
}

provider "aws" {
  region = var.region

  # Local runs authenticate via a named profile that assumes the deploy role.
  # CI runs authenticate via GitHub OIDC (ambient env credentials) and pass
  # aws_profile="" — then the provider uses those creds directly and skips both
  # the profile and the assume_role (the OIDC role is already the deploy identity).
  profile = var.aws_profile != "" ? var.aws_profile : null

  dynamic "assume_role" {
    for_each = var.aws_profile != "" ? [1] : []
    content {
      role_arn     = local.terraform_deploy_role_arn
      session_name = "tofu-account"
    }
  }

  default_tags {
    tags = local.default_tags
  }
}
