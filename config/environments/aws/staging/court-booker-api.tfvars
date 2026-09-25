# Inputs for the HTTP court-booker-api zip root only.
# Packaging a zip does not retarget Lambda until booker_api_zip_key is a
# stable/ key and this unit is applied.

aws_account_id             = "992382747916"
region                     = "us-east-1"
aws_profile                = "admin"
terraform_deploy_role_name = "TerraformDeploy"

default_tags = {
  managed_by = "opentofu"
  repo       = "aws-account-infra"
}

booker_api_zip_key   = "stable/court-booker/e1516dc74b9b036b0cc19df30b1cce49c5799f98.zip"
api_schedule_enabled = true
alert_email          = "tushar.97@hotmail.com"
