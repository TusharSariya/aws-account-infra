# Remote access over the tailnet

> [!IMPORTANT]
> Historical record only. This document describes the retired Ubuntu/kubeadm and Ansible path. Its commands are archival examples and must not be run. Removed sources remain available in the [pre-removal repository tree](https://github.com/TusharSariyaOrg/aws-account-infra/tree/9a5f9720e45e3bbcbb5637e7bd27a8c688d53add/ansible). Current server management uses Talos, OpenTofu, and Helm.

How `grafana.home.arpa` and `pihole.home.arpa` are reached from outside the
house, and which parts of that path Ansible owns.

## The problem

The homelab publishes its services on MetalLB LoadBalancer addresses in
`10.0.0.0/24`, and resolves their names through Pi-hole at `10.0.0.232`. Both
are LAN-only facts. Off-site, two independent things fail:

1. **Routing** — the tailnet gives the node one address, `100.125.44.96`. No
   route into `10.0.0.0/24` exists, so `10.0.0.234` is unreachable.
2. **DNS** — `home.arpa` is a reserved non-global name. No public resolver will
   ever answer it, and Pi-hole (the only resolver that can) is itself behind
   problem 1.

Fixing one without the other changes nothing. SSH is unaffected either way,
because it terminates on the tailnet address itself (see the `ssh_tailnet` role).

## Reaching the node over SSH

```bash
ssh tushar@tushar-ubuntu-26-desktop   # MagicDNS; 100.125.44.96 works too
```

The name comes from MagicDNS, so it resolves only while Tailscale is running on
the client — with the client stopped it fails as `Unknown host`, which reads like
a wrong hostname rather than a tunnel that is down. `tailscale status` is the
faster check.

The LAN address is not a fallback. `ssh_tailnet` binds sshd to the tailnet
interface alone and disables `ssh.socket`, so port 22 on `10.0.0.156` is closed
by design; that address remains the Kubernetes API endpoint and is unaffected.
Any client-side shortcut — an `~/.ssh/config` alias, a shell function — must
therefore carry the tailnet name, not the LAN one. An alias predating the
`ssh_tailnet` migration will still point at `10.0.0.156` and quietly fail.

## Managing the cluster over the tailnet

```bash
kubectl get nodes                              # default context, over the tailnet
kubectl config use-context homelab-lan         # fallback, same subnet only
```

The API server binds `*:6443`, so the tailnet always reached it; what failed was TLS.
A certificate lists the names it may be presented for, and the cluster's was issued
when the only client was on the LAN:

```text
x509: certificate is valid for 10.96.0.1, 10.0.0.156, not 100.125.44.96
```

`kubernetes_api_external_endpoint` fixes that by adding the MagicDNS name to
`certSANs`. The name rather than the tailnet IP, so a Tailscale reassignment does not
invalidate the certificate. Because `kubeadm init` runs only once,
`kubernetes_control_plane` reconciles the live certificate on every run — it compares
the parsed SANs, and only when one is missing does it back up the old pair, reissue,
restart the API server container, and wait for `/livez`. It then asserts against the
reissued file, since a template change proves nothing about what the server presents.

The same SANs are uploaded into the `kube-system/kubeadm-config` ConfigMap, because
`kubeadm upgrade apply` regenerates certificates from there and not from the rendered
file. Skipping that step buys a SAN that works until the next upgrade and then vanishes.

`controlPlaneEndpoint` deliberately stays `10.0.0.156`. It is embedded in every node's
`kubelet.conf` and in the cluster's own configuration, so moving it is a migration
rather than a setting — and external clients need only a matching SAN, not a matching
endpoint.

Two contexts, for the same reason the SSH aliases keep both paths. The default context
follows the MagicDNS name and is correct in both locations, since Tailscale connects
directly over the LAN when both machines are home. `homelab-lan` exists for the case
the tailnet itself is down, and works because `kubernetes_api_endpoint` is also a SAN.

`admin.conf` is fetched verbatim, so its server is always `controlPlaneEndpoint`; the
role rewrites it after the fetch. Editing `~/.kube/config` by hand instead means the
next playbook run silently restores LAN-only access.

Not enabled: `kubernetes_control_plane_user_kubeconfig` would place a copy of
`admin.conf` in the node user's home so `ssh desktop kubectl …` works without `sudo`.
It is off because it widens cluster-admin from root-only to any process running as
that user.

## What Ansible manages

The `tailscale_subnet_router` role, applied by `playbooks/compute.yml` to hosts
with `tailscale_subnet_router_enabled: true`:

- Advertises the service VIPs as `/32` subnet routes, derived from
  `kubernetes_pihole_dns_address` and `kubernetes_gateway_address` so a VIP
  change moves the route with it.
- Enables `net.ipv4.ip_forward` independently of the Kubernetes sysctls, since
  the two are unrelated features that happen to need the same setting.
- Verifies the routes came back **approved**, by reading `Self.AllowedIPs` from
  `tailscale status --json` rather than trusting the node's own preferences.

`/32`s rather than `10.0.0.0/24`: an accepted subnet route outranks the client's
own LAN route, so advertising the whole subnet would pull every home address
through this node even for clients sitting beside it on the LAN.

The role uses `tailscale set`, never `tailscale up`. `up` requires every
non-default flag to be restated on each invocation and silently resets the ones
omitted — not something a repeatedly-run playbook can do safely.

## What Ansible cannot manage

Two settings are tailnet-wide control-plane state, not node state. They are
reached through the admin console or the Tailscale API, and applying them from
here would mean holding a Tailscale API key in vault for what is a one-time
click. They are deliberately manual:

1. **Route approval** — Machines → the node → Route settings, at
   <https://login.tailscale.com/admin/machines>. The role fails with this
   instruction rather than exiting green on a route that carries no traffic.
   To make it declarative instead, add an `autoApprovers` stanza to the tailnet
   policy file:

   ```jsonc
   "autoApprovers": {
     "routes": { "10.0.0.0/24": ["tushar.sariya77@gmail.com"] },
   },
   ```

2. **Split DNS** — DNS → Nameservers → *Add nameserver* → *Custom*, set
   `10.0.0.232`, and **restrict it to `home.arpa`**. Without the restriction
   Pi-hole becomes the global resolver for every tailnet client, which routes
   all DNS over a home WiFi link even when the client is on cellular.

Client-side, each device needs *accept routes* (`tailscale set
--accept-routes=true`, or "Use Tailscale subnets" in the macOS menu bar).

## Verifying

From a tailnet client that is **not** on the home LAN — a phone hotspot is the
honest test, since on-LAN success proves nothing about the tailnet path:

```bash
tailscale status | grep -i route          # subnet routes offered by the node
dig +short @10.0.0.232 grafana.home.arpa  # expect 10.0.0.234
curl -sS -o /dev/null -w '%{http_code}\n' \
  --resolve grafana.home.arpa:80:10.0.0.234 \
  http://grafana.home.arpa/login          # expect 200 or 302
```

## Known limitations

- **Plaintext.** The Gateway has a single `HTTP:80` listener — no TLS. WireGuard
  encrypts the transit, so this is not an exposure problem, but browsers will
  mark it insecure. `docs/plans/cert-manager.md` covers the wildcard that
  resolves it.
- **Prometheus is not routed.** Only Grafana and the Pi-hole admin UI have
  HTTPRoutes. Prometheus remains `kubectl port-forward` only.
- **Single point of failure.** The subnet router, the Kubernetes control plane,
  and the only ingress are the same WiFi-attached machine. `enp4s0` is
  `NO-CARRIER`; a cable is the highest-value reliability fix available here.
