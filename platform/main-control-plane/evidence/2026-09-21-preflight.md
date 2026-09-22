# Migration evidence - 2026-09-21/22

Status: **accepted; application services and original submissions restored**.

- Temporary .226/.227 routed Wi-Fi/proxy-ARP proof passed in both directions.
  Scoped forwarding exceptions coexist with the retired pilot firewall.
- Source CODE/visible-VARS firmware pair booted on QEMU 10.2.1. Guest-agent
  device, 2 vCPU, 4096 MiB, disk controller, UUID and MAC preserved.
- Fresh main and pilot etcd snapshots, machine configurations and checksums are
  private, with main recovery material also copied off laptop before shutdown.
- Pilot VM and lifecycle services stopped; pilot disks retained and checksummed.
  Primary pilot worker VM 9107 stopped and protected, with autostart disabled.
- Main source VM 100 gracefully stopped, protected, onboot disabled. Sparse
  conversion compared equal to the source LV. Resumable transfer and full SHA256
  verification completed before destination launch at 2026-09-22 02:06:58 UTC.
- Laptop API .231 and etcd .221 healthy. Original node/namespace UIDs and every
  baseline PVC/PV UID, class, binding and affinity passed identity comparison.
  Workers 01/02 Ready; worker 02 retains its preexisting cordon.
- CoreDNS and Cilium operator now on laptop. Talos upstream resolvers are
  1.1.1.1 and 8.8.8.8. Twelve cross-node Pod-IP/Service-DNS HTTP requests passed
  across all three nodes, plus external DNS from each. Owned test namespace removed.
- Platform placement applied with private originals and UID/spec concurrency
  guards. Application access ProxyClass configured; dormant AI resources unchanged.
- Primary IaC map excludes retired VM 100. A later audit of current main found
  S3 state ownership absent from the stale migration checkout. That authoritative
  state was backed up and exactly VM 100 removed; worker state was unchanged.
  No provider apply was performed. See the IaC reconciliation runbook.

Completed after cutover:

- Initial 600-second four-Job capacity test passed: minimum available memory
  2454 MiB Ubuntu / 773 MiB guest, without sustained swapping. A second test
  with monitoring also passed, followed by a third with Argo CD installed.
  All four bounded Jobs completed in each run. Graphical boot remains enabled.
- Kubelet serving TLS bootstrap enabled without node reboot. Exactly three
  CSRs were inspected for signer, username, node DNS/IP SANs and server usage
  before approval. API and all kubelet endpoints validate against the original
  Kubernetes CA. No insecure TLS bypass or blanket approver installed.
- Monitoring deployed with five retained primary-local claims (10/10/2/1/1 GiB).
  Dashboard queries, replacement-Pod sanitized log streams, negative log test,
  alert firing/resolution and all eight scrape targets passed.
- Secondary and primary physical shutdown/wake cycles passed. Primary applications
  were stopped in order; CNPG hibernated before Talos shutdown. Original data disk
  UUID/mount, protected bindings, historical monitoring metrics/logs and maintenance
  silence survived wake. CoreDNS replacement succeeded with application webhooks
  stopped. Source VM 100 stayed stopped after primary PVE boot.
- Argo core deployed on worker 01; authenticated TLS administrative access passed.
  Projects are closed, with no Applications or repository/cluster credentials.
  Redis bootstrap credential is private; Redis has no API token or Role.
- Main VM autostart enabled. Final both-host wake restored the original data
  disk/mount and all protected bindings before application writes resumed.
  Monitoring historical metrics, both log streams, all eight scrape targets,
  PVC/PV identities and maintenance silences survived. Argo core and authenticated
  TLS access passed after recovery, still with no application adoption.
- All desired platform replicas are healthy, CNPG is ready, and dormant AI
  deployment specs remain unchanged. Original schedules and runner ranges were
  restored from the first maintenance journal. Maintenance silences expired after
  recovery; infrastructure alerts cleared. A resumed cache-monitor query timed
  out once; a fresh follow-up completed with no warnings or configuration change.
  Both workers are Ready, with worker 02
  retaining its original cordon. The temporary recovery probe was removed.

Both physical application hosts were confirmed off through their IMM endpoints.
Laptop API readiness, etcd and internal/external cluster DNS passed in this state,
after Wi-Fi disconnect/reconnect, and again after a full laptop reboot. The boot
ID changed, the sole main QEMU VM started automatically, and the retired pilot
root services stayed disabled. Graphical boot and suspend masks were preserved.
Original identities and protected bindings passed again; post-reboot memory and
swap reserves passed. Private desired-state journals were copied off laptop.
Both application hosts are on after successful recovery. Source VM 100 remains
stopped, protected and onboot=0. Post-reboot available memory was at least
2649 MiB on Ubuntu and 1706 MiB in the guest; the final capacity check also passed.
A fresh final etcd snapshot and checksummed evidence are retained privately on
the laptop and recovery Mac.

Acceptance is complete. Never boot the stale source copy; rollback requires
transferring the latest consistent destination state. Monitoring and GitOps pause
while worker 01 sleeps, and this remains a single-control-plane cluster.

Private evidence: ~/.local/share/main-control-plane on laptop and recovery Mac.
No credentials or images are stored in Git.
