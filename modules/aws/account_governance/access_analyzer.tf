# External-access analyzer is free. Unused-access analysis is paid ($0.20 per
# IAM user/role per month) and is intentionally not created.
resource "aws_accessanalyzer_analyzer" "external" {
  analyzer_name = "account-external"
  type          = "ACCOUNT"
}
