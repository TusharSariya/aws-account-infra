provider "aws" {
  region  = var.region
  profile = var.aws_profile != "" ? var.aws_profile : null

  default_tags {
    tags = {
      managed_by = "opentofu"
      repo       = "aws-account-infra"
      stack      = "organization"
    }
  }
}

data "aws_organizations_organization" "current" {}

resource "aws_organizations_aws_service_access" "iam" {
  service_principal = "iam.amazonaws.com"
}

resource "aws_iam_organizations_features" "root_access" {
  enabled_features = [
    "RootCredentialsManagement",
    "RootSessions",
  ]

  depends_on = [aws_organizations_aws_service_access.iam]
}

locals {
  catalog = jsondecode(file(var.catalog_file))
  declared_paths = distinct(concat(
    flatten([
      for service in values(local.catalog.services) : [
        for account in values(service.accounts) : account.ou_path
      ]
    ]),
    ["Suspended/Accounts"],
  ))
  path_parts = { for path in local.declared_paths : path => split("/", path) }
  level_one  = toset([for parts in values(local.path_parts) : parts[0]])
  level_two_paths = toset([
    for parts in values(local.path_parts) : join("/", slice(parts, 0, 2))
    if length(parts) >= 2
  ])
  level_two = {
    for path in local.level_two_paths : path => split("/", path)
  }
  level_three = {
    for parts in values(local.path_parts) : join("/", slice(parts, 0, 3)) => parts
    if length(parts) == 3
  }
}

resource "aws_organizations_organizational_unit" "level_one" {
  for_each = local.level_one

  name      = each.value
  parent_id = data.aws_organizations_organization.current.roots[0].id
  tags      = { ou_path = each.value }

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_organizations_organizational_unit" "level_two" {
  for_each = local.level_two

  name      = each.value[1]
  parent_id = aws_organizations_organizational_unit.level_one[each.value[0]].id
  tags      = { ou_path = each.key }

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_organizations_organizational_unit" "level_three" {
  for_each = local.level_three

  name      = each.value[2]
  parent_id = aws_organizations_organizational_unit.level_two[join("/", slice(each.value, 0, 2))].id
  tags      = { ou_path = each.key }

  lifecycle {
    prevent_destroy = true
  }
}

output "ou_ids" {
  value = merge(
    { for path, ou in aws_organizations_organizational_unit.level_one : path => ou.id },
    { for path, ou in aws_organizations_organizational_unit.level_two : path => ou.id },
    { for path, ou in aws_organizations_organizational_unit.level_three : path => ou.id },
  )
}
