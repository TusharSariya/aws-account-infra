output "capacity" {
  value = {
    vcpus             = local.total_vcpus
    memory_gib        = local.total_memory_gib
    primary_disks_gib = local.total_guest_disks_gib
    efi_disk_count    = length(var.vms)
  }
}
