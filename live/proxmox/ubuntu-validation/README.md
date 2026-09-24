Disposable validation state is local and must be retained outside Git until destroy.
Set `PROXMOX_VE_ENDPOINT` and `PROXMOX_VE_API_TOKEN` from private credentials, then:

```
tofu init -backend-config=path=/PRIVATE/validation.tfstate
tofu plan -var-file=/PRIVATE/ubuntu-validation.tfvars -out=/PRIVATE/ubuntu-validation.tfplan
tofu apply /PRIVATE/ubuntu-validation.tfplan
```

The private var file supplies the dated Ubuntu 26.04 cloud image URL, published
SHA256 and an operator public SSH key. Record the DHCP lease for MAC
`02:00:00:00:22:60`; use it in a separate private Ansible inventory with
`worker_enrollment_validation_vm: true`, `worker_runtime_gpu: false`, and node
name `ubuntu-enrollment-validation`. Use the same worker roles as the desktop.
Keep this VM under an existing server maintenance hold while testing. Do not wake
or alter the servers outside their existing power coordinator. Verify VM ID 2260
is unused before applying. Destroy only this root after evidence is captured.

Use a privilege-separated token with a short expiry. The validated permission
scope is VM 2260 (allocate, audit, configuration and power), `/storage/local`
(allocate, allocate template/space and audit), `/storage/local-lvm` (allocate
space and audit), `/nodes/pve` (audit and access network for URL metadata), and
`/sdn/zones/localnetwork/vmbr0` (use). Revoke its ACLs and token after destroying
the VM and image. Never widen the shared deployment token. Proxmox removes the
VM ACL when deleting a VM, so restore that temporary ACL before a replacement.

The image uses the existing `import` content type on `local` and API-backed
`disk.import_from`; `disk.file_id` would require provider SSH access. No provider
SSH credential is required. Wait for `cloud-init status --wait` before Ansible.
Use smaller VM reservations (kubelet 100m/256Mi, system 200m/512Mi) for this
2 CPU/4 GiB proof. A first check-mode run cannot install a hypothetical repository;
record that limitation, then verify actual apply, repeat apply, and check/diff.

The Ubuntu release URL and checksum are pinned in
`config/environments/proxmox/ubuntu-validation/validation.tfvars`. The direct PVE
certificate covers `localhost`, but not the current LAN address. On this Mac, a
verified localhost SSH tunnel plus the public PVE CA works with Linux OpenTofu;
macOS Go uses its platform trust store. Keep CA material and token values private,
pass tokens by environment, and retain the local state path through cleanup.
