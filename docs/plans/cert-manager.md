# cert-manager cluster add-on plan

Status: **implemented as a pinned `cluster_addons` Helmfile release; pending apply**

This is the separately-reviewed install record required by the repository's
Kubernetes-install gate (see `CLAUDE.md` scope boundaries and
`docs/plans/kubernetes.md`). Design rationale for the wider PKI lives in
`docs/superpowers/specs/2026-07-16-homelab-pki-design.md`; this file covers only
the add-on install.

## What

[cert-manager](https://cert-manager.io) installed as a cluster add-on: the
`jetstack/cert-manager` Helm chart, pinned to chart version `v1.21.0`, deployed
into a dedicated `cert-manager` namespace by the existing `cluster_addons` role
alongside Cilium, MetalLB, Istio, KEDA, and the rest of the platform stack.

It brings three pods (controller, webhook, cainjector) and the
`cert-manager.io` CRDs — `ClusterIssuer`, `Issuer`, `Certificate`,
`CertificateRequest`, `Order`, `Challenge`.

## Why

The `homelab` Gateway (`istio-ingress`) currently serves **HTTP on :80 only** —
there is no TLS anywhere in the north-south path. Grafana and Pi-hole are reached
over plaintext on `*.home.arpa` names.

We own `tfdraw.dev`, hosted on Cloudflare. cert-manager solves an ACME **DNS-01**
challenge against that zone and issues a publicly-trusted Let's Encrypt wildcard
for `*.homelab.tfdraw.dev`, which the Gateway terminates. DNS-01 writes a
temporary `_acme-challenge` TXT record and requires **no inbound connectivity** —
nothing from the internet ever reaches the house. Internal names resolve to the
MetalLB address via Pi-hole (split horizon) and never appear in public DNS.

The alternative — a private CA — would mean installing a root certificate on
every device that talks to the cluster (laptops, phones, guests). Let's Encrypt
is free, already reachable, and trusted natively everywhere. See the design spec
for why the private CA is nonetheless retained for a separate purpose (IAM Roles
Anywhere node identity, which Let's Encrypt structurally cannot serve).

## How

- Repo: `jetstack` (`https://charts.jetstack.io`) added to
  `ansible/roles/cluster_addons/templates/helmfile.yaml.j2`.
- Release: `cert-manager`, namespace `cert-manager`, `createNamespace: true`,
  chart `jetstack/cert-manager`, version
  `{{ cluster_addons_cert_manager_version }}` pinned in
  `ansible/roles/cluster_addons/defaults/main.yml` (`v1.21.0` — verified against
  the chart repo index on 2026-07-16; re-verify before apply, per repo pinning
  policy).
- Applied by the standard `helmfile apply` in the `cluster_addons` role, after
  which the role waits on `deployment/cert-manager-webhook` becoming
  `Available`.

Values set at install:

```yaml
crds:
  enabled: true
dns01RecursiveNameservers: "1.1.1.1:53,9.9.9.9:53"
dns01RecursiveNameserversOnly: true
```

`crds.enabled` is the current spelling; `installCRDs` is deprecated and must not
be used on 1.21. A single Helm release is therefore sufficient — no separate
CRD-apply step, unlike the Gateway API CRDs this role server-side applies.

### The `dns01RecursiveNameservers` values are load-bearing

Before asking Let's Encrypt to validate, cert-manager performs its own
**self-check**: it queries authoritative nameservers to confirm the
`_acme-challenge` TXT record has propagated. By default that query resolves
through cluster DNS.

This cluster's DNS path reaches **Pi-hole**, which answers for
`homelab.tfdraw.dev` (the split-horizon records that point service names at the
MetalLB address). A challenge lookup routed through Pi-hole returns `NXDOMAIN`,
the self-check never passes, and issuance hangs until timeout — with no obvious
error pointing at DNS.

Forcing the self-check to public resolvers (`--dns01-recursive-nameservers`,
`--dns01-recursive-nameservers-only`, surfaced by the chart as the two values
above) bypasses Pi-hole entirely. Set at install rather than retrofitted after a
debugging session.

### Ordering

The helmfile runs before this role's Gateway-resources step, so cert-manager and
its CRDs exist before anything references them. The webhook wait matters
independently: a Helm release reporting Ready does **not** mean the admission
webhook is serving, and a `ClusterIssuer` applied too early fails admission with
a connection error that reads like a network fault.

The wait task is currently appended at the end of `tasks/main.yml`. When the
issuer resources land it should move to sit immediately before them — that is
the thing it exists to gate.

### Operator prerequisites

Before applying, the operator must:

- **Create a scoped Cloudflare API token.** Permissions `Zone:DNS:Edit` +
  `Zone:Zone:Read`, **restricted to the `tfdraw.dev` zone only**. Not the global
  API key. Store it as `vault_cloudflare_api_token` in the encrypted inventory.
- **Bootstrap the Ansible vault** if not already done — see
  `docs/plans/ansible-vault.md`. As of 2026-07-16 the vault password file and
  `group_vars/all/` layout were only partially in place on the controller; both
  are prerequisites for any `cluster_addons` run.
- **Verify the chart pin.** Confirm `cluster_addons_cert_manager_version` against
  `https://charts.jetstack.io/index.yaml` before apply, per repo pinning policy.

### Note: this apply also lands KEDA

`cluster_addons` reconciles every release in the helmfile. As of 2026-07-16,
`helm list -A` shows all nine deployed releases matching their pins exactly (no
drift — Cilium and Istio will not be disturbed), but **KEDA is pinned and not
deployed** (`docs/plans/keda.md` status: "pending apply"). The next
`make -C ansible addons` therefore installs **both** KEDA and cert-manager.
Expected, but not a surprise worth discovering at runtime.

### Note: `CHECK=1` does not work for this role

`make -C ansible addons CHECK=1` fails at `tasks/main.yml:23`
("Destination /tmp/homelab-kubernetes-platform does not exist"). Under
`--check`, the `file` task that creates the working directory only reports the
change; the subsequent `get_url` then has nowhere to write. The role's setup
chain (`file` → `get_url` → `unarchive` → `link`) depends on real side effects,
and its helmfile/kubectl steps are `command` tasks that no-op under check mode
anyway — so `--check` cannot preview this role even when it runs.

Use `helmfile diff` against the rendered file for a genuine preview. Making
`--check` honest would mean adding `check_mode: false` to those four prep tasks;
tracked as a follow-up, not part of this change.

## Verification

```bash
kubectl get pods -n cert-manager           # 3 pods: controller, webhook, cainjector
kubectl get crd | grep cert-manager.io     # 6 CRDs
kubectl get clusterissuers                 # (empty until the issuers land)
```

## Rollback

cert-manager is a self-contained release and can be removed independently, but
**order matters** — uninstalling the chart removes the CRDs, which silently
orphans any `Certificate` still referencing them.

```bash
# Remove issued certs and issuers first (they depend on the CRDs).
kubectl delete -n istio-ingress certificate --all
kubectl delete clusterissuer letsencrypt-staging letsencrypt-prod

# Then uninstall the operator.
helm uninstall cert-manager --namespace cert-manager
kubectl delete namespace cert-manager
```

Removing cert-manager does not revoke already-issued Let's Encrypt certificates
or delete the TLS `Secret`s it wrote; the Gateway keeps serving the last-issued
cert until it expires (≤90 days), at which point the HTTPS listener stops
working. If the Gateway's HTTPS listener has already landed, remove it (or the
`certificateRefs`) as part of the rollback rather than leaving a listener
pointing at a `Secret` nothing renews.
