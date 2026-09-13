# Proxmox OpenTofu access and state

The VM root uses the existing AWS state bucket with its own key:

- Bucket: `tofu-state-992382747916-us-east-1`, region `us-east-1`
- Key: `proxmox/homelab/terraform.tfstate`
- Lock table: `tofu-locks`
- Encryption: S3 server-side encryption; bucket versioning is enabled.

AWS account/workload state keys are unchanged. Initialization selects and checks
this backend; the first apply will write the initial VM state object. No VM
state object or guest creation is claimed merely because initialization passed.
The administrator AWS login remains independent of Proxmox. Use the existing
reviewed AWS deployment workflow to change bucket/table infrastructure.

## Reproduce API identity setup

Run from a trusted administration checkout after verifying the Proxmox SSH host
key through the local console. The bootstrap requires existing root SSH access;
it does not bootstrap SSH or install Tailscale. On a replacement administration
machine, supply its explicitly verified SSH target instead of assuming an alias.

```bash
python3 scripts/proxmox-provider-bootstrap.py --ssh-target server-10-42
```

This creates `homelab-tofu@pve` with no login password, custom roles, and the
privilege-separated `provider` token. Both the user and token receive only:

| Scope | Permissions |
| --- | --- |
| `/` | `Sys.Audit` for API discovery |
| `/vms/100`, `/vms/102` | Allocate, audit, configure CPU/memory/disks/CDROM/network/hardware/options, power operations and guest-agent audit |
| `/storage/local-lvm` | Audit and allocate disk space |
| `/storage/local` | Audit existing ISO storage |
| `/sdn/zones/localnetwork/vmbr0` | Use the existing bridge |

The token does not receive Administrator, host modification, user/ACL management,
or VM allocation outside these IDs. VM allocation permissions also permit
removing these two guests: review plans and preserve state/backups. No claim of
proven create/update compatibility is made before the first approved apply.

The local credential is stored outside Git at
`~/.config/aws-account-infra/proxmox/credentials.json` with mode 0600 in a private
directory. Values are captured over SSH and never printed. Do not invoke the
bootstrap's internal `--remote` mode directly. Existing credentials/tokens and
unexpected roles/ACLs stop the helper instead of being overwritten. The script
is reproducible on a replacement host; it deliberately does not silently rotate
an existing identity.

The token currently has no explicit expiry. Revoke/reissue after credential loss
or suspected exposure using the recovery procedure below. It is independent of
the Tailscale node key, which has its own expiry policy.

## Verify and preview

Tailscale must be connected. The endpoint is `https://pve.tail2f646b.ts.net/`.
TLS verification remains enabled. Serve terminates trusted browser/API-facing
HTTPS and proxies to Proxmox over local-loopback HTTPS using its already
configured `https+insecure` upstream. This does not make port 8006 publicly
accessible or enroll CI in the tailnet.

```bash
python3 scripts/proxmox-tofu.py check
python3 scripts/proxmox-tofu.py init
python3 scripts/proxmox-tofu.py validate
python3 scripts/proxmox-tofu.py plan
```

The wrapper defaults `AWS_PROFILE` to `admin`, loads the private API credential
into the child process environment, and does not put it in argv or tfvars. The
check exercises authenticated API discovery and verifies VM allocation allowed
for IDs 100/102 and absent for 101. The speculative plan assumes
`vm_creation_approved=true` to preview the proposed resources; it does not mean
remaining readiness checks have passed. The wrapper cannot apply or save an
executable plan, and removes inherited CLI/log overrides. The normal variable
default remains false. Any future creation requires explicit operator approval,
a fresh reviewed plan and the outstanding network/state checks. The operator
has deferred the clean-machine restore test; it remains recorded as untested.

The new S3 backend requires AWS authentication for live initialization and plans.
Offline validation continues using `init -backend=false` plus mocked tests.
The deployment manifest now enables this root for live CI. See
[GitHub CI setup](CI.md) for the separate read-only plan identity, environment
secrets, Tailscale OIDC trust and the apply-label workflow.

## Credential loss, rotation and state recovery

If the Mac is lost but Proxmox survives, regain independently trusted root SSH or
console access. Inspect the user, token metadata and ACLs without dumping token
secrets. Explicitly revoke the lost token:

```bash
pveum user token remove homelab-tofu@pve provider
```

On a replacement administration machine, rerun the bootstrap with a new private
output path and a verified SSH target. Existing matching roles/user/ACLs can be
reused. Keep any working credential until replacement access has been verified.
Revocation invalidates existing token users, so coordinate this with any future
CI integration. A failed bootstrap can leave public roles/ACLs or a token;
inspect and revoke that token before retrying. Never delete unrelated identities.

If Proxmox is lost, recreate its trusted local network/SSH and Tailscale access,
then rerun the bootstrap; the same role definitions are versioned here. Do not
restore old API secrets as a prerequisite. Verify new host keys through the
console and update the endpoint explicitly if re-enrollment changes its name.

Recover AWS administrator access independently, initialize the same backend key,
and inspect current state against the actual recovered host before planning.
For a corrupt/deleted state object, retrieve a known-good S3 object version into
a private recovery directory and inspect it before an explicit state recovery;
do not automatically overwrite the current state. State and executable plans
must stay out of Git and logs. A fresh-machine/backend restore rehearsal and
first persisted VM state remain untested.

Sources: [pinned provider authentication](https://github.com/bpg/terraform-provider-proxmox/blob/v0.112.0/docs/index.md),
[Proxmox privileges](https://pve.proxmox.com/pve-docs/pveum.1.html#_privileges).
Installed PVE 9.2.11 CLI help and API permission checks were also used to verify
actual command behavior and scope.
