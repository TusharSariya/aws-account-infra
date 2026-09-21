# IMM2 power control and verified startup

Recorded 2026-09-21 UTC (September 20 local time). This records an authorized manual startup, not an installed autoscaling controller.

## Verified operation

| Host | IMM2 | Proxmox | Production VMs |
| --- | --- | --- | --- |
| Primary | 10.0.0.98 | 10.0.0.224 | 100 control plane, 102 worker |
| Secondary | 10.0.0.67 | 10.0.0.223 | 103 worker |

Password-free SSH authenticated to both IMM2 controllers using the dedicated Mac RSA key. Both initially returned `power off`. Explicit `power on` commands returned `ok`; subsequent status showed `power on` and firmware startup. Both hosts reached Proxmox and their production VMs autostarted. All three production Kubernetes nodes became Ready, and all Deployments/StatefulSets reached their desired ready replica counts, including Pi-hole and Nexus.

Shutdown cordons cleared automatically during Talos recovery: an explicit uncordon check reported all three nodes already uncordoned. Do not infer a stuck cordon from an early boot snapshot. IMM2 power-on acknowledgement, Proxmox availability, Node Ready, CSI readiness and application readiness are separate milestones.

The laptop prototype control plane remained Ready while the physical servers were off. Prototype VM9104 is intentionally not configured for autostart and remained stopped; it was not part of production recovery. The earlier retained-volume proof is recorded in [the prototype evidence](../../prototypes/disposable-worker-storage/evidence.md).

## SSH enrollment and operator access

IMM2 uses its own account/key store, not a Linux `authorized_keys` file. Authenticate once with the existing account password, run `users` and select the account index matching the login. Both current `USERID` accounts are index1. Add the public key using:

```text
users -1 -pk -add "ssh-rsa BASE64_PUBLIC_KEY"
```

The initial script sent the base64 portion alone, following the abbreviated documentation example; both enrollment and subsequent key authentication failed. Including the `ssh-rsa` prefix worked. Preserve the full public-key type and payload as one quoted argument. Do not replace existing keys, passwords or account permissions while enrolling another key.

Local Mac artifacts (not committed):

- `~/.ssh/imm2_control` and `.pub`: dedicated RSA2048 key pair; private file permissions600, no passphrase for unattended operation.
- `~/.config/aws-account-infra/imm2/ssh_config`: aliases `imm-primary` and `imm-secondary`, explicit key, `IdentitiesOnly`, `BatchMode`, strict known-host checking and host-scoped RSA signature compatibility.
- `~/imm-ssh-setup.sh`: one-time enrollment wizard; validated with Bash syntax and ShellCheck, then exercised by the operator. Passwords are entered only at SSH prompts.

```bash
ssh -F ~/.config/aws-account-infra/imm2/ssh_config imm-primary 'power state'
ssh -F ~/.config/aws-account-infra/imm2/ssh_config imm-secondary 'power state'
# Explicit manual startup:
ssh -F ~/.config/aws-account-infra/imm2/ssh_config imm-primary 'power on'
ssh -F ~/.config/aws-account-infra/imm2/ssh_config imm-secondary 'power on'
```

Current access uses the existing privileged operator account. This is a verified operator path, not the final least-privilege controller credential. Give the Ubuntu laptop its own key and a dedicated account with only the permissions proven necessary for status and power actions. Do not copy the Mac private key into Git, Helm values, images or Terraform state. Preserve independently recoverable credential references and known-host trust.

## Library and adapter boundary

Recommended implementation: Paramiko for Python SSH transport, with a small IMM2-specific adapter. OpenSSH is the already verified operator transport. Paramiko support for these exact firmware/key/algorithm combinations must still be exercised; successful OpenSSH authentication is not a Paramiko integration test.

The adapter exposes registered host identities and bounded `get_power` / `ensure_on` operations. It sends only allowlisted commands, validates the complete response, distinguishes unknown/unreachable from off, uses bounded connection/command timeouts and re-reads actual state before retrying a timed-out action. IMM2 can report command errors while SSH exits zero, as the failed enrollment demonstrated. Never classify success from exit status alone. Do not expose arbitrary commands, reset, forced power-off, account changes or firmware actions through routine scaling.

For routine shutdown, the coordinator drains workloads, releases retained storage, deletes only owned disposable compute and requests orderly Proxmox shutdown; IMM2 observes completion. An IMM2 hard-off is not a fallback for a failed drain. Power acceptance must not block a short provider RPC throughout firmware boot; publish progress and reconcile asynchronously.

`pyghmi` is an alternative for IPMI power control, but SSH public keys do not authenticate IPMI. Switching would require a separately provisioned supported credential path. We do not need to implement an SSH or IPMI protocol stack.

Sources: [Paramiko SSH client](https://docs.paramiko.org/en/stable/api/client.html), [Lenovo IMM2 users command](https://pubs.lenovo.com/imm2/dw1lm_r_userscommand), [Lenovo IMM2 IPMI support](https://pubs.lenovo.com/imm2/dw1lm_t_managingtheimmwithipmi), and the repository's [captured firmware CLI help](../research/imm2-cli-help.md).

## Next implementation slice

Build and test the bounded power adapter against both controllers from management capacity, with response-parser tests for actual on/off/UEFI/error responses. Then connect it to one isolated worker slot: zero-worker demand -> host wake -> PVE ready -> fresh worker creation/join -> networking and CSI ready -> workload execution. Keep this slice separate from production ownership transfer. The full build sequence and policy contract are in [the IaC plan](homelab-autoscaling-iac.md).
