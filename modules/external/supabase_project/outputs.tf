output "project" {
  value = {
    project_ref  = supabase_project.this.id
    project_name = supabase_project.this.name
  }
}
