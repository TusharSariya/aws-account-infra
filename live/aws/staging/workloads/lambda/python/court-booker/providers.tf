locals {
  terraform_deploy_role_arn = "arn:aws:iam::${var.aws_account_id}:role/${var.terraform_deploy_role_name}"
  default_tags              = merge(var.default_tags, { stack = "court-booker-api" })
  zip_bucket_name           = "lambda-releases-${var.aws_account_id}-${var.region}"
}

provider "aws" {
  region = var.region

  profile = var.aws_profile != "" ? var.aws_profile : null

  dynamic "assume_role" {
    for_each = var.aws_profile != "" ? [1] : []
    content {
      role_arn     = local.terraform_deploy_role_arn
      session_name = "tofu-court-booker-api"
    }
  }

  default_tags {
    tags = local.default_tags
  }
}
