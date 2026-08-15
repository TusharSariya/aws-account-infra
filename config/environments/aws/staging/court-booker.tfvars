# Inputs for the Playwright court-booker root only.
# Pushing an image does not retarget Lambda until booker_image_tag is updated
# and this unit is applied.

aws_account_id             = "992382747916"
region                     = "us-east-1"
aws_profile                = "admin"
terraform_deploy_role_name = "TerraformDeploy"

default_tags = {
  managed_by = "opentofu"
  repo       = "aws-account-infra"
}

booker_image_tag = "56f6af3"
schedule_enabled = false
alert_email      = "tushar.97@hotmail.com"
