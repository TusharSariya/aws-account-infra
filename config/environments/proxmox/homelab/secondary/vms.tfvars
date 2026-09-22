vms = {
  talos-worker-02 = {
    vm_id         = 103
    vcpus         = 38
    memory_gib    = 112
    disks_gib     = [320]
    mac_address   = "02:42:00:00:01:03"
    ipv4_address  = "10.0.0.225"
    iso_file_id   = "local:iso/talos-v1.13.9-qemu-gvisor-amd64.iso"
    startup_order = 2
    guest_agent   = true
    cpu_limit     = 0
    cpu_units     = 100
    started       = false
    on_boot       = true
  }
}
