# Nested CloudFormation: daily / weekly / monthly cost emails. Deploys with this
# OpenTofu unit (no extra deploy-units.json entry). AWS Budgets Reports are
# console-only (no public API), so the template emails Cost Explorer totals.
resource "aws_cloudformation_stack" "budget_reports" {
  name          = "account-budget-reports"
  template_body = file("${path.module}/budget_reports.cfn.yaml")
  capabilities  = ["CAPABILITY_IAM"]

  parameters = {
    ReportEmail = var.governance_alert_email
    BudgetName  = aws_budgets_budget.monthly.name
  }
}
