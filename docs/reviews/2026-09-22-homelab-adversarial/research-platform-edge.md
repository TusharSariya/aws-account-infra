> Raw agent report from the 2026-09-22 homelab adversarial review. It was produced against a local working tree behind `main`; several findings were fixed on `main` (`000bb81`) before filing. See [README.md](README.md) for the re-verified status and issue links.

I've written the report below, checked against 2026 primary sources where I could. Nothing in the repo was changed. Items I couldn't confirm are marked **[unverified]**.

# Talos homelab platform research (as of 2026-09-22)

## Grounding: where I agree and disagree with the existing plans

I agree with most of the three plan docs: Cloudflare Tunnel, Gateway API, Cilium with Hubble, Kyverno plus native CEL policy, Tetragon rather than Falco, ESO with IAM Roles Anywhere, CloudNativePG with the Barman plugin, a dead-man switch, and deferring Backstage and Crossplane.

Where I disagree or would update:
- **The hardware assumption is stale.** `kubernetes-tooling-landscape-2026.md` reasons from "all VMs consume one fixed Proxmox host." You now have a laptop plus two Proxmox hosts whose workers sleep. That changes the storage and control-plane answers. The "no Karpenter" conclusion still holds, but for a different reason: sleep/wake is a power-schedule problem, not a scale-on-demand problem.
- **The Cluster API assumption is weaker than the plan implies.** Sidero Labs has stopped developing the Talos Cluster API control-plane provider and points users to Omni instead ([repo](https://github.com/siderolabs/cluster-api-control-plane-provider-talos)). CAPI plus Talos is now a community-supported path.
- **Cilium mutual auth (SPIFFE/SPIRE) is gone.** The removal PR [cilium#48647](https://github.com/cilium/cilium/pull/48647) merged on 2026-09-22, and SPIRE moves to the beta ztunnel component. Which release first ships without it is [unverified]; the stable 1.20.2 docs still call it beta. The plan to defer SPIFFE is right. If you want workload mTLS, use Istio, which you already run.
- **The Falco fallback lost gVisor support.** Falco 0.44 (May 2026) removed its gVisor engine ([releases](https://github.com/falcosecurity/falco/releases)). That matters for your sandbox worker and makes Tetragon a firmer choice, though Tetragon also can't see syscalls inside gVisor.
- **MutatingAdmissionPolicy is stable since Kubernetes 1.36** ([docs](https://kubernetes.io/docs/reference/access-authn-authz/mutating-admission-policy/)). Simple defaulting and mutation can move from Kyverno to native CEL.

Current versions: Talos v1.14.1 (2026-09-15, Kubernetes 1.37.0, native BGP, etcd 3.7) ([releases](https://github.com/siderolabs/talos/releases)), Cilium 1.20.2, Kyverno 1.19.1, ESO v2.11.0, CloudNativePG 1.30.0.

---

## 1. Public ingress for a home IP

**Recommendation:** Run Cloudflare Tunnel as 2 `cloudflared` replicas that point at your single in-cluster Gateway (Istio or Cilium), with a wildcard hostname. Keep all routing in Gateway API `HTTPRoute`s rather than in the Cloudflare dashboard.
- Put Cloudflare Access in front of admin hostnames.
- Leave the free WAF managed ruleset on (it's on by default for Free plans).
- Issue certificates with cert-manager DNS-01 using a scoped Cloudflare API token. Every hostname then works the same over the tunnel and over LAN/Tailscale.

**Why:** Nothing listens on your home IP, you get unmetered DDoS protection on all plans, and you can use your own domain ([Cloudflare K8s guide](https://developers.cloudflare.com/tunnel/deployment-guides/kubernetes/), [WAF managed rules](https://developers.cloudflare.com/waf/managed-rules/), [DDoS](https://developers.cloudflare.com/ddos-protection/)). Cloudflare's own caveats:
- Replicas give high availability, not load balancing.
- Don't autoscale `cloudflared`; scaling down breaks connections.
- Use `/ready` on port 2000 as the liveness probe.

**Alternatives:**
- **Tailscale Funnel** only serves `*.ts.net` names (no custom domains), only ports 443/8443/10000, and has undisclosed bandwidth caps ([docs](https://tailscale.com/docs/features/tailscale-funnel)). Fine for demos, not for production.
- **VPS + WireGuard edge** (for example Pangolin, [fosrl](https://github.com/fosrl)) is the choice if you need non-HTTP protocols, or don't want Cloudflare terminating TLS and seeing plaintext. That second point is real for security-sensitive apps. The cost is that you now patch and defend a public host.
- **Gateway API controllers for Cloudflare** ([cfgate](https://github.com/cfgate/cfgate), [lexfrei](https://github.com/lexfrei/cloudflare-tunnel-gateway-controller)) are single-maintainer v1alpha1 projects. Skip them.

**Talos caveats:** none. Talos 1.14's native BGP could eventually replace MetalLB, but whether it announces LoadBalancer IPs is [unverified]; keep MetalLB L2.

**Effort:** about 1 day.

## 2. Control plane HA on a budget

**The core conflict:** etcd needs a majority of voters awake at all times. Control-plane VMs on hosts that sleep will lose quorum. A 2-member etcd cluster is worse than 1, because the majority of 2 is 2 ([etcd FAQ](https://etcd.io/docs/v3.7/faq/)). A laptop control plane also brings lid-close, sleep and Wi-Fi risk.

**Recommendation:**
- **Now:** stay on 1 control-plane node, harden it (wired Ethernet, sleep disabled), and invest in recovery. Automate encrypted Talos etcd snapshots to S3 and rehearse a restore quarterly.
- **Later:** go to 3 control planes only when you have 3 always-on boxes, for example laptop + one always-on Proxmox host + a cheap N100 or arm64 mini-PC. Sidero recommends 3; 5 costs about 5% of write throughput ([Talos control plane](https://docs.siderolabs.com/talos/v1.13/learn-more/control-plane)).
- **Endpoint:** use the Talos Layer2 VIP for the external API endpoint. It needs all control-plane nodes on the same L2 and is elected through etcd, so it won't help `talosctl` ([VIP](https://docs.siderolabs.com/talos/v1.14/networking/advanced/vip)).
- **KubePrism:** keep it on for in-cluster access, and point Cilium's `k8sServiceHost` at `localhost:7445` ([KubePrism](https://docs.siderolabs.com/kubernetes-guides/advanced-guides/kubeprism)). On Talos 1.14, `.machine.features.kubePrism` is deprecated in favour of a `KubePrismConfig` document, so migrate your patches.
- **KubeSpan:** only needed if the laptop leaves the LAN. It depends on the public discovery service and doesn't suit control planes spread across sites ([KubeSpan](https://docs.siderolabs.com/talos/v1.12/networking/kubespan)).

**Omni:**
- **Pricing:** the SaaS Hobby plan is $10/month for up to 10 nodes and 2 users ([pricing](https://www.siderolabs.com/pricing)).
- **Licence:** self-hosting is BSL, free for "home labs and other personal, non-commercial use". Separately, the licence treats running anything your "own development, operations, or business depends" on as production ([BSL guidance](https://docs.siderolabs.com/omni/self-hosted/production-vs-non-production)). Whether public-facing personal apps count is ambiguous; ask Sidero.
- **Verdict: don't adopt.** Omni would hold root-equivalent access to Talos and Kubernetes for a security-sensitive cluster. It also adds a SaaS dependency that contradicts your WAN-partition design, and a SideroLink security advisory exists ([GHSA](https://github.com/siderolabs/omni/security/advisories/GHSA-hqrf-67pm-wgfq)). It doesn't fix quorum either.

## 3. Node lifecycle and autoscaling on Proxmox

**Recommendation:** OpenTofu provisions the VMs; talhelper or `talosctl` patches define per-class machine config; a small **power controller** handles sleep/wake. The controller can be a CronJob, or an n8n/Home Assistant flow on an always-on box:
1. Cordon and drain the worker.
2. `talosctl shutdown` the worker VM.
3. Suspend or shut down the Proxmox host.
4. To wake: `pvenode wakeonlan <node>` from another cluster member, or a raw WoL magic packet, then VM autostart, then uncordon ([Proxmox node management](https://pve.proxmox.com/wiki/Proxmox_Node_Management)).

Put `node.kubernetes.io/*` taints plus a `power-class=ephemeral` label on sleepable workers, and keep stateful and critical pods off them.

**Proxmox caveats:**
- Two clustered Proxmox hosts need a QDevice for Proxmox's own quorum, and more so if one sleeps. This is from Proxmox docs I didn't re-fetch [unverified this session].
- Talos-specific settings: disable memory ballooning, use CPU type `host`, use the VirtIO SCSI controller (not "VirtIO SCSI Single"), and include the qemu-guest-agent extension ([Talos on Proxmox](https://docs.siderolabs.com/talos/v1.14/platform-specific-installations/virtualized-platforms/proxmox)).

**Options I considered and rejected:**
- **CAPMOX:** actively maintained (v0.9.0, June 2026), but still on the v1alpha2 contract, needs image-builder templates, and depends on the Talos CAPI providers that Sidero has stopped developing ([bex.co summary](https://bex.co/blog/2026/07/29/cluster-api-provider-proxmox-capmox)).
- **karpenter-provider-proxmox:** a single-maintainer project that creates and destroys VMs from templates, doesn't mention Talos, and can't wake sleeping hosts ([repo](https://github.com/sergelogvinov/karpenter-provider-proxmox)).
- **Cluster Autoscaler:** needs a CAPI or cloud node group. The Omni path works but leaves deleted machines to clean up by hand ([Omni CA](https://docs.siderolabs.com/omni/cluster-management/scale-your-cluster/cluster-autoscaler)).
- **Omni machine classes** with the MPL-2.0 [Proxmox provider](https://github.com/siderolabs/omni-infra-provider-proxmox) are the most polished route for heterogeneous workers, but they come with the Omni concerns from section 2.

**Effort:** the power controller is 2–3 days; CAPI or Karpenter would be 1–2 weeks plus ongoing upkeep.

## 4. Storage

**Recommendation for 2 sleepable hosts:** don't run synchronously replicated block storage across nodes that sleep; every wake triggers a rebuild.
- **Shared data:** the external NAS over NFS CSI, as already planned.
- **Per-host block storage:** [Proxmox CSI plugin](https://github.com/sergelogvinov/proxmox-csi-plugin). Volumes live on the hypervisor's own storage (ZFS/LVM), are zone-labelled, and support LUKS. Local volumes can't migrate between hosts automatically.
- **Databases:** replicate at the application layer (a CloudNativePG replica per host) and use CloudNativePG + Barman Cloud plugin to S3. In-tree Barman removal was pushed to 1.31, so migrate to the plugin now ([CNPG releases](https://github.com/cloudnative-pg/cloudnative-pg/releases)).

**If you later want replicated block storage** (2 always-on storage nodes plus a tiebreaker):
- **Piraeus/LINSTOR** is the best fit: a diskless third node, such as the control plane, can act as the DRBD quorum tiebreaker ([LINBIT](https://linbit.com/drbd-user-guide/drbd-guide-9_0-en/)). On Talos it needs the DRBD system extension matched to the kernel, `usermode_helper=disabled`, and no systemd bits ([Piraeus Talos](https://piraeus.io/docs/v2.9.0/how-to/talos/)). The risk is extension/kernel coupling on every Talos upgrade.
- **Longhorn 1.12** (V2 engine now GA) is the easiest. It needs the `iscsi-tools` and `util-linux-tools` extensions, a privileged namespace, and hugepages for V2 ([Longhorn on Talos](https://longhorn.io/docs/1.12.1/advanced-resources/os-distro-specific/talos-linux-support/)).
- **Skip:** Rook-Ceph (needs 3+ real failure domains) and Mayastor (hugepages and resource-heavy for this size). democratic-csi only makes sense if the NAS is TrueNAS/ZFS [unverified what your NAS is].

**Backups:** Velero is now a CNCF Sandbox project (March 2026) with a Kopia data mover ([InfoQ](https://www.infoq.com/news/2026/05/broadcom-velero-cncf/)). Use it for Kubernetes objects and PVCs after the etcd and CloudNativePG restores are proven. The plan's ordering is correct. VolSync is a lighter per-PVC alternative; its 2026 release state is [unverified].

## 5. Security and supply chain

**Agree with the plan, plus these additions:**
- **Kyverno 1.19:** legacy policy types are in their deprecation phase, so migrate to `ImageValidatingPolicy` now. First run a spike on keyless (GitHub OIDC) verification, because an open bug crashes key- and certificate-based bundle verification ([#16435](https://github.com/kyverno/kyverno/issues/16435)). Sigstore policy-controller is a fallback only; don't run both.
- **Native CEL policies:** use ValidatingAdmissionPolicy and MutatingAdmissionPolicy (both stable) for simple rules. Kubernetes 1.36's manifest-based admission policies ("can't be deleted") are a good fit for the Pod Security floor ([blog](https://kubernetes.io/blog/2026/05/04/kubernetes-v1-36-manifest-based-admission-control/)).
- **Secrets:** ESO (v2.x) for runtime secrets. Keep SOPS + age via talhelper for bootstrap secrets (Talos machine secrets, the Roles Anywhere certificate), because ESO can't bootstrap itself.
- **Talos hardening:**
  - Talos Ingress Firewall (`NetworkRuleConfig`) to restrict apid and kubelet to management CIDRs ([docs](https://www.talos.dev/v1.11/talos-guides/network/ingress-firewall/)).
  - SecureBoot + TPM-bound STATE/EPHEMERAL disk encryption where the VMs support vTPM.
  - KSPP-hardened, signed-modules-only kernel (a Talos default).
  - Enable Talos 1.14 DNS-over-TLS.
- **Runtime:** Tetragon 1.7 in observe mode ([Isovalent](https://isovalent.com/blog/post/tetragon-v1.7-release)).

## 6. Observability that still works when the cluster is down

**Recommendation:** route kube-prometheus-stack's always-firing `Watchdog` alert to an external dead-man check with `repeat_interval: 5m` and `send_resolved: false` ([pattern](https://blog.ediri.io/how-to-set-up-a-dead-mans-switch-in-prometheus)). Two ways to receive it:
- **healthchecks.io:** zero effort.
- **AWS-native, since you already run staging:** a Lambda function URL receives the webhook and writes a CloudWatch metric. An alarm with `TreatMissingData=breaching` sends email through SNS. This costs cents per month and lives in this repo's IaC. The design is my own and not yet tested.

Add an external HTTP probe of the public hostnames, from Cloudflare health checks or Uptime Kuma on a VPS [unverified free-tier details], and have the Proxmox hosts send a separate heartbeat so "cluster down" and "power off on purpose" can be told apart. The power controller from section 3 should pause the dead-man check while a planned sleep is in progress.

**Effort:** half a day.

## 7. Developer experience

- **Renovate:** the Argo CD manager must be enabled explicitly through `managerFilePatterns` ([docs](https://docs.renovatebot.com/modules/manager/argocd/)). Group Talos, the talhelper version and the Talos image-factory schematic in one PR with no automerge. A community report says talhelper `genconfig` broke on Talos 1.14.1 ([issue](https://github.com/aoshimash/homelab-k8s/issues/316)), so gate the PR on a `genconfig` plus `talosctl validate` CI job.
- **Talos config:** talhelper (v3.1.x, native SOPS) is better than hand-maintained `talosctl gen` patches for heterogeneous node classes ([docs](https://budimanjojo.github.io/talhelper/latest/)).
- **Inner loop:** Tilt is Docker-owned but still maintained ([FAQ](https://docs.tilt.dev/faq.html)). Use it against a disposable namespace or kind; don't point it at the production cluster.
- **Preview environments:** use the Argo CD ApplicationSet PR generator ([docs](https://argo-cd.readthedocs.io/en/latest/operator-manual/applicationset/Generators-Pull-Request/)) with label opt-in, private-only exposure (never through the tunnel), a namespace-per-PR ResourceQuota, and no builds from fork PRs.
- **Portal:** use Headlamp over OIDC plus a `catalog.yaml`. Keep deferring Backstage, as the plan says.

---

## Suggested order

1. etcd snapshot and restore drill.
2. Dead-man switch.
3. Cloudflare Tunnel to the Gateway, with Access.
4. Talos firewall and KubePrism config migration.
5. Power controller for sleep/wake.
6. Proxmox CSI + CloudNativePG.
7. Kyverno `ImageValidatingPolicy` migration.
8. Tetragon.
9. Third always-on control-plane node, when you have the hardware.

## Could not verify

- Talos 1.14 BGP announcing LoadBalancer IPs.
- The exact Cilium release that drops mutual auth.
- VolSync's 2026 releases.
- Specifics of Cloudflare health-check and Grafana Cloud free tiers.
- The OpenTofu `bpg/proxmox` provider's current version.
- Proxmox QDevice guidance (from memory, not re-fetched).
- Whether Omni's BSL treats your use as production.

**Sources:** the URLs are inline above. The plan docs I compared against are in `docs/plans/`: `kubernetes-tooling-landscape-2026.md`, `kubernetes-additional-tools-2026.md` and `kubernetes-security-hardening-2026.md`.