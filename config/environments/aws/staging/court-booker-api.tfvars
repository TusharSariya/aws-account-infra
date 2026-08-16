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

booker_api_zip_key   = "stable/court-booker/56f6af31e49f2c9274e98f20cdade4d169081a42.zip"
api_schedule_enabled = true
# This root is the currently active workload. New vended accounts default to
# disabled, but retaining true here prevents an infrastructure-only rollout
# from silently turning off the existing booking schedule before cutover.
booking_enabled = true
alert_email     = "tushar.97@hotmail.com"
