# Endpoint and API credentials come from PROXMOX_VE_* environment variables.
# Establish trusted HTTPS access before the first live plan. No SSH provider
# connection is needed for creating blank disks from existing local ISOs.
provider "proxmox" {
  insecure = false
}
