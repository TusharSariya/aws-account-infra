# Homelab application deployment

OpenSpec: `deploy-pihole-tailnet-dns`. This root owns Pi-hole and the shared
Tailscale operator. State is independent of Talos at
`s3://tofu-state-992382747916-us-east-1/kubernetes/homelab/terraform.tfstate`.

Pi-hole runs on `talos-worker-01` with a retained 2Gi claim, 100m/128Mi requests,
1 CPU/512Mi limits and replacement updates. The volume survives pod replacement;
it is not independently backed up. Git owns the upstreams, blocklist and FTL
settings. Changes to environment-managed settings belong in values/PRs, not the
web UI. Query history is retained seven days. No DHCP or LAN DNS changes.

## First deployment

1. Run `bash scripts/homelab-pihole-setup.sh` from a checkout containing this PR.
   It walks through tag ownership and a dedicated Tailscale OAuth credential,
   then stores `TS_OPERATOR_CLIENT_ID`, `TS_OPERATOR_CLIENT_SECRET`, and
   `PIHOLE_ADMIN_PASSWORD` in this repository's protected `prod` environment.
   A private recovery copy is retained under `~/.config/aws-account-infra/pihole/`.
   Never paste that file, credentials or passwords into chat or Git.
2. Review the PR's application plan, then add the `apply` label. The existing
   gate requires successful CI apply. No local apply is necessary.
3. CI reconciles the tailscale namespace and credential Secrets using server-side
   apply, then applies the exact guarded OpenTofu plan. The foundation already
   owns `homelab-services`. Only secret references enter Helm/OpenTofu; credentials
   are not ordinary Terraform variables or Helm release values. Secret rotation
   requires a reviewed pod restart to load the new environment/mount inputs.
4. The endpoint check prints the assigned DNS IP and validates TCP/UDP resolution,
   stock-list blocking, private trusted HTTPS and unauthenticated API rejection.
   The planned administration URL is
   `https://pihole-admin.tail2f646b.ts.net/admin/`. It is usable only after apply.
   Sign in with the password saved during setup. Preserve the proxy Secrets;
   recreating their identities can change DNS addresses.

Chart artifacts and images are pinned; updates require a reviewed PR and endpoint
checks. CI reuses the original Talos identity only to obtain an ephemeral
kubeconfig. It never bootstraps or modifies Talos from this root.

## Tailscale credential and policy details

Merge into the existing `tagOwners` object, retaining other entries and grants:

```json
{
  "tag:k8s-operator": ["autogroup:admin"],
  "tag:k8s": ["tag:k8s-operator"]
}
```

Create the dedicated OAuth client with write access for General/Services,
Devices/Core and Keys/Auth Keys, scoped to `tag:k8s-operator`. Do not reuse the
OIDC GitHub-runner credential. The current operator-approved broad tailnet grants
allow client DNS and administration traffic. A future restrictive policy must
explicitly allow TCP/UDP 53 and HTTPS 443 to the relevant proxies. Do not remove
existing grants during setup. HTTPS must be enabled for the tailnet; Funnel is
neither enabled nor needed.

## DNS cutover, after endpoint checks

- Save the existing global nameservers, override setting, restricted nameservers
  and MagicDNS setting from the Tailscale DNS console independently.
- Confirm Proxmox and the gateway use independent upstream DNS. On infrastructure
  Tailscale clients, opt out with `tailscale set --accept-dns=false`. CI opts out
  explicitly. Kubernetes CoreDNS and Pi-hole upstreams must not point back through
  this Pi-hole endpoint.
- Add the **reported Tailscale DNS IP** as the sole global nameserver, enable
  Override DNS servers, and retain MagicDNS. Do not copy an invented address.
  Do not add a public fallback beside Pi-hole: resolvers need not be queried in
  order, so it could bypass filtering even when Pi-hole is healthy.
- Keep each device's OS network DNS automatic and enable Use Tailscale DNS
  settings. Clients accepting the global configuration will participate, not
  just the laptop and desktop. No exit node is required. If using an exit node,
  verify its DNS behavior separately before relying on the filtering.
- Test using actual OS resolution. On macOS use
  `dscacheutil -q host -a name example.com`; direct `dig @IP` only checks the
  server and does not prove that the OS/browser uses it. Disable a browser's
  separate Secure DNS provider if it bypasses the OS resolver.

## Turn filtering off on one device

Leave Tailscale connected. Turn off **Use Tailscale DNS settings**, or run:

```bash
tailscale set --accept-dns=false
# Enable again:
tailscale set --accept-dns=true
```

Use an elevated terminal if required by the client. This opts out of all Tailscale
DNS, so MagicDNS/custom private-name lookup may stop working. Tailscale IP
connectivity remains. With OS DNS left automatic, internet DNS uses the local
network. Cached answers can persist briefly; retry after cache expiry/flush.
Pi-hole's web UI can pause blocking for everyone while retaining DNS service;
that is not recovery when the server is down. Proxy SNAT may merge client
identities, so do not depend on Pi-hole client groups for independent bypass.

## Acceptance and rollback

Record results in the OpenSpec tasks/evidence before marking rollout complete:

1. Verify allowed and blocked queries over TCP and UDP, and HTTPS login/rejected
   unauthenticated API calls. Verify the endpoint is private, not Funnel.
2. In an explicitly scheduled maintenance window, record PVC/PV identity and a
   test file checksum under `/etc/pihole`, replace only the Pi-hole pod, verify
   the same claim and file, then remove the test file. Do not restart nodes.
3. Test the laptop and desktop, and one device over a phone hotspot. Bypass on
   one client while the other remains filtered, then re-enable. Disconnect
   Tailscale on one client and verify restoration of its normal local DNS.
4. For an explicitly scheduled outage rehearsal, prepare both clients' bypass
   controls first, scale only the Pi-hole Deployment to zero, verify bypass and
   Tailscale IP access, then restore one replica even if a check fails. Record
   recovery. Never automate this interruption in routine CI.
5. For a failed cutover, restore the saved Tailscale DNS settings first. Do not
   remove the resolver while clients still depend on it.

Normal CI rejects deletes/replacements. A planned removal requires a reviewed
change to that guard for Pi-hole only, after DNS rollback. Keep the retained PVC
and shared operator. Operator `prevent_destroy` must stay enabled. No `tofu
 destroy` against the root or deletion of the tailscale namespace is part of
Pi-hole removal. A second independent resolver is future work; more replicas on
this host do not provide host-outage protection.

Sources: [operator installation](https://tailscale.com/docs/kubernetes-operator/install-operator),
[private ingress](https://tailscale.com/docs/kubernetes-operator/ingress),
[client preferences](https://tailscale.com/docs/features/client/manage-preferences),
[DNS behavior](https://tailscale.com/docs/reference/dns-in-tailscale),
[Pi-hole container configuration](https://docs.pi-hole.net/docker/configuration/).
