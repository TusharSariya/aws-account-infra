## Why
Use the existing server for private ad-blocking DNS without changing the ISP router. Devices must be able to bypass filtering independently without losing Tailscale connectivity.

## What Changes
- Add a separate Kubernetes application OpenTofu root and reviewed CI deployment.
- Deploy persistent Pi-hole and a shared Tailscale operator with private DNS and HTTPS endpoints.
- Configure Tailscale DNS only after acceptance; document client opt-out and global rollback.

## Capabilities
### New Capabilities
- `tailnet-dns`: Private filtered DNS with per-device participation and bypass.

## Impact
Depends on the existing Talos cluster, Cilium and local-path storage. Adds application state at kubernetes/homelab/terraform.tfstate. No router, Talos identity or host DNS migration. Shared operator survives Pi-hole removal. Full DR and independent resolver redundancy remain deferred.
