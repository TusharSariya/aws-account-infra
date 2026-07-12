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
  kubelet ECR credential provider (`kubernetes_node` role) using the read-only
  IAM user from `live/aws/staging/account/ecr_pull_iam.tf` — no imagePullSecret.

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
