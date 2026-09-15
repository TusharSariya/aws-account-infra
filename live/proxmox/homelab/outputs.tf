output "vm_plan" {
  description = "Declared VM capacity and DHCP identities; not observed guest addresses."
  value       = { for name, vm in var.vms : name => merge(vm, { memory_gib = var.ci_runner_enabled && name == "talos-worker-01" ? 156 : vm.memory_gib }) }
}

output "capacity" {
  value = {
    vcpus             = local.total_vcpus
    memory_gib        = local.total_memory_gib
    primary_disks_gib = local.total_guest_disks_gib
    efi_disk_count    = length(var.vms) + (var.ci_runner_enabled ? 1 : 0)
  }
}
