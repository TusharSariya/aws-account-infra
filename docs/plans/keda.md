# KEDA cluster add-on plan

Status: **implemented as a pinned `cluster_addons` Helmfile release; pending apply**

This is the separately-reviewed install record required by the repository's
Kubernetes-install gate (see `CLAUDE.md` scope boundaries and
`docs/plans/kubernetes.md`).

## What

[KEDA](https://keda.sh) (Kubernetes Event-Driven Autoscaling) installed as a
cluster add-on: the `kedacore/keda` Helm chart, pinned to chart version
`2.20.1`, deployed into a dedicated `keda` namespace by the existing
`cluster_addons` role alongside Cilium, MetalLB, Istio, and the rest of the
platform stack.

## Why

The `harvest-work` worker drains per-source ingest queues (arxiv, openalex, s2)
that are idle most of the time and bursty when a crawl is scheduled. Running
always-on Deployments would waste the homelab's small capacity. KEDA scales each
source from zero on demand: the `cluster_harvester` role defines one KEDA
`ScaledJob` per source, and KEDA's **postgresql scaler** reads the pending
`pgmq` queue length directly from Supabase (`pgmq.metrics('<queue>')`, as the
read-only `harvester_keda_ro` role) to decide how many worker Jobs to run, up to
a per-source cap. See `ansible/roles/cluster_harvester/` and
`ansible/playbooks/harvester.yml`.

## How

- Repo: `kedacore` (`https://kedacore.github.io/charts`) added to
  `ansible/roles/cluster_addons/templates/helmfile.yaml.j2`.
- Release: `keda`, namespace `keda`, `createNamespace: true`, chart
  `kedacore/keda`, version `{{ cluster_addons_keda_version }}` pinned in
  `ansible/roles/cluster_addons/defaults/main.yml` (`2.20.1` — verify current
  against the chart repo before apply, per repo pinning policy).
- Applied by the standard `helmfile apply` in the `cluster_addons` role, after
  which the role waits on `deployment/keda-operator` becoming `Available`.
- Workers pull the prod harvest image from ECR; auth is handled by the node
  kubelet ECR credential provider (`kubernetes_node` role). It sources AWS
  credentials from **IAM Roles Anywhere** — each node presents an X.509 client
  cert to the trust anchor and receives short-lived STS creds, so there is no
  static AWS access key and no imagePullSecret. See the flow below.

## ECR pull auth: IAM Roles Anywhere

The homelab nodes run off-cloud (no EC2 instance role, no OIDC), so kubelet's
`ecr-credential-provider` plugin needs AWS credentials. Rather than a long-lived
access key, the node uses IAM Roles Anywhere:

1. The operator's **CA certificate** is registered as a Roles Anywhere trust
   anchor in `live/aws/staging/account/ecr_pull_iam.tf`
   (`aws_rolesanywhere_trust_anchor`, input var `homelab_ca_certificate_pem`).
2. That file also defines the IAM role (`homelab-ecr-pull`, trusting
   `rolesanywhere.amazonaws.com` and carrying the repo-scoped ECR-read policy)
   and a Roles Anywhere profile. Its outputs expose the trust-anchor / profile /
   role ARNs.
3. On each node the `kubernetes_node` role installs the **aws_signing_helper**
   (AWS IAM Roles Anywhere Credential Helper) binary, mints the node's client
   cert via an **on-node CSR** (the node generates and keeps its own private key
   at `/etc/kubernetes/rolesanywhere/key.pem`; the controller signs the CSR with
   the homelab CA and returns only the public `cert.pem`), and writes an AWS
   config whose `[default]` profile runs `aws_signing_helper credential-process
   ...` as a `credential_process`.
4. The credential provider (via `AWS_CONFIG_FILE`) invokes that process, the
   helper signs a request with the client cert, Roles Anywhere validates it
   against the trust anchor, and STS returns temporary creds scoped to the role.

### Operator prerequisites

The CA, trust anchor, node-cert custody, reproduction steps, and threat model all
live in **[`homelab-ca.md`](homelab-ca.md)** — that is the source of truth for
this trust domain. In summary, before applying:

- **Bring a CA and register the trust anchor.** See `homelab-ca.md`. The AWS side
  is Terraform (`live/aws/staging/account/ecr_pull_iam.tf`), applied with the CA's
  public PEM as `-var homelab_ca_certificate_pem=...`. That variable gates the whole
  chain via `count`, so an apply that omits it plans the trust anchor, role, and
  profile for **destruction** — breaking ECR pull on every node.
- **Wire the ARNs and CA paths into inventory.** Set
  `kubernetes_node_ecr_rolesanywhere_trust_anchor_arn`, `_profile_arn`, `_role_arn`,
  plus `kubernetes_node_ecr_ca_certificate_path` / `_ca_privatekey_path` (see
  `inventories/example/group_vars/all/main.yml`). The two CA paths are the switch:
  both must be non-empty or every ECR task skips silently.
- **Per-node client certs need no operator action.** `node-prepare` mints them via
  an on-node CSR. There is no `vault_ecr_pull_node_certificate` /
  `vault_ecr_pull_node_private_key` — a node's private key never leaves the node.
- **Verify the binary pins.** Confirm `kubernetes_node_aws_signing_helper_version`
  and `kubernetes_node_ecr_credential_provider_version` / URLs / per-arch SHA256
  before apply, per repo pinning policy. The credential provider is pinned to
  **v1.31.0** deliberately: upstream stopped publishing prebuilt binaries after it,
  and every later `artifacts.k8s.io` path 404s.

## Rollback

KEDA is a self-contained release and can be removed independently:

```bash
# Remove the harvester workloads first (ScaledJobs depend on the KEDA CRDs).
kubectl delete -n harvester scaledjob --all
kubectl delete -n harvester triggerauthentication harvester-pg

# Then uninstall the operator.
helm uninstall keda --namespace keda
kubectl delete namespace keda
```

Uninstalling the chart removes the KEDA CRDs; any remaining `ScaledJob` /
`TriggerAuthentication` objects become inert first, so delete them before the
release. Removing KEDA does not touch the harvest queues or Supabase data.
