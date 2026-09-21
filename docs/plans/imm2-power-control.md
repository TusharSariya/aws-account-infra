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

The Mac operator path uses the existing privileged account. The laptop now has a separate generated SSH key and dedicated account `capacity` in slot2 on each controller with `custom:pr` power/restart permission. Its generated IPMI password is held in a private file, not supplied by an operator at runtime. Do not copy the Mac private key into Git, Helm values, images or Terraform state. Preserve independently recoverable credential references and known-host trust.

## Library and adapter boundary

Updated after live comparison: use pyghmi1.6.19 as the primary power transport. Structured IPMI status and idempotent ensure-on worked from the laptop against both controllers using the dedicated power-only account. Paramiko4.0.0 also passed live SSH checks, but Paramiko5 removed the legacy RSA signature these units require. Keep SSH as the operator/diagnostic path; there is no automatic transport fallback after an uncertain write. See [the implemented power adapter](../../controllers/homelab-capacity/README.md).

The adapter exposes registered host identities and bounded `get_power` / `ensure_on` operations. It sends only allowlisted commands, validates the complete response, distinguishes unknown/unreachable from off, uses bounded connection/command timeouts and re-reads actual state before retrying a timed-out action. IMM2 can report command errors while SSH exits zero, as the failed enrollment demonstrated. Never classify success from exit status alone. Do not expose arbitrary commands, reset, forced power-off, account changes or firmware actions through routine scaling.

For routine shutdown, the coordinator drains workloads, releases retained storage, deletes only owned disposable compute and requests orderly Proxmox shutdown; IMM2 observes completion. An IMM2 hard-off is not a fallback for a failed drain. Power acceptance must not block a short provider RPC throughout firmware boot; publish progress and reconcile asynchronously.

`pyghmi` is the selected power transport following live testing; SSH public keys do not authenticate IPMI. Its separate generated credential path is now provisioned on the laptop. We do not need to implement an SSH or IPMI protocol stack.

Sources: [Paramiko SSH client](https://docs.paramiko.org/en/stable/api/client.html), [Lenovo IMM2 users command](https://pubs.lenovo.com/imm2/dw1lm_r_userscommand), [Lenovo IMM2 IPMI support](https://pubs.lenovo.com/imm2/dw1lm_t_managingtheimmwithipmi), and the repository's [captured firmware CLI help](../research/imm2-cli-help.md).

## Implementation progress

The bounded pyghmi power adapter passed live status and idempotent ensure-on checks against both controllers from the laptop. The isolated one-slot external-gRPC prototype also passed ordinary pending-Job demand -> fresh VM creation/join -> networking and CSI readiness -> workload completion, including a second fresh identity. The physical host was already on; cold physical wake and Kueue admission were not part of this proof. See [recorded evidence](../../prototypes/one-slot-autoscaler/evidence.md). Production ownership transfer remains separate. The full build sequence and policy contract are in [the IaC plan](homelab-autoscaling-iac.md).
