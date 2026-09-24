# Disposable VM only. Never include the retained Talos VMs in this state.
provider "proxmox" {
  insecure = false
}
variable "node_name" {
  type    = string
  default = "pve"
}
variable "image_url" {
  type        = string
  description = "Dated Ubuntu 26.04 amd64 cloud image HTTPS URL verified against Ubuntu SHA256SUMS"
  validation {
    condition     = startswith(var.image_url, "https://cloud-images.ubuntu.com/")
    error_message = "Use an official Ubuntu image."
  }
}
variable "image_sha256" {
  type = string
  validation {
    condition     = can(regex("^[a-f0-9]{64}$", var.image_sha256))
    error_message = "Pin the published SHA256 digest."
  }
}
variable "ssh_public_key" {
  type = string
}
variable "vm_id" {
  type    = number
  default = 2260
  validation {
    condition     = var.vm_id >= 2000 && var.vm_id <= 2999
    error_message = "Validation VMs use their own ID range, never 100, 102 or 103."
  }
}
resource "proxmox_download_file" "ubuntu" {
  node_name          = var.node_name
  datastore_id       = "local"
  content_type       = "import"
  file_name          = "ubuntu-26.04-validation.qcow2"
  url                = var.image_url
  checksum           = var.image_sha256
  checksum_algorithm = "sha256"
}
resource "proxmox_virtual_environment_vm" "validation" {
  node_name       = var.node_name
  vm_id           = var.vm_id
  name            = "ubuntu-enrollment-validation"
  description     = "Disposable mixed Ubuntu-Talos enrollment validation"
  on_boot         = false
  started         = true
  stop_on_destroy = true
  cpu {
    cores = 2
    type  = "host"
  }
  memory { dedicated = 4096 }
  serial_device { device = "socket" }
  disk {
    datastore_id = "local-lvm"
    import_from  = proxmox_download_file.ubuntu.id
    interface    = "scsi0"
    size         = 24
  }
  network_device {
    bridge      = "vmbr0"
    model       = "virtio"
    mac_address = "02:00:00:00:22:60"
  }
  initialization {
    datastore_id = "local-lvm"
    ip_config {
      ipv4 { address = "dhcp" }
    }
    user_account {
      username = "ubuntu"
      keys     = [var.ssh_public_key]
    }
  }
}
output "validation_vm_id" { value = proxmox_virtual_environment_vm.validation.vm_id }
