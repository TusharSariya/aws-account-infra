variable "node_name" {
  description = "Existing Proxmox node hosting the initial two guests."
  type        = string
  default     = "pve"
}

variable "vm_creation_approved" {
  description = "Explicit approval for VM creation. Speculative preview may assume approval; it does not establish readiness."
  type        = bool
  default     = false
}

variable "vms" {
  description = "Non-secret guest identities and initial capacity. IPs describe DHCP reservations; no cloud-init is installed."
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
    condition = (
      length(var.vms) == 1 &&
      alltrue([for name, vm in var.vms :
        name == "talos-worker-01" && vm.vm_id == 102 && vm.ipv4_address == "10.0.0.222"
      ])
    )
    error_message = "Only existing worker 01 (VM 102, .222) belongs here. Never reintroduce retired VM 100."
  }
  validation {
    condition = alltrue([for vm in var.vms :
      vm.vm_id >= 100 && vm.vm_id == floor(vm.vm_id) &&
      vm.vcpus >= 2 && vm.vcpus % 2 == 0 &&
      vm.memory_gib > 0 && vm.memory_gib == floor(vm.memory_gib) &&
      length(vm.disks_gib) >= 1 && length(vm.disks_gib) <= 2 &&
      alltrue([for size in vm.disks_gib : size > 0 && size == floor(size)]) &&
      can(regex("^02:([0-9a-fA-F]{2}:){4}[0-9a-fA-F]{2}$", vm.mac_address)) &&
      can(regex("^10\\.0\\.0\\.22[0-3]$", vm.ipv4_address)) &&
      vm.startup_order >= 1 && vm.startup_order <= 2 &&
      vm.startup_order == floor(vm.startup_order)
    ])
    error_message = "Guest capacity and identity must use valid whole-unit allocations and the reserved .220-.223 range."
  }
}
