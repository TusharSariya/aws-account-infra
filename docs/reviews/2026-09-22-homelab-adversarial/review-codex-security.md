> Raw agent report from the 2026-09-22 homelab adversarial review. It was produced against a local working tree behind `main`; several findings were fixed on `main` (`000bb81`) before filing. See [README.md](README.md) for the re-verified status and issue links.

**Verdict: a useful private lab, but not yet a defensible platform for public, mixed-trust workloads.** This review covers checked-in code and recorded acceptance evidence, not a fresh live audit. No infrastructure was changed or secret values read.

**1. Verdict per goal**

1. **PARTIAL — Private apps and safe public traffic:** private access exists; the public exposure contract remains planned.
2. **PARTIAL — Scheduled, on-demand and persistent AI:** worker capacity exists, but GPU operation and enforced AI isolation are not established by the reviewed evidence.
3. **NOT MET — Security-, performance- and latency-sensitive work:** shared workers lack demonstrated tenant isolation and resource guarantees.
4. **PARTIAL — Modular, scalable, maintainable:** useful placement and recovery tooling exists; topology drift and manual host power operations limit reproducibility.
5. **NOT MET — Arbitrary workloads in production-like fashion:** admission, secret authorization, supply-chain enforcement and security monitoring are incomplete.

**2. Findings, ranked by severity**

**High — Public ingress is a proposal; the existing gateway is unsafe to promote unchanged.**  
Evidence: [gateway-resources.yml.j2:17](ansible/roles/cluster_addons/templates/gateway-resources.yml.j2:17) defines HTTP/80 and `allowedRoutes.namespaces.from: All`, then attaches Grafana. [The roadmap:86](docs/plans/production-kubernetes-homelab-roadmap.md:86) still calls for HTTPS, Cloudflare Tunnel, authentication and rate limiting.

Failure: pointing a public tunnel at this shared listener without strict hostname rules risks exposing private routes. An identity permitted to create HTTPRoutes in another namespace can also attach routes; this is the documented [Gateway attachment model](https://gateway-api.sigs.k8s.io/docs/concepts/security/). Neither current public exposure nor working WAF/DDoS protection is demonstrated.

Fix: separate public and administrative listeners, restrict route namespaces and hostname ownership, implement explicit tunnel routes with terminal denial, verified origin TLS, authentication, edge rate limits/WAF, and origin-bypass tests before publishing anything.

**High — Management and workload networks share a broad trust boundary.**  
Evidence: [network inventory:11](docs/homelab-network-inventory.md:11) places BMCs, Proxmox, workers and the laptop on the same LAN. [VM networking:62](live/proxmox/homelab/main.tf:62) uses `vmbr0` without VLAN separation. [Laptop forwarding:113](platform/main-control-plane/network.py:113) allows LAN-to-control-plane forwarding by destination address, without management source/port restrictions. [Tailscale README:3](config/environments/proxmox/homelab/tailscale/README.md:3) explicitly retains allow-all; the restrictive policy is unapplied.

Failure: a compromised tailnet device gains network reachability across advertised destinations. A compromised workload without effective egress policy can probe management services. Authentication remains a barrier, but network isolation does not contain the attack.

Fix: isolate BMC/Proxmox management, restrict tailnet grants, enforce host firewalls and workload egress allowlists, and prove denied access from an ordinary application pod and unauthorized device. Historical firewall acceptance is insufficient evidence of current enforcement.

**High — Shared-worker placement is not a mixed-trust security boundary.**  
Evidence: [compute-template.yaml:3](kubernetes/platform/main/placement/compute-template.yaml:3) allows both workers and prefers primary; [placement logic:109](kubernetes/platform/main/placement/plan.py:109) similarly places runners. [Implementation log:960](openspec/changes/build-talos-proxmox-homelab/implementation-log.md:960) explicitly says the gVisor smoke-test RuntimeClass was removed and does not establish permanent admission enforcement.

Failure: public apps, private data services and build/AI jobs can share a worker kernel. A container escape threatens colocated workloads and mounted data; an unrestricted job can also exhaust shared resources. Installed gVisor extensions alone do not force sandbox use.

Fix: enforce runtime, placement, restricted Pod Security, token and resource policies for every workload class. Separate untrusted jobs/public workloads from sensitive services using dedicated worker VMs or stronger isolation. Test bypass attempts. Kubernetes’ [multi-tenancy guidance](https://kubernetes.io/docs/concepts/security/multi-tenancy/) likewise treats network policy, sandboxing and node isolation as distinct controls.

**High — The everyday laptop account controls both cluster identity and hypervisor recovery.**  
Evidence: [service:10](platform/main-control-plane/systemd/main-control-plane.service:10) runs QEMU as `tushar`; [host preparation:15](platform/main-control-plane/prepare-host.sh:15) gives that account ownership of VM storage. [Runbook:29](docs/runbooks/main-control-plane.md:29) identifies its Proxmox SSH key as a host-root credential; [line 84](docs/runbooks/main-control-plane.md:84) stages cluster credentials and the secrets bundle locally.

Failure: desktop-account compromise can access cluster credentials and VM control sockets, alter the control-plane disk, and use the management key from its authorized source. Theft creates a comparable risk if storage protection is inadequate. Filesystem modes do not defend against the owning account; disk encryption is unverified.

Fix: use a dedicated VM service identity, separate privileged administration from desktop use, constrain Proxmox credentials, verify encrypted storage and recovery-key custody, and document revocation after laptop compromise.

**High — Secret-to-workload authorization is planned, not demonstrated.**  
Evidence: [security plan:140](docs/plans/kubernetes-security-hardening-2026.md:140) proposes namespace/ServiceAccount Secret allowlists and encryption verification. The reviewed main platform does not establish those controls for application namespaces.

Failure: a compromised deployment identity with pod-creation rights can mount another application’s Secret in the same namespace without direct Secret-read permission. Restricted Pod Security alone does not prevent this.

Fix: split namespaces by trust domain; constrain workload creation, interactive access and Secret references; prove credential rotation and unauthorized-mount rejection. Verify effective Talos Secret encryption and encrypted restores without exporting values. This is an acceptance gap, not a claim that Talos stores Secrets unencrypted.

**High — Monitoring acceptance does not provide security audit coverage.**  
Evidence: [Alloy:4](kubernetes/platform/main/monitoring/config/alloy.alloy:4) discovers only opted-in monitoring pods; [line 33](kubernetes/platform/main/monitoring/config/alloy.alloy:33) drops everything except fixed diagnostic markers. [Alertmanager:9](kubernetes/platform/main/monitoring/config/alertmanager.yml:9) has no external notification receiver.

Failure: Secret enumeration, malicious exec, RBAC changes or host compromise may leave no centrally retained security evidence or external alert. Worker shutdown also stops the main monitoring stack.

Fix: collect sanitized API audit, host authentication and network-denial events; retain evidence outside the compromised worker’s control; test external security alerts and a dead-man signal.

**Medium — Digest pinning lacks an enforced artifact-trust chain.**  
Evidence: [pilot-http.yml:15](.github/workflows/pilot-http.yml:15) uses mutable Action tags; publication produces a digest selection but no explicit signing/verification gate. [Talos README:5](config/environments/proxmox/homelab/talos/README.md:5) explicitly defers signature verification.

Failure: a compromised build dependency can publish malicious bytes that are subsequently pinned faithfully. OIDC authentication alone would not establish artifact provenance.

Fix: pin Actions by commit, restrict publication identities, sign release digests/provenance, and enforce approved registry/workflow identities at admission.

**Medium — Conflicting topology documents can restore the wrong security posture.**  
Evidence: [CONTEXT.md:7](CONTEXT.md:7) describes three Proxmox Talos VMs plus a GPU worker; [the accepted runbook:3](docs/runbooks/main-control-plane.md:3) makes the laptop authoritative. [Sleep/wake:3](docs/runbooks/manual-server-sleep.md:3) explicitly has no automatic wake/shutdown trigger.

Failure: operators infer nonexistent GPU capacity, automatic scaling or independent trust domains, or apply obsolete bootstrap assumptions.

Fix: reconcile the canonical topology, distinguish manual power management from autoscaling, and make security/recovery acceptance specific to each node class.

**3. Blockers versus nice-to-haves**

Before claiming production-like public or mixed-trust operation: close ingress, segmentation, sandbox/admission, Secret authorization, laptop credential and audit gaps; prove them with negative tests and independent recovery.

Later improvements: richer dashboards, additional security products, service-mesh expansion and convenience autoscaling. These do not substitute for enforced boundaries.

**4. What is good**

Talos configuration generation protects private output and preserves PKI; installer/CLI integrity is pinned. Monitoring has restricted Pod Security and narrow access. Argo projects are closed by default. Migration fencing explicitly prevents stale control-plane startup. The repository often distinguishes smoke-test success from actual recovery acceptance, which is valuable discipline.