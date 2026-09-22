# Main cluster on the laptop

This directory is the main cluster's monitoring, Argo CD and placement configuration.
It is independent of the pilot's addresses, credentials and lifecycle controllers.
It creates no Application and does not adopt existing releases into GitOps.

Live status and the ordered migration procedure are in
[the control-plane runbook](../../../docs/runbooks/main-control-plane.md).
[Manual sleep/wake](../../../docs/runbooks/manual-server-sleep.md) requires an accepted
relocation first. Monitoring and GitOps stop when worker 01 sleeps; stored data
survives, but collection and reconciliation pause. This is not HA.

## Placement and storage

`placement/plan.py` discovers only the named existing main workloads. Without
`--apply`, it saves originals and UID/spec guarded patches outside
Git and performs server dry-runs. CoreDNS and Cilium operator stay on the tainted
control plane. Platform controllers, backups, local storage and persistent apps
are primary-pinned. Runners with claims remain primary-pinned; eligible compute
prefers primary while allowing secondary. Merge `compute-template.yaml` into
eligible Argo workflow templates through their existing Helm/config ownership.

Apply `placement/proxy-class.yaml`, then set `tailscale.com/proxy-class:
primary-applications` on the selected application Services and Ingresses through
their owning manifests/post-renderer. Do not patch generated
proxy StatefulSets: the operator would revert that placement. Leave dormant AI
services, workloads and data unchanged. Preserve existing Helm values when
persisting placement changes; do not run a chart upgrade using only these fragments.

Existing classes and PVCs are not migrated. `placement/storage-class.yaml` adds
only a non-default, Retain, WaitForFirstConsumer `local-primary` class. Its `defaultVolumeType: local` annotation requests local PVs so kubelet
filesystem metrics are available. The audited
provisioner allows only `/var/mnt/local-path-provisioner` on worker 01 and refuses
OS-disk fallback. Do not apply the older namespace-wide admission binding to
namespaces with existing classes. No volume or claim deletion is part of rollout.
Local-path claim sizes are provisioning requests, not enforced filesystem quotas.

## Monitoring

Single-instance deployments use pinned digests, restricted Pod security, probes,
explicit limits, minimal RBAC and private network policies. Claims are 10 GiB
Prometheus, 10 GiB Loki, 2 GiB Grafana, 1 GiB Alloy and 1 GiB Alertmanager.
Prometheus, Loki and Alertmanager retain 48 hours. Prometheus caps retained blocks
at 8 GB; WAL/head storage needs additional reserve. Requests total 700m CPU and
1216 MiB; memory limits total 3584 MiB. Grafana/Alloy storage holds configuration
and collection state, not an independent 48-hour log database.

Alloy reads the Kubernetes API only in `monitoring`, and only Pods opting in with
`monitoring.homelab/main-logs=true`. It keeps only exact `main-observe TOKEN`
markers, dropping ordinary logs and payloads. Broader namespaces require an
explicit matching discovery and namespaced Role/RoleBinding change. No host logs,
host tokens or privileged node proxies are collected. Kubelet metrics use verified
TLS and narrowly scoped `nodes/metrics` access; do not bypass TLS verification to
make a scrape pass. Alertmanager initially retains alerts for its authenticated
administrative tunnel; external delivery is not configured.

```sh
python3 kubernetes/platform/main/monitoring/render.py
python3 kubernetes/platform/main/validate.py
python3 -m unittest discover -s platform/main-control-plane/tests -v
```

`accept-monitoring.py` verifies dashboard samples, marker-only logs after canary
replacement, alert firing/resolution and unchanged claims. Its smoke result alone
does not certify worker-restart persistence. `bounded-load.py` runs four ten-minute
Jobs (1 CPU and 512 MiB total) while sampling laptop/control-plane reserves.

`install.py monitoring --kubeconfig PATH --acceptance PATH` requires a fresh
control-plane acceptance receipt. Argo installation requires a separate fresh
monitoring receipt. Receipts are private JSON with `component`, `passed: true`,
`completed` (UTC ISO timestamp), and linked evidence. They are operator attestations
after all runbook checks, not a substitute for those checks. Never fabricate one
to advance a blocked cutover.

## Argo CD and access

The checksum-locked upstream non-HA namespace installation is v3.5.3. Repository,
server, Redis and application controller are primary-pinned with explicit budgets;
unused Dex, notifications and ApplicationSet deployments have zero replicas.
Both projects are closed (`sourceRepos: []`, `destinations: []`), no cluster-wide
application RBAC is granted, and no repo Secret or Application is installed.
Manual sync and disabled pruning must be preserved when later onboarding an app.
Repository egress and target-namespace RBAC are also later-stage changes.

Use administrative Kubernetes credentials and localhost-only forwards:

```sh
kubectl --kubeconfig "$KUBECONFIG" -n monitoring port-forward --address=127.0.0.1 service/grafana 3000:3000
kubectl --kubeconfig "$KUBECONFIG" -n monitoring port-forward --address=127.0.0.1 service/prometheus 9090:9090
kubectl --kubeconfig "$KUBECONFIG" -n monitoring port-forward --address=127.0.0.1 service/loki 3100:3100
kubectl --kubeconfig "$KUBECONFIG" -n monitoring port-forward --address=127.0.0.1 service/alertmanager 9093:9093
kubectl --kubeconfig "$KUBECONFIG" -n argocd port-forward --address=127.0.0.1 service/argocd-server 8443:443
```

Retrieve Grafana's `grafana-admin/password` and Argo's initial admin password
privately with kubectl. Do not publish them in logs or evidence. If forwarding
on the laptop, use an SSH localhost tunnel from the recovery workstation.
NetworkPolicies permit internal traffic and API/DNS/metrics only. Validate Cilium's
service-DNAT policy behavior during acceptance; add only exact required endpoints
if it differs. No ingress or LoadBalancer is installed.

Rollback monitoring by scaling its five deployments to zero, retaining its namespace,
Secrets and all PVC/PVs. Roll back Argo by scaling only its controllers/server/repo/Redis
to zero. Leave CRDs and existing applications untouched. Do not use `kubectl delete -k`
on monitoring, because that would delete claims. Reapply the same manifests to resume.

The three existing Terraform roots now invoke this renderer automatically for every
Helm release, passing the release namespace explicitly and hashing both renderer
and policy into release inputs. Kueue retains its admission filter before placement.
For a manually invoked Helm upgrade outside those roots, preserve placement using
`--post-renderer ./kubernetes/platform/main/placement/helm-post-renderer.py`
(with Python/PyYAML installed). Set `MAIN_HELM_NAMESPACE` to the release namespace when invoking Helm; the renderer
refuses to silently skip namespaced objects that omit it.
This applies the same explicit allowlist as the live placement plan, preserving
AI specs and existing storage. Keep the primary-applications ProxyClass installed.
The primary affinity is idempotent; UID/spec guards ignore status-only updates
while refusing concurrent desired-state changes.

Kubelet metrics use the existing Kubernetes CA with IP SAN verification. The
main nodes have `machine.kubelet.extraConfig.serverTLSBootstrap: true` from
`platform/main-control-plane/kubelet-serving-certificates.yaml`. Each serving CSR
was checked for its exact node username, system:nodes organization, node DNS/IP
SANs, kubernetes.io/kubelet-serving signer and server-auth usage before approval.
No blanket CSR approver or TLS bypass is installed. Review renewal CSRs the same
way before the current certificates expire. See the [Talos configuration reference](https://www.talos.dev/v1.8/reference/configuration/v1alpha1/config/)
and [Kubernetes TLS bootstrap](https://kubernetes.io/docs/reference/access-authn-authz/kubelet-tls-bootstrapping/).

Cilium node identities require explicit entity rules: ordinary IP-block policies
exclude cluster nodes. Narrow Cilium policies permit Alloy and Argo API access,
and Prometheus TCP/10250 node metrics; metric RBAC still restricts the three
named nodes. See [Cilium policy semantics](https://docs.cilium.io/en/stable/network/kubernetes/policy/).

The installer server-side applies the large Argo CRDs without embedding their
schemas in a last-applied annotation. It creates the private Redis password once,
so Redis needs neither an API token nor its upstream Secret-initialization Role.
Do not replace that Secret during an upgrade; Argo components share its value.
`accept-argocd.py` verifies the local TLS certificate, authenticates through an
administrative port forward, and asserts zero Applications and repository/cluster
credential Secrets. Run it again after worker recovery.
