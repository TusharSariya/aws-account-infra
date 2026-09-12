output "vm_plan" {
  description = "Declared VM capacity and DHCP identities; not observed guest addresses."
  value       = var.vms
}

output "capacity" {
  value = {
    vcpus             = local.total_vcpus
    memory_gib        = local.total_memory_gib
    primary_disks_gib = local.total_guest_disks_gib
    efi_disk_count    = length(var.vms)
  }
}
