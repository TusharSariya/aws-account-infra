# Homelab PKI: Let's Encrypt server TLS + IAM Roles Anywhere node identity

Date: 2026-07-16
Status: design approved (Track 1 sections 1–2); **Track 2 not yet reviewed**

## Problem

The homelab has **five unrelated trust domains** and no deliberate design tying
them together:

| Trust domain | Issuer today | Managed by |
|---|---|---|
| ECR pull node identity | `CN=homelab-ecr-pull-ca` (hand-rolled openssl) | `kubernetes_node` role |
| Browser → Grafana | none — **plaintext HTTP** | — |
| Pi-hole web UI | Pi-hole's own self-signed (`CN=pi.hole, O=Pi-hole, C=DE`) | Pi-hole itself |
| Istio mesh | istiod self-signed root (`O=cluster.local`, 10y, minted 2026-07-06) | istiod |
| Kubernetes control plane | kubeadm PKI (`/etc/kubernetes/pki`) | kubeadm |

Two concrete problems follow:

1. **No server TLS.** The `homelab` Gateway serves HTTP on :80 only. Every
   internal service is plaintext on the LAN.
2. **The ECR CA is a single point of failure.** `homelab-ca.key` lives in the
   repo checkout (`~/Projects/aws-account-infra/homelab-ca.key`), gitignored.
   `docs/plans/ansible-vault.md` documents it at
   `~/.config/aws-account-infra/homelab-ca.{crt,key}` — "outside the checkout"
   so `git clean -x` can't destroy it — but it was never moved there. Because
   `git clean -x` deletes *ignored* files, the CA does not survive the exact
   scenario that doc claims to defend against. `BACKUPS.md` records that a
   desktop has already been wiped once.

## Goals

- Publicly-trusted TLS on internal services, with **no inbound exposure** and no
  root certificate installed on any device.
- Node identity for IAM Roles Anywhere that survives losing any single machine.
- Both reproducible from the repo + a password manager, with no manual openssl.
- A path that scales to node #2 without hand-signing.

## Non-goals (explicit)

- **Not touching kubeadm's PKI.** It self-manages and renews on upgrade
  (`kubeadm certs renew`). Replacing it with an external CA is a well-known way
  to brick a control plane for no benefit.
- **Not touching Istio's CA.** The self-signed `cluster.local` root is invisible
  to browsers and works. Swapping in a custom `cacerts` root means restarting
  every workload and buys nothing until mesh federation exists.
- **Not adopting step-ca or Vault PKI.** See "Key decisions".
- **Not fixing Pi-hole's self-signed UI cert.** Separate, self-contained, low
  value; revisit if the UI moves behind the Gateway.
- **Not exposing anything to the internet.** DNS-01 is chosen precisely so this
  stays true.

## Key decisions

### 1. Two trust domains, one spec. They cannot merge.

Let's Encrypt **cannot** serve node identity: IAM Roles Anywhere requires a trust
anchor whose **private key you hold**, and LE only ever issues end-entity leaf
certs — it will never hand out a signing CA, and its intermediate is shared by
every LE customer. Conversely the private CA **should not** serve browsers, or
every device needs its root installed.

So: **LE for what browsers see; the private CA for what AWS sees.** This is not a
compromise between them — it is what each system independently requires. The
private half never goes public, at any future date.

### 2. `home.arpa` is abandoned. Names move to `homelab.tfdraw.dev`.

`home.arpa` is RFC 8375 — reserved for home networks and deliberately not
publicly resolvable. **No public CA can ever issue for it**, so keeping those
names means permanently forgoing Let's Encrypt.

`tfdraw.dev` is already owned and already on Cloudflare (zone
`8aad82763aa1144a148989b4600c44f3`, Free plan). The apex is in use (CNAME →
`ainur-chb.pages.dev`, Cloudflare Email Routing MX, Zoho verification TXT), so
the homelab takes the `homelab.tfdraw.dev` subdomain. Cost: $0 — the domain is
already paid for.

**Naming is the migration cost, not the issuer.** Issuers swap cheaply
(step-ca and Let's Encrypt both speak ACME behind the same cert-manager `Issuer`
shape); hostnames do not — they touch SANs, Pi-hole records, Gateway hosts,
inventory vars, and bookmarks. Get the names right once.

### 3. Wildcard, not per-service certs.

Issue `*.homelab.tfdraw.dev` **plus** `homelab.tfdraw.dev` (a wildcard does not
cover its own parent). Two reasons:

- **Certificate Transparency.** Every LE issuance is logged publicly and
  permanently. Per-service certs would publish `grafana.`, `pihole.`, and every
  future service name to the world. A wildcard leaks only
  `*.homelab.tfdraw.dev` — the existence of a homelab, not its inventory.
- One `Certificate` resource, one renewal path, no churn when a service is added.

### 4. Keep the openssl CA for node identity. Defer step-ca.

step-ca was the initial recommendation and was **dropped** once LE turned out to
be free here. With server TLS handled by LE, the private CA's only remaining job
is a single yearly client cert for one node — which the existing Ansible
on-node-CSR flow (commit `6201937`) already automates correctly: the node
generates its key, Ansible ships only the CSR, the controller signs, the private
key never leaves the node.

step-ca earns its keep at *N* nodes or with short-lived certs. At one node it is
a second service to run, back up, and unseal for no gain. **Revisit when node #2
lands** — the trigger is real, not hypothetical (`hosts.yml` already lists
`ubuntu_laptop_dell_studio`).

Vault PKI is rejected for the same reason, more so: HA, unsealing, and backup
discipline are a second job for a solo operator.

### 5. The CA key backs up to the Ansible vault, not to AWS.

The obvious home for a backup is S3/Secrets Manager — `BACKUPS.md` already has
the pattern. **This would be circular**: the CA exists to obtain AWS credentials
via Roles Anywhere. Storing it in AWS means a disaster recovery that needs AWS
credentials to recover the thing that gets you AWS credentials.

The Ansible vault breaks the loop: ciphertext is committed to git (surviving
laptop loss, per `ansible-vault.md` decision #1) and the password lives in a
password manager — outside both this machine and AWS. That is the only backup
target here with no dependency on the thing it recovers.

## Architecture

```
┌─ PUBLIC TRUST — browsers ──────────────────────────────────────────┐
│  Let's Encrypt ──DNS-01──▶ Cloudflare (tfdraw.dev)                  │
│         │                       ▲ TXT _acme-challenge (temporary)   │
│         ▼                                                            │
│  cert-manager ──▶ Certificate: *.homelab.tfdraw.dev                  │
│         │              + homelab.tfdraw.dev                          │
│         ▼                                                            │
│  Secret (istio-ingress) ──▶ Gateway `homelab` :443 Terminate         │
│                                    ▲                                 │
│  Pi-hole: *.homelab.tfdraw.dev ──▶ 10.0.0.234 (MetalLB, LAN only)    │
└─────────────────────────────────────────────────────────────────────┘
   No inbound. No public A records. No root installed anywhere.

┌─ PRIVATE TRUST — AWS (never public, by requirement) ────────────────┐
│  homelab-ecr-pull-ca  (key: ~/.config/aws-account-infra/)            │
│         │ signs CSR — node's private key never leaves the node       │
│         ▼                                                            │
│  node client cert ──▶ IAM Roles Anywhere ──▶ STS ──▶ ECR pull        │
└─────────────────────────────────────────────────────────────────────┘
```

## Track 1 — Let's Encrypt server TLS

Current state (verified live 2026-07-16): the `homelab` Gateway
(`gateway.networking.k8s.io/v1`, `gatewayClassName: istio`) in `istio-ingress`
has **one listener — HTTP :80** — pinned to MetalLB `10.0.0.234`. This track is
purely additive until the cutover step.

1. **cert-manager** → `cluster_addons` helmfile, pinned `v1.21.0`. Full install
   record: `docs/plans/cert-manager.md`.
2. **Cloudflare token** → scoped `Zone:DNS:Edit` + `Zone:Zone:Read` on
   `tfdraw.dev` only → `vault_cloudflare_api_token` → templated `Secret` in the
   `cert-manager` namespace.
3. **Two `ClusterIssuer`s: `letsencrypt-staging` first, then
   `letsencrypt-prod`.** Not ceremony — LE's failed-validation limit is 5/hour
   and duplicate-certificate is 5/week. Debugging DNS-01 against prod is how you
   get rate-limited out for a week. Staging proves the loop; prod issues the real
   cert.
4. **`Certificate` in `istio-ingress`** for `*.homelab.tfdraw.dev` +
   `homelab.tfdraw.dev`. It must live in the Gateway's namespace: Gateway API
   `certificateRefs` cannot cross namespaces without a `ReferenceGrant`. An
   explicit `Certificate` is used rather than cert-manager's gateway-shim
   annotation — the shim needs an extra controller feature flag, and explicit
   matches how this repo does everything else.
5. **HTTPS listener** on the Gateway: :443, `mode: Terminate`, `certificateRefs`
   → that Secret, hostname `*.homelab.tfdraw.dev`. Keep :80 with an
   HTTP→HTTPS redirect route.
6. **Rename** `kubernetes_grafana_hostname` / `kubernetes_pihole_hostname` to
   `*.homelab.tfdraw.dev`, and add the Pi-hole wildcard record →
   `10.0.0.234`. **This happens last** — renaming before a cert exists just
   breaks Grafana.

## Track 2 — node identity: custody, backup, renewal

> **Not yet reviewed.** Sections 1–2 (Track 1) were walked through and approved;
> this track was written straight into the spec at the operator's request.

Current state (verified 2026-07-16):

- CA: `CN=homelab-ecr-pull-ca`, self-signed, `CA:TRUE, pathlen:0`, valid
  2026-07-12 → 2036-07-09.
- Leaf: `CN=desktop`, 2026-07-12 → **2027-07-12** (365d, per
  `kubernetes_node_ecr_client_cert_days`).
- Flow: on-node CSR → controller signs → cert installed at
  `/etc/kubernetes/rolesanywhere/cert.pem`; `aws_signing_helper` exchanges it for
  STS creds. Trust anchor registered in
  `modules/aws/account_identity/ecr_pull_iam.tf` via `homelab_ca_certificate_pem`.

Changes:

1. **Move the CA out of the checkout.** `homelab-ca.{crt,key,srl}` →
   `~/.config/aws-account-infra/`, the location `ansible-vault.md` already
   specifies and `kubernetes_node_ecr_signing_dir` already defaults beside
   (`~/.config/aws-account-infra/node-certs`). The directory now exists (created
   2026-07-16 for the vault password). Also delete the stray `desktop.{crt,csr,key}`
   and `homelab-ca.crt.bak` from the repo root — they are build residue.
2. **Back the CA key up into the Ansible vault** as `vault_homelab_ca_key` (see
   decision #5 for why not S3). Ciphertext committed; password in the password
   manager.
3. **Renewal.** The leaf expires 2027-07-12 with nothing watching it. Cheapest
   credible option: a `blackbox_exporter`-style cert-expiry check into the
   existing kube-prometheus-stack, alerting at 30 days. Re-running the
   `kubernetes_node` role reissues; the flow is already idempotent.
4. **Node #2.** The Ansible flow is already per-host, so adding
   `ubuntu_laptop_dell_studio` to `kubernetes_nodes` should Just Work. Unproven —
   validate before relying on it.
5. **Fix `docs/plans/keda.md`.** It still describes shipping "cert + private key
   (from Vault)" to the node, which commit `6201937` deliberately replaced with
   the on-node CSR flow. The doc contradicts the code.

## Files

| Path | Change |
|---|---|
| `ansible/roles/cluster_addons/defaults/main.yml` | + `cluster_addons_cert_manager_version: v1.21.0` |
| `ansible/roles/cluster_addons/templates/helmfile.yaml.j2` | + `jetstack` repo, + `cert-manager` release |
| `ansible/roles/cluster_addons/tasks/main.yml` | + webhook wait; + render/apply issuer resources |
| `ansible/roles/cluster_addons/templates/cert-resources.yml.j2` | **new** — ClusterIssuers + Certificate |
| `ansible/roles/cluster_addons/templates/gateway-resources.yml.j2` | + HTTPS listener, + redirect route, hostname rename |
| `ansible/inventories/local/group_vars/all/vault.yml` | + `vault_cloudflare_api_token`, + `vault_homelab_ca_key` |
| `ansible/inventories/local/group_vars/all/main.yml` | hostnames → `*.homelab.tfdraw.dev` |
| `ansible/roles/kubernetes_node/*` | CA path → `~/.config/aws-account-infra/` |
| `docs/plans/cert-manager.md` | **new** — install record (gate) |
| `docs/plans/keda.md` | fix stale on-node-CSR description |

## Pinned versions (verified 2026-07-16)

| Component | Version | Source |
|---|---|---|
| cert-manager chart | `v1.21.0` | `https://charts.jetstack.io/index.yaml` (latest stable; `v1.20.3` prior) |

## Cutover sequence

Deliberate, verify-before-flip — mirroring the Istio ingress cutover:

1. `make -C ansible addons` → installs cert-manager **and KEDA** (pinned, never
   applied — see `docs/plans/cert-manager.md`). Verify 3 cert-manager pods + CRDs.
2. Apply `letsencrypt-staging` ClusterIssuer + a staging `Certificate`. Confirm
   the DNS-01 challenge completes and a Secret appears. **This is the step that
   proves the Cloudflare token, the DNS-01 path, and the Pi-hole self-check
   bypass all work.**
3. Swap to `letsencrypt-prod`. Confirm a real, browser-trusted cert lands.
4. Add the HTTPS listener to the Gateway. Grafana still reachable on
   `grafana.home.arpa` over :80 at this point — nothing has broken yet.
5. Add the Pi-hole wildcard record → `10.0.0.234`.
6. Rename hostnames, attach the HTTPRoute to the new name, verify HTTPS
   end-to-end, **then** add the HTTP→HTTPS redirect.

Rollback at any step: `docs/plans/cert-manager.md`.

## Verification

```bash
kubectl get pods -n cert-manager
kubectl get clusterissuer                       # Ready=True
kubectl -n istio-ingress get certificate        # Ready=True
kubectl -n istio-ingress describe certificate homelab-wildcard   # events on failure
dig +short _acme-challenge.homelab.tfdraw.dev TXT @1.1.1.1       # during challenge
curl -vI https://grafana.homelab.tfdraw.dev     # no -k; must validate natively
```

## Risks / follow-ups

- **Pi-hole breaks the DNS-01 self-check** unless
  `dns01RecursiveNameserversOnly` is set. Mitigated at install; documented in
  `docs/plans/cert-manager.md`. Most likely thing to eat an afternoon.
- **Certificate Transparency** publishes `*.homelab.tfdraw.dev` permanently.
  Accepted — wildcard keeps service names out of the logs.
- **Cloudflare token is a real credential.** Scoped to one zone, DNS-edit only,
  in the vault. Compromise = DNS control of `tfdraw.dev`, which also hosts a
  Pages site and email routing. Worth a periodic rotation.
- **`desktop.crt` carries no X.509 extensions** — no EKU `clientAuth`, no
  keyUsage. Roles Anywhere may tolerate this, but it is not verified working
  end-to-end. **Confirm the trust anchor actually authenticates before relying on
  ECR pull**, and add the EKU if not.
- **Trust anchor may never have been applied.** `ecr_pull_iam.tf` exists; whether
  `aws_rolesanywhere_trust_anchor` is live in staging was not verified.
- **`--check` is broken for `cluster_addons`** (see install record). Follow-up:
  `check_mode: false` on the four prep tasks.
- **`deploy/tofu/cert-manager.tf` in the `excalidraw-tf-rag` repo is a trap.** It
  declares cert-manager for a **k3s cluster that no longer exists** (that repo's
  `deploy/` describes k3s `v1.35.5+k3s1` + Kafka/SeaweedFS/CNPG; the live box is
  kubeadm v1.36.2 with cilium/istio/metallb/pihole and none of those workloads).
  cert-manager is owned **here**, by `cluster_addons`. Do not apply that file.
- **Controller bootstrap was incomplete** and cost time on 2026-07-16: the vault
  password file was never created (`ansible.cfg` points at
  `~/.config/aws-account-infra/vault-password`), and an empty
  `group_vars/all/` directory silently shadowed `group_vars/all.yml`, hiding all
  22 inventory variables. Both fixed. The `example` inventory was migrated by
  commit `6201937` but `local` is gitignored, so nothing enforced it —
  `make -C ansible check` is the cheap guard and should be run first, from the
  repo root.
