# Talos configuration through OpenTofu CI

This root adopts the existing control plane separately from the Proxmox VM
root. It pins siderolabs/talos 0.11.0 and OpenTofu 1.11.5 in CI, retaining Talos
v1.13.9/Kubernetes v1.36.3 and the existing cluster secrets and public patches.
It does not create VMs, generate new cluster secrets or bootstrap the live
cluster again. Worker configuration is enabled in cluster.tfvars to install and
join the existing shared-worker VM using the same cluster identity.

## Review and deployment

Public desired configuration remains in config/environments/proxmox/homelab/talos.
Changes there select this deploy unit. PRs run an authenticated preflight and
plan through an ephemeral Tailscale CI runner with subnet-route acceptance.
After reviewing the plan, add the existing `apply` label. CI applies before
merge and the apply gate blocks merge on failure. Talos is ordered after the
Proxmox root when both are selected. Talos changes do not require a local apply.

The shared `.github/actions/talos-deploy` action exposes setup, private identity
preparation, live preflight, init, validate, plan, plan guard, apply, state
inspection, storage readiness and networking/PVC acceptance as named steps.
`scripts/talos-ci.py` is a stage adapter, not the workflow orchestrator. It uses
the hash-verified pinned talosctl only to generate and
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
is claimed. Monitor the initial worker installation and verify authenticated
Talos access and Kubernetes node registration after its reboot. The earlier
control-plane soft-reboot stall remains unresolved; a successful provider apply
alone is not installation acceptance. If it recurs, inspect the Proxmox console
and establish that installation and disk sync completed before considering an
operator-directed VM reset. Do not reset the stateful control plane or blindly
retry bootstrap. Unattended upgrades remain deferred.

## Secrets and state

The existing private talos-secrets.yaml is encrypted as the GitHub `prod`
environment secret TALOS_SECRETS_B64. Run scripts/talos-ci-secrets.py from a
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
AWS_PROFILE=admin bash scripts/talos-plan-local.sh \
  "$HOME/.config/aws-account-infra/talos/homelab/talos-secrets.yaml"
```

The private command adapter refuses local applies and checks that apply uses
the exact saved plan approved by the structural guard. Normal updates use GitHub CI. Plan summaries
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

## Cilium foundation

The same root owns `helm_release.cilium` with Helm provider 3.3.0 and Cilium
chart 1.20.1. CI downloads the chart from https://helm.cilium.io, verifies its
committed SHA-256, and supplies the local archive to the provider. Chart image
digests remain pinned by upstream defaults. Public Helm values live in
config/environments/talos/homelab/cilium-values.yaml.

Use Kubernetes IPAM with the existing 10.244.0.0/16 pod range, VXLAN tunneling,
kubeProxyReplacement=false and kube-proxy retained. Talos provides bpffs and
cgroup v2 mounts; Cilium does not remount them or request SYS_MODULE. Agents
reach the API through each node's KubePrism on localhost:7445. The operator
uses one replica on this single-host cluster. Hubble is disabled for this
foundation step; its observability services and certificates can be added
separately. No sandbox isolation is claimed until task 5.5 installs policies.

The wrapper retrieves a temporary admin kubeconfig through the authenticated
Talos API. Its path is an ephemeral provider input; client credentials are
checked against state after apply and are never printed or uploaded. The API
at 10.42.0.224:6443 must be reachable through the existing Tailscale subnet
route. No additional GitHub secret or IAM role is needed.

After apply, CI runs scripts/homelab-cilium-validate.sh using checksum-pinned
kubectl 1.36.3. It checks both nodes, Cilium/Envoy/operator, CoreDNS, kube-proxy
and the live networking mode, then creates two restricted, temporary test pods
(one per node), Services, and tests same-node/cross-node pod IP traffic,
Service routing and internal/external DNS. A narrowly scoped toleration allows
the temporary control-plane test pod; application scheduling stays disabled.
The generated test namespace is deleted on exit. If the runner is killed,
inspect and delete only leftover homelab-network-check-* namespaces.

Repeat acceptance from the Mac with the private kubeconfig:

```bash
KUBECONFIG="$HOME/.config/aws-account-infra/talos/homelab/two-vm-20260912/kubeconfig" \
  bash scripts/homelab-cilium-validate.sh
```

A failed acceptance check fails apply CI and blocks automatic merge. Inspect
Cilium pod status/events before retrying. Helm atomic uninstall and automatic
cleanup are disabled so failure cannot silently remove the CNI; prevent_destroy
and the plan guard reject deletion/replacement. Correct values through a new
reviewed plan. If state was lost, recover the same backend or import the existing
release as kube-system/cilium before applying; do not install a second owner.
For a rebuilt cluster, restore the original identity and documented Talos state
before deploying this chart. Full DR and safe networking rollback rehearsals
remain outstanding; no automatic destructive rollback is implemented.

Sources: [Talos Cilium guide](https://docs.siderolabs.com/kubernetes-guides/cni/deploying-cilium),
[Cilium Kubernetes compatibility](https://docs.cilium.io/en/v1.20/network/kubernetes/requirements/),
[Helm provider release schema](https://github.com/hashicorp/terraform-provider-helm/blob/v3.3.0/docs/resources/release.md).

## Task 8.2 migration boundary

The native OpenTofu command and flags are visible in the shared action. The
`exec` adapter injects ephemeral inputs in a filtered child environment and
suppresses potentially secret-bearing provider diagnostics. No private values
are written to GITHUB_ENV/GITHUB_OUTPUT or uploaded as artifacts. The action
always removes its private workspace on completion/failure. A hard runner kill
still relies on destruction of the ephemeral GitHub runner.

`talos_tools.py` centralizes the existing Talos CLI and deployment chart/tool
pins, reusing the installer for local configuration generation and recovery.
Cilium's kube-proxy/VXLAN/IPAM contract is now a blocking OpenTofu postcondition;
structural deletion/bootstrap/target guards and multi-document disk checks
remain in the adapter. Native `yamldecode` is unsuitable for Talos multi-document
YAML, so that safety check is retained.

The apply job deploys selected AWS/Proxmox prerequisites before the Talos action
and fails closed if the unit graph puts anything after Talos. Existing apply
and auto-merge gates still cover all acceptance stages. Networking/PVC tests
and first-provision storage reboot retain their prior semantics; moving them
to independently selected jobs/explicit maintenance is task 8.3. Backup command
consolidation remains 8.4. No cluster identity, backend key or resource address
changes in this migration. Rollback to main revision 0bf06a7 restores the prior
wrapper/workflows without resetting state or recreating infrastructure.
