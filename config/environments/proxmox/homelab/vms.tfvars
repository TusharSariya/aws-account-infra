# Main control plane relocated to Ubuntu; VM 100 is a protected stale recovery copy.
vms = {
  talos-worker-01 = {
    vm_id         = 102
    vcpus         = 38
    memory_gib    = 112
    disks_gib     = [320, 1200]
    mac_address   = "02:42:00:00:01:02"
    ipv4_address  = "10.0.0.222"
    iso_file_id   = "local:iso/talos-v1.13.9-qemu-gvisor-amd64.iso"
    started       = false
    on_boot       = true
    startup_order = 2
    guest_agent   = true
    cpu_limit     = 0
    cpu_units     = 100
  }
}

# Retired CI VM: do not re-enable on the post-DIMM-move 128-GiB host.
ci_runner_enabled        = false
ci_runner_started        = false
ci_runner_ssh_public_key = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIB1o8n6cw3NhDQ9uCuQzUqtm/ZfcU6zGH9LVgZvUNzz8 macbook"
