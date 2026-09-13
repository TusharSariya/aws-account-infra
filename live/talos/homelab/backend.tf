terraform {
  backend "s3" {
    bucket         = "tofu-state-992382747916-us-east-1"
    key            = "talos/homelab/terraform.tfstate"
    region         = "us-east-1"
    dynamodb_table = "tofu-locks"
    encrypt        = true
  }
}
