# Kubernetes service vending

This repository defines the Kubernetes platform as infrastructure as code. OpenTofu owns
AWS resources, Ansible owns the node, cluster, platform resources, tenant namespaces and
lifecycle, Helmfile owns pinned add-ons, and Argo CD owns only explicitly allowlisted
application resources. No namespace, PVC, or application data is automatically destroyed.

## Current state

The target version is Kubernetes `v1.35.7` from the `v1.35` pkgs.k8s.io repository.
Kyverno chart `3.8.2` (application `v1.18.2`) and Argo CD chart `10.3.3`
(application `v3.5.1`) are pinned but disabled by default. Kyverno 1.18 documents support
for Kubernetes 1.33 through 1.35. Argo CD 3.5 includes Kubernetes 1.35 in its tested range.

The repository does not perform an in-place control-plane downgrade. Kubernetes supports
skew for upgrades, not arbitrary downgrades. Moving a node from 1.36 to 1.35 is therefore
a rebuild and restore operation with an explicit maintenance window.

## Ownership

| Owner | Resources |
|---|---|
| Ansible | Namespace, quota, LimitRange, NetworkPolicy, HTTPRoute, Secrets, RBAC, admission, lifecycle state |
| Helmfile | Argo CD, Kyverno, Cilium, Gateway, monitoring and other platform add-ons |
| Argo CD | ConfigMap, Service, ServiceAccount, Deployment, StatefulSet, ReplicaSet, Job, CronJob, HPA, ScaledObject |
| Tenant repository | Desired manifests for only the Argo allowlist |

Argo's default project has no sources, destinations, or resources. The application
controller has no generated cluster role and receives one namespace RoleBinding per active
catalog service. Native ValidatingAdmissionPolicy and PSA restricted controls remain active
when Argo or Kyverno is unavailable.

## Static workflow

```bash
python3 -m pip install -r requirements-vending.txt
python3 scripts/service-catalog.py validate
python3 scripts/service-catalog.py render
python3 scripts/kubernetes-vending.py render --target homelab --phase native
python3 scripts/kubernetes-vending.py render --target homelab --phase argocd
python3 -m unittest discover -s tests/catalog -p 'test_*.py'
```

CI performs those deterministic checks without cluster credentials. A local operator runs
the serialized reconciliation only after its inventory gates are true:

```bash
ANSIBLE_CONFIG=ansible/ansible.cfg ansible-playbook \
  -i ansible/inventories/local/hosts.yml ansible/playbooks/tenants.yml
```

## 1.35 rebuild gate

Before the maintenance window, capture the current OS, kernel, mounts, disk usage,
allocatable node resources, platform Pod requests and limits, GPU model/VRAM/display use,
Kubernetes objects, container images, encryption configuration and backup status. Create an
encrypted off-node etcd snapshot and separate application-data backups. Verify each backup
in a disposable environment before changing the node.

During the window:

1. Suspend catalog services and prove no non-terminal tenant Pods remain.
2. Cordon and drain the node, stop writers, then take final etcd and application backups.
3. Rebuild the control plane from the pinned Ansible `v1.35.7` configuration. Do not run the
   forward-only `kubernetes_upgrade` role as a downgrade mechanism.
4. Restore etcd according to the Kubernetes 1.35 restore procedure, restore application
   data separately, then reconcile add-ons and native tenant controls.
5. Verify `/readyz`, DNS, Cilium, Gateway, audit logging, Secret encryption, external alerts,
   and a reboot before setting any add-on gate true.

Rollback means rebuilding the previous pinned version and restoring its matching verified
snapshot. Merely retaining `admin.conf` is not a recovery plan.

## Rollout evidence

Keep the flags in `cluster_addons` and `kubernetes_tenants` false until each item is attached
to the change record:

- Kubernetes 1.35 compatibility is confirmed for the actual Ubuntu release and kernel.
- API Secret encryption at rest is enabled, keys are backed up and rotated, existing
  Secrets are re-encrypted, and a snapshot restore is tested.
- Audit logs exclude Secret bodies, are bounded, and have a verified off-node copy.
- Direct API attempts prove prohibited resources, host access, missing resources,
  selectorless proxying, `externalIPs`, and tenant priority escalation are denied.
- Kyverno admission is ready and its disruption behavior is documented for this single
  node. Audit results are remediated before `cluster_addons_kyverno_enforce` becomes true.
- A dedicated least-privilege registry credential is refreshed without values in source,
  arguments, logs, diffs, or temporary files. ECR token expiry and outage tests pass.
- A signed private-ECR image validates only against the exact protected main workflow
  identity and issuer. Unsigned, wrong-repository, wrong-workflow and expired-auth cases
  fail.
- Argo pruning, self-healing, bounded retry, Git-revert rollback and platform-owned data
  preservation tests pass through the admission path.

Set `kubernetes_tenants_argocd_ready` only when both
`kubernetes_tenants_kyverno_ready` and `kubernetes_tenants_secret_contracts_ready` are true.
Secret contract metadata is stored in the catalog, but values are intentionally not handled
by this repository until an approved runtime materialization path exists.

## Lifecycle, storage and GPU

The catalog accepts only `active -> suspended -> archived` unless an operator supplies the
validator override. Suspension removes the route and Argo Application, scales controllers,
suspends CronJobs, pauses KEDA, revokes contracted runtime credentials, and retains data.
Archive remains non-cascading. Capacity is released only after reconciliation sees no
non-terminal tenant Pods and records that state in `kube-system/tenant-catalog-state`.

Tenant PVC and GPU vending remain structurally disabled. Enable PVCs only after physical
per-volume quotas and independent filesystem pressure alarms exist. Enable GPU only after
the real hardware, display use, driver, MIG geometry and reboot recovery are recorded. Use
one exact MIG resource if two suitable instances exist; otherwise GPU access is exclusive.

## References

- [Kyverno release and Kubernetes support policy](https://kyverno.io/docs/installation/releases/)
- [Argo CD tested Kubernetes versions](https://argo-cd.readthedocs.io/en/release-3.5/operator-manual/tested-kubernetes-versions/)
- [Kubernetes version skew policy](https://kubernetes.io/releases/version-skew-policy/)
- [Encrypting Kubernetes Secret data at rest](https://kubernetes.io/docs/tasks/administer-cluster/encrypt-data/)
