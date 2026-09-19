variable "node_name" {
  description = "Observed Proxmox node name on the secondary PVE host at 10.0.0.223."
  type        = string
}

variable "host_readiness_confirmed" {
  description = "Set only after .225 collision, ECC, memory-reserve, recovery, and storage checks pass."
  type        = bool
  default     = false
}

variable "vms" {
  description = "Non-secret identity and fixed hardware for the secondary PVE guest."
  type = map(object({
    vm_id         = number
    vcpus         = number
    memory_gib    = number
    disks_gib     = list(number)
    mac_address   = string
    ipv4_address  = string
    iso_file_id   = string
    startup_order = number
    guest_agent   = bool
    cpu_limit     = number
    cpu_units     = number
    started       = optional(bool, false)
    on_boot       = optional(bool, false)
  }))

  validation {
    condition = length(var.vms) == 1 && alltrue([for name, vm in var.vms :
      name == "talos-worker-02" && vm.vm_id == 103 && vm.vcpus == 38 &&
      vm.memory_gib == 112 && length(vm.disks_gib) == 1 && vm.disks_gib[0] == 320 &&
      lower(vm.mac_address) == "02:42:00:00:01:03" && vm.ipv4_address == "10.0.0.225" &&
      vm.iso_file_id == "local:iso/talos-v1.13.9-qemu-gvisor-amd64.iso" && vm.guest_agent && vm.on_boot
    ])
    error_message = "Secondary worker identity or fixed hardware drifted."
  }
}
