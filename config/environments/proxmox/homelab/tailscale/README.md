# Optional tailnet management hardening

Operator deferred adoption: retain the existing default allow-all policy for now.
This candidate is not a deployment prerequisite and must not be automatically applied.

`policy.json` is a proposed full replacement for the operator-supplied default
allow-all policy, not an applied policy. It permits the administrator account's
user-owned devices to reach Proxmox SSH/HTTPS, the Talos API
and Kubernetes API. Other connections need explicit future grants. It does not
configure Kubernetes node-to-node networking or expose future application ports.

Both Tailscale IPv4 and IPv6 identities of pve are included so MagicDNS clients
can use either. These host addresses must be rechecked after re-enrollment.
Tagged administrator devices do not inherit their owner's user grant; review
tags explicitly if adopting them. This is account-scoped, not Mac-only access.

The supplied Tailscale SSH check rule is retained, but it does not grant network
reachability by itself or enable Tailscale SSH on pve. Ordinary OpenSSH and
Proxmox login remain required. Removing the funnel node attribute removes the
policy permission to publish via Funnel; private Serve does not require it.
No HTTPS DNS setting or Serve mapping is changed by this file.

Before replacing the policy, save the current policy outside the checkout as a
rollback copy. Replace the complete JSON editor contents with policy.json so the
old allow-all grant cannot remain additive. Use Tailscale's policy validation and
embedded tests before saving; local JSON parsing does not validate Tailscale
semantics. Keep the existing local SSH/console path available. After saving,
verify browser login at https://pve.tail2f646b.ts.net, ordinary SSH and
scripts/homelab-tailscale-route-validate.sh. Tests of undeployed Talos destinations
validate policy intent, not actual endpoints. Test unauthorized user/device access
when an appropriate independent test identity is available; no such denial test
has yet been run. Do not invent a successful denial result from one-owner tests.

Restore the saved prior policy through the Tailscale admin console if necessary;
that restoration reinstates its broad access and Funnel capability. The tailnet
administration account must remain recoverable independently of Kubernetes.

Sources: https://tailscale.com/docs/reference/syntax/grants and
https://tailscale.com/kb/1337/policy-syntax.

The intended primary host routes are `10.0.0.224/32`, `10.0.0.221/32`,
`10.0.0.222/32`, and `10.0.0.231/32`. Do not advertise the entire home LAN
as part of CI recovery. On 2026-09-19, the stale `.92` and `.220` advertisements
were replaced with `.224` and `.221` through a verified local SSH connection.
The replacement routes were approved in Tailscale and both retired approvals
removed. Hosted GitHub run `35447273846` then passed authenticated Talos
preflight and planning. Updating repository scripts alone does not update live
advertisements or approvals. The setup helper refuses unrelated routes and
compares route sets because Tailscale sorts advertisements.

`CI_EXECUTOR=talos` routes most CI jobs to the homelab runner pools. Proxmox and
Talos plan jobs explicitly retain `ubuntu-latest`; infrastructure apply also uses
hosted runners for these roots. Their Tailscale path must work independently of
the cluster they manage. Hosted-runner billing availability is a separate
prerequisite, not fixed by changing node IPs or the default executor variable.
