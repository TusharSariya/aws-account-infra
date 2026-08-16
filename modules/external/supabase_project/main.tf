resource "supabase_project" "this" {
  organization_id   = var.organization_id
  name              = var.project_name
  database_password = var.database_password
  region            = var.region
  instance_size     = "micro"
  # Provider 1.9.1 deprecates this control because Supabase is removing the legacy
  # key system, but omitting it leaves the hosted default authoritative. Keep the
  # explicit fail-safe until a compatibility-gated provider removes the field.
  legacy_api_keys_enabled = false

  lifecycle {
    ignore_changes = [database_password]
  }
}

resource "supabase_settings" "this" {
  project_ref = supabase_project.this.id

  api = jsonencode({
    db_schema            = "public"
    db_extra_search_path = "public,extensions"
    max_rows             = 1000
  })

  auth = jsonencode({
    site_url                         = var.site_url
    uri_allow_list                   = join(",", var.redirect_urls)
    disable_signup                   = true
    external_anonymous_users_enabled = false
  })
}
