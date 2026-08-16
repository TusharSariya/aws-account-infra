terraform {
  required_version = ">= 1.8"

  required_providers {
    supabase = {
      source  = "supabase/supabase"
      version = "= 1.9.1"
    }
  }
}
