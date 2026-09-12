# Laptop-connected Proxmox address plan

Prepared 2026-09-12 for task 2.5. Saved and active DHCP configuration plus existing-host connectivity were verified in LOG-0037. Guest reservation files are installed; no guest lease or VM creation is proven. Full task acceptance remains pending.

## Observed topology

Home router `10.0.0.1/24` -> laptop Wi-Fi `10.0.0.181` -> NetworkManager shared Ethernet `server-link` on `enp2s0`, `10.42.0.1/24` -> Proxmox `vmbr0`, `10.42.0.115/24`.

Laptop Wi-Fi uses DHCP with a home-router reservation confirmed by the operator on 2026-09-12 (LOG-0046). Proxmox has a verified DHCP reservation on the laptop. Its gateway and DNS server are `10.42.0.1`. Mac SSH aliases are `laptop-dell-studio` and `server-10-42`, with the latter using the laptop as ProxyJump. The `proxmox` alias is stale and points to `10.0.0.92`.

NetworkManager 1.54.3 now serves dynamic addresses `.10-.199`. The saved and active shared gateway is `10.42.0.1/24`, preserving the existing `.115` reservation; this was reconfirmed after the two-VM revision.

## Prepared identities

| VM ID | Name | Address | MAC | Startup order |
|---|---|---|---|---:|
| 100 | talos-cp-01 | 10.42.0.220 | 02:42:00:00:01:00 | 1 |
| 102 | talos-worker-01 | 10.42.0.222 | 02:42:00:00:01:02 | 2 |

- Kubernetes API candidate: `https://10.42.0.224:6443`. Task 3.3 generated its Talos configuration; the VIP is not active until control-plane bootstrap.
- MetalLB candidate: `10.42.0.231-10.42.0.253`, on the shared Ethernet segment.
- All guests: `/24`, gateway and DNS `10.42.0.1`, attached to `vmbr0`.
- VM inventory was empty and the next available ID was 100. ARP discovery from Proxmox saw no responding host in `.200-.254`; this does not prove absence of sleeping devices or unexpired leases. The wizard checks active leases and existing reservation configuration before mutation.

## Apply and recovery

`scripts/homelab-network-wizard.sh` is a temporary operator-run wizard. It requires sudo on the laptop, preserves the existing Proxmox reservation, checks for overlapping leases/configuration, backs up DHCP snippets and prior changed properties under `/var/backups/homelab-network.*`, writes guest reservations, validates dnsmasq syntax, and activates only `server-link`. Wi-Fi is unchanged. Proxmox connectivity may pause during Ethernet reactivation.

On failure after mutation it attempts restoration using the generated `rollback.sh`; this script can also be run from the laptop console. Copy the resulting backup off-host and verify SSH, DNS, routing, DHCP settings and reservations before accepting the change. Do not mark task 2.5 complete solely because the wizard returns success.

Native range syntax is documented by [NetworkManager](https://www.networkmanager.dev/docs/api/latest/settings-ipv4.html). The setting is supported by the installed version. Explicit host reservations outside a dynamic range are supported by dnsmasq; see the [maintainer's explanation](https://lists.thekelleys.org.uk/pipermail/dnsmasq-discuss/2015q1/009193.html).

## Remaining reachability decisions

This shared network is NATed behind the laptop. An SSH jump reaches management endpoints, but does not establish the networking needed by the external GPU Kubernetes worker or general LAN clients. Verify the intended routed or overlay path and firewall policy before joining that worker or advertising service access. The old `10.0.0.231-253` MetalLB range does not apply to these guests. Task 2.5 remains open pending execution, verification and resolution of required access paths.

## Repeatable validation

Run `./scripts/homelab-network-validate.sh` from the administration checkout. It checks saved and active laptop settings, per-interface forwarding, reservation files, SSH through the laptop, Proxmox gateway/DNS and outbound HTTPS. It changes no network configuration and explicitly reports its untested recovery and routing checks. See LOG-0037 for the successful run.

## Two-VM revision, 2026-09-12

Only IDs 100 and 102 are active desired guests. Prior laptop reservations for retired IDs 101/.221 and 103/.223 may remain installed and unused; they are not proof those VMs exist and are not recycled. Repository helpers now require/create only the two active reservations. No live network change was made for this revision. The existing wizard still refuses an already configured reservation file; use the pending DR reconciliation procedure to change installed state.

## Privileged read-only audit

The administration-side validator passed again after the two-VM revision. The laptop requires interactive sudo for root-only checks. `scripts/homelab-network-root-audit.sh` checks dnsmasq syntax, the saved DHCP range and active leases against reserved/excluded addresses, then prints the nftables ruleset for review. It changes no network settings. A copy is staged at `/home/tushar/homelab-network-root-audit.sh`; run `sudo bash ~/homelab-network-root-audit.sh` on the laptop. The script is target-checked for the current Ubuntu gateway. This is an audit helper, not the still-pending fresh-machine recovery implementation. The operator ran the audit successfully at 2026-09-12T18:42:05Z (LOG-0045). DHCP syntax/range and active leases passed; only the expected Proxmox lease was present. The reviewed firewall supports outbound NAT and returning traffic, but rejects new forwarded connections from the home LAN into the server subnet. A client route alone is therefore insufficient for general LAN/GPU access. Task 2.5 remains open for outstanding wider-client/GPU reachability checks. Current gateway reboot persistence is verified below.

The operator confirmed the home-router DHCP reservation for laptop Wi-Fi at `10.0.0.181` on 2026-09-12. Its observed MAC is `1c:65:9d:07:f3:73`; the subsequent router screenshot showed Reserved IP selected, the matching MAC and 10.0.0.181 (LOG-0047). This is the Wi-Fi uplink, distinct from the Ethernet gateway at `10.42.0.1`. The current SSH jump depends on this Wi-Fi address remaining stable.

## Reboot persistence verified

After the operator rebooted the laptop, the administration-side validator passed (recorded 2026-09-12, LOG-0047): saved and active Ethernet/Wi-Fi addresses, shared DHCP range, Proxmox/control-plane/worker reservations, per-interface forwarding, SSH jump access, gateway reachability, DNS and outbound HTTPS all returned. This verifies the current gateway setup survives a reboot; it does not prove fresh-machine reconstruction or new guest leases. The validator footer describes the script's standalone coverage, not the cumulative status of this build.

## Tailscale management path

Operator reports Tailscale installed directly on pve (2026-09-12, LOG-0048). Enrollment, version, endpoint, startup persistence and access from outside home are not yet verified. The planned remote path is administrator Tailscale client -> pve for UI/SSH, and pve as an approved subnet router -> 10.42.0.0/24 for authorized Talos/service management. Installing the client does not automatically configure subnet access. Tasks 2.9-2.11 capture verification and recovery work.

The laptop still provides pve's internet uplink. Existing local addresses, reservations, SSH jump and console fallback remain valid. Review Tailscale/host firewall interaction and approved route return traffic before activation; do not blindly replace NetworkManager-managed firewall tables. Remote management does not complete the external GPU worker's Kubernetes networking requirements. No Tailscale installation on the laptop or Talos nodes is asserted.

## Tailscale host verification, 2026-09-12

Proxmox Tailscale package/client is 1.102.4, backend Running, tailscaled active and enabled. Host IPv4 is `100.101.182.9`, MagicDNS name `pve.tail2f646b.ts.net`. From the Mac on the home network, Tailscale ping and ordinary key-authenticated SSH passed. Tailscale SSH is disabled; no subnet routes are advertised. Service enablement is verified, but persistence through a Proxmox reboot is not yet tested. The node reports key expiry 2027-03-11T19:51:59Z; server expiry policy remains to be reviewed.

The web UI returned HTTP 200 through Tailscale with CA/name verification using the Proxmox public CA retrieved through trusted SSH and `curl --cacert <public-ca-file> --resolve pve:8006:100.101.182.9 https://pve:8006`. The current certificate has DNS SAN pve and pve.proxmox.local but no Tailscale IP or DNS SAN, so the browser-facing Tailscale URL still needs a trusted certificate arrangement. Certificate SHA-256 fingerprint: `85:8D:F9:29:E3:97:18:A2:EC:95:20:B8:41:36:36:61:F9:01:73:0E:8F:17:CC:D6:73:77:26:35:8F:ED:C5:B8`. No TLS verification was disabled for the successful check and no certificate was changed.

SSH verification command from the existing administration Mac: `ssh -o StrictHostKeyChecking=yes -o HostKeyAlias=10.42.0.115 -i ~/.ssh/id_ed25519 root@100.101.182.9 hostname`. This reuses the already trusted host key; it is not a fresh-machine trust bootstrap procedure. Access-policy restrictions, off-home UI login/SSH, Proxmox reboot persistence and recovery remain open in task 2.9 and related tasks. No host configuration changed.

## Private HTTPS verified by operator

LOG-0050 records successful operator-reported off-home UI access and removal of browser certificate warnings. The current preferred URL is `https://pve.tail2f646b.ts.net` (no port suffix). Both Serve/Funnel status outputs explicitly say **tailnet only** and proxy to `https+insecure://localhost:8006`. Funnel capability was enabled accidentally, but no active public exposure is shown. Rebuild the mapping with `tailscale serve --bg https+insecure://localhost:8006` after restoring enrollment and enabling HTTPS; verify `tailscale serve status` and browser login. This mapping skips TLS verification only for the loopback backend. Existing direct port-8006 certificates are unchanged.

Next network step is task 2.10, planned subnet routing through pve for 10.42.0.0/24. Tailnet access-policy review, remaining host-persistence/source checks and independent recovery are still open; remote UI success alone does not complete them.

## Subnet route advertised; approval pending

LOG-0052: Proxmox now persists IPv4 forwarding in `/etc/sysctl.d/99-homelab-tailscale.conf` and advertises only `10.42.0.0/24`. Default subnet SNAT is retained so downstream devices see the subnet router as the source; this is an administrator-access configuration, not proof of GPU-worker networking. Reproduce with `scripts/homelab-tailscale-subnet.sh` as root on pve. Existing Serve and SSH remain functional.

The Mac has not yet received the subnet in its peer map. Approve the pve subnet route in the Tailscale admin console, review the tailnet grants/ACLs for intended administrators, then verify client route acceptance and forwarding to a separate live subnet device. Do not treat access to pve's own subnet IP as proof that forwarding to a guest works. Guest checks must wait for guest creation. Rollback is recorded in LOG-0051.

## Approved subnet forwarding verified

LOG-0053 supersedes the route-approval-pending status: the operator approved the route, the Mac received 10.42.0.0/24 from pve, and its route to 10.42.0.1 uses the Tailscale utun interface. Authenticated SSH to the separate laptop Ethernet endpoint succeeded without a jump host; the laptop saw source 10.42.0.115, proving Proxmox forwarding/SNAT and return traffic. Recheck with `scripts/homelab-tailscale-route-validate.sh`. Access-policy review and unauthorized-client denial remain pending; guest and GPU endpoints need later runtime validation.

## Default policy accepted; restrictive grants optional

The operator explicitly retained the supplied default allow-all policy. Subnet route approval, client acceptance and authenticated forwarding/SNAT already passed in LOG-0053; task 2.10 is now complete under this accepted membership trust boundary. Account/port restrictions and removal of Funnel capability are optional future improvements, not deployment gates. Effective Serve remains tailnet-only. Guest/API and external GPU runtime checks remain in their later tasks, and off-home SSH/recovery work is still open.
