terraform {
  required_version = ">= 1.8"
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 6.5" }
  }
  backend "s3" {
    bucket         = "tofu-state-992382747916-us-east-1"
    key            = "retired/network-ips/terraform.tfstate"
    region         = "us-east-1"
    dynamodb_table = "tofu-locks"
    encrypt        = true
  }
}
variable "aws_profile" {
  type    = string
  default = "admin"
}
provider "aws" {
  alias               = "ohio"
  region              = "us-east-2"
  profile             = var.aws_profile != "" ? var.aws_profile : null
  allowed_account_ids = ["992382747916"]
  dynamic "assume_role" {
    for_each = var.aws_profile != "" ? [1] : []
    content { role_arn = "arn:aws:iam::992382747916:role/TerraformDeploy" }
  }
}
provider "aws" {
  alias               = "california"
  region              = "us-west-1"
  profile             = var.aws_profile != "" ? var.aws_profile : null
  allowed_account_ids = ["992382747916"]
  dynamic "assume_role" {
    for_each = var.aws_profile != "" ? [1] : []
    content { role_arn = "arn:aws:iam::992382747916:role/TerraformDeploy" }
  }
}
