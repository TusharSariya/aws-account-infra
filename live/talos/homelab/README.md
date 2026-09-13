# Talos configuration through OpenTofu CI

This root adopts the existing control plane separately from the Proxmox VM
root. It pins siderolabs/talos 0.11.0 and OpenTofu 1.11.5 in CI, retaining Talos
v1.13.9/Kubernetes v1.36.3 and the existing cluster secrets and public patches.
It does not create VMs, generate new cluster secrets or bootstrap the live
cluster again. Worker configuration is declared but disabled in cluster.tfvars
until its separately reviewed installation change.

## Review and deployment

Public desired configuration remains in config/environments/proxmox/homelab/talos.
Changes there select this deploy unit. PRs run an authenticated preflight and
plan through an ephemeral Tailscale CI runner with subnet-route acceptance.
After reviewing the plan, add the existing `apply` label. CI applies before
merge and the apply gate blocks merge on failure. Talos is ordered after the
Proxmox root when both are selected. Talos changes do not require a local apply.

scripts/talos-ci.py uses the hash-verified pinned talosctl only to generate and
validate YAML and inspect the existing cluster/dry-run changes. Actual machine
configuration is applied by the Terraform provider. Only sanitized action
summaries enter CI logs/PR comments; raw generated YAML, plans, diagnostics and
state are kept in a private temporary directory and are not uploaded.

The stable provider's configuration resource has no import or live-state Read
implementation. Adoption therefore creates a Terraform resource that sends the
exact existing configuration with apply_mode=no_reboot. The wrapper verifies
its original fingerprint and refuses a detected live configuration diff during
adoption. The bootstrap resource supports import; its Update changes only state.
The committed import block records the existing bootstrap, and the plan guard
rejects any bootstrap create, all deletion/replacement, unknown resources,
control-plane reboot mode and node reset. prevent_destroy is additional defense.

After adoption the provider tracks desired-config changes, not out-of-band drift.
The authenticated dry-run is a preflight, not automatic drift reconciliation.
OS/Kubernetes upgrades remain explicit later work; the new machine/cluster
resources are prerelease and are not enabled here. No unattended reboot recovery
is claimed. The initial Talos soft-reboot stall remains a follow-up before worker
installation or unattended upgrades.

## Secrets and state

The existing private talos-secrets.yaml is encrypted as the GitHub `prod`
environment secret TALOS_SECRETS_YAML. Run scripts/talos-ci-secrets.py from a
trusted administration checkout to populate/recover it without printing it.
The source is ~/.config/aws-account-infra/talos/homelab/talos-secrets.yaml,
mode 0600. Its fingerprint in identity.json prevents accidentally adopting a
new cluster identity. Do not generate replacement secrets for this cluster.

Both CI plan and apply jobs can access the existing CA/key bundle and generate
admin client credentials. They are not read-only security identities; trusted
repository workflow authors and prod-secret access are the boundary. The
existing prod environment has no required reviewer. Tailscale enrollment and
AWS state access reuse the existing OIDC identities; no Tailscale admin change
or new AWS role is required by this implementation.

Client configuration and machine YAML enter OpenTofu as sensitive ephemeral
variables and the provider's write-only attributes. Only public metadata and
rendered hashes should be persisted. The apply wrapper checks persisted state
for accidental secret/configuration retention. Keep provider/CLI versions
pinned, and revalidate secret exclusion on upgrades.

State uses the existing versioned encrypted bucket tofu-state-992382747916-us-east-1,
key talos/homelab/terraform.tfstate, and tofu-locks table. Other roots' keys are
unchanged. No saved plan or state is committed or uploaded as a CI artifact.

For a local preview only:

```bash
AWS_PROFILE=admin uv run scripts/talos-ci.py plan \
  --secrets-file "$HOME/.config/aws-account-infra/talos/homelab/talos-secrets.yaml"
```

The wrapper refuses local applies. Normal updates use GitHub CI. Plan summaries
show resource actions and bootstrap import, without configuration content.
Review the public patch diff as well as the plan summary.

## Recovery and rollback

Recover the existing secret bundle from the independently encrypted AWS archive
and initialize the same state key. Reissue the GitHub secret with the helper;
Tailscale/OIDC and AWS administrator recovery remain independent of Kubernetes.
If state is lost but the cluster survives, recover an S3 state version first.
Never remove the bootstrap import and blindly create bootstrap again.

For complete host/cluster loss, rebuild the Proxmox VMs first and use the
separately reviewed Talos/etcd restore procedure. This adoption root deliberately
requires an existing running control plane, so it is not by itself a fully
rehearsed disaster-recovery bootstrap. Do not clear its guards as routine retry.
The documented initial bootstrap and etcd recovery remain separate operations.

Reverting public configuration through a PR reconciles supported no-reboot
changes. Removing Terraform resources must not reset nodes; on_destroy.reset
is false and deletion is rejected by the wrapper. To abandon this migration,
stop triggering its deploy unit and retain state/credentials rather than
resetting the live cluster. Changing the stored state or removing resource
ownership requires a deliberate review.

Sources: pinned provider [configuration implementation](https://github.com/siderolabs/terraform-provider-talos/blob/v0.11.0/pkg/talos/talos_machine_configuration_apply_resource.go),
[bootstrap import/update implementation](https://github.com/siderolabs/terraform-provider-talos/blob/v0.11.0/pkg/talos/talos_machine_bootstrap_resource.go).
