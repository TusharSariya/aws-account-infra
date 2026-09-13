## Context
One control plane and one worker on a single Proxmox host. All participating clients run Tailscale. Router DNS is locked and remains unchanged.

## Decisions
Separate live/kubernetes/homelab root, existing GitHub plan/apply gates, shared private Talos-derived kubeconfig. Pin Pi-hole chart 2.38.0/image 2026.07.2 and operator chart 1.102.3 by verified artifact digests. One worker replica, retained 2Gi PVC, requests 100m/128Mi, limits 1CPU/512Mi, replacement updates. Default blocklist, Cloudflare upstreams, seven-day query history, DHCP disabled. Infrastructure resolvers stay independent.
Operator uses dedicated OAuth credentials in a Kubernetes Secret supplied by protected CI; Pi-hole password likewise references an existing Secret. No application credentials in Helm values or OpenTofu state/logs. Shared operator has destruction protection and is retained on Pi-hole removal. Expose separate pihole-dns TCP/UDP 53 and pihole-admin private HTTPS identities; preserve proxy identity Secrets. No Funnel.
After tests, operator manually records previous tailnet DNS settings, adds the assigned DNS IP as sole global nameserver, enables override and retains MagicDNS. No public fallback. Clients keep OS DNS automatic and can use tailscale set --accept-dns=false/true. Opt-out affects private names as well as filtering. No policy forces DNS participation.

## Risks / Trade-offs
Single server/gateway dependency; no HA claim. Replacing Pi-hole briefly interrupts DNS. Proxy SNAT can hide individual clients from Pi-hole; bypass belongs on clients, not Pi-hole client groups. Persistent volume is not independently backed up. Credentials and tailnet changes require operator setup outside Git.

## Migration Plan
Reviewed PR and CI apply, verify endpoint queries and persistence, then operator DNS cutover. Restore previous tailnet DNS settings before uninstall or outage maintenance. Existing deferred homelab validation is not a prerequisite. Do not pause/stop Pi-hole during routine CI; outage/bypass acceptance is explicitly scheduled after a client is available.
