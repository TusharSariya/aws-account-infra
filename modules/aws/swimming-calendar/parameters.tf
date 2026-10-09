locals {
  sync_parameter_arns = { for name in var.sync_parameter_reads : name => "arn:aws:ssm:${var.region}:${var.aws_account_id}:parameter${name}" }
}

resource "aws_iam_role_policy" "sync_parameters" {
  count = length(var.sync_parameter_reads) > 0 ? 1 : 0
  role  = aws_iam_role.lambda["sync"].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = concat([
      { Effect = "Allow", Action = ["ssm:GetParameter"], Resource = values(local.sync_parameter_arns) }
      ], length(var.sync_parameter_writes) > 0 ? [
      { Effect = "Allow", Action = ["ssm:PutParameter"], Resource = [for name in var.sync_parameter_writes : local.sync_parameter_arns[name]] }
    ] : [])
  })
}
