locals {
  terraform_deploy_role_arn = "arn:aws:iam::${var.aws_account_id}:role/${var.terraform_deploy_role_name}"
  default_tags              = merge(var.default_tags, { stack = "rag" })
}

provider "aws" {
  region  = var.region
  profile = var.aws_profile

  assume_role {
    role_arn     = local.terraform_deploy_role_arn
    session_name = "tofu-rag"
  }

  default_tags {
    tags = local.default_tags
  }
}
