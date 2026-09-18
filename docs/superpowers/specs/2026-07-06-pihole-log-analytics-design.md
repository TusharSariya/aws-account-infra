# Pi-hole DNS query-log analytics → Loki + Grafana

> [!IMPORTANT]
> Historical record only. This document describes the retired Ubuntu/kubeadm and Ansible path. Its commands are archival examples and must not be run. Removed sources remain available in the [pre-removal repository tree](https://github.com/TusharSariyaOrg/aws-account-infra/tree/9a5f9720e45e3bbcbb5637e7bd27a8c688d53add/ansible). Current server management uses Talos, OpenTofu, and Helm.

Date: 2026-07-06
Status: implemented (pending live cutover)

## Problem

Pi-hole exposes nothing to the monitoring stack. Per-query DNS logs live only inside
the container (`/var/log/pihole/pihole.log`) and aggregate stats only in the FTL SQLite
DB. DNS query logs are the richest passive sensor on the LAN — every connection starts
with a lookup — so they enable useful analytics (per-device domain history, NXDOMAIN/DGA
canaries, blocked-domain trends, beaconing patterns). This is the first concrete slice of
`observability.md` Phase 5 (centralized logs).

## Goals

- Ship Pi-hole query logs into a single-node Grafana Loki and visualize them.
- Add the Pi-hole metrics path (exporter → Prometheus) in parallel.
- Alert on Pi-hole blocking health.
- Reconcile everything through the existing IaC toolchain (Ansible + Helmfile) — **no
  manual `kubectl apply`**.

## Key decisions

- **Pi-hole becomes a Helm release** (`mojo2600/pihole` 2.37.0, Pi-hole v6 image
  `2026.06.0`), replacing the retired hand-applied `kubernetes/apps/pihole/pihole.yml`.
  Deployed by a **new `cluster_apps` Ansible role**, symmetric with `cluster_addons`
  (each role renders its own Helmfile + a companion resources template). Chosen over an
  Ansible-templated manifest to be fully Helm-native; the chart was verified to support
  every needed value (v6 `existingSecret`, `existingClaim`, `extraContainers`,
  `extraVolumes`, `serviceDns` LoadBalancer + MetalLB annotation, mixed TCP/UDP DNS).
- **Alloy as a chart sidecar** (`extraContainers` + a shared `emptyDir` at
  `/var/log/pihole`). Pi-hole v6 writes per-query lines to a *file*, not stdout, so a
  node-level scraper can't see them; a sidecar tailing the file is the only clean in-pod
  option. A cluster-wide Alloy DaemonSet for general stdout logs is deferred to when the
  RAG services exist.
- **pihole-exporter is standalone** (`ekofr/pihole-exporter` v1.2.0, a Deployment that
  reaches the Pi-hole web Service over the network), decoupling the metrics path from the
  risky Pi-hole chart cutover.
- **Logs vs metrics division.** The dnsmasq log carries the client only on the
  `query[...] from <client>` line; `reply`/`blocked` lines don't. So per-client
  blocked/NXDOMAIN aggregates come from the exporter (FTL's correlated DB), while Loki
  carries raw per-query forensic detail.
- **Cardinality discipline.** Only `action` (+`client` where present) become Loki stream
  labels. The domain stays in the log line and is extracted at query time with LogQL
  (`| regexp`/`| pattern`), never a label.
- **Single-binary Loki** (`grafana-community/loki` 18.4.0, Loki 3.7.3), filesystem
  storage on `local-path`, `replication_factor: 1`, compactor retention; minio/gateway/
  caches disabled to keep RAM low on one node.
- **Alerts** are metric-based (blocking health) via `additionalPrometheusRulesMap`.
  NXDOMAIN/DGA detection is a Loki dashboard panel, not a fired alert (Loki's ruler is
  disabled, and reply-line client attribution is unreliable).

## Architecture

```
cluster_apps (Helmfile)                    cluster_addons (Helmfile)
  pihole RELEASE (mojo2600)                  loki RELEASE (single-binary, filesystem)
    pihole container (v6)                     kube-prometheus-stack values:
      FTL → /var/log/pihole/pihole.log          + Loki datasource
    alloy SIDECAR ── push ─────────────────►    + PrometheusRule (blocking health)
      (shared emptyDir)                    Prometheus ◄── ServiceMonitor
  resources template:                        Grafana ◄── logs + metrics dashboards
    HTTPRoute pihole.home.arpa
    Alloy config ConfigMap
    pihole-exporter Deploy+Svc+ServiceMonitor (standalone, → pihole-web)
    Grafana dashboards ConfigMap (monitoring ns)
```

## Files

- `ansible/roles/cluster_addons/defaults/main.yml` — `cluster_addons_loki_*` pins.
- `ansible/roles/cluster_addons/templates/helmfile.yaml.j2` — `grafana-community` repo,
  `loki` release, Grafana `additionalDataSources` (Loki), `additionalPrometheusRulesMap`.
- `ansible/roles/cluster_apps/` — new role: `defaults/main.yml` (pins),
  `templates/helmfile.yaml.j2` (pihole release + Alloy sidecar),
  `templates/pihole-resources.yml.j2` (Alloy config, HTTPRoute, exporter+ServiceMonitor),
  `templates/pihole-dashboards.yml.j2` + `files/pihole-{logs,metrics}-dashboard.json`,
  `tasks/main.yml`.
- `ansible/playbooks/apps.yml` — runs `cluster_apps` (after `addons.yml`).
- `ansible/roles/cluster_validation/` — `cluster_validation_loki_*` + a Loki readiness wait.
- `ansible/inventories/example/group_vars/all.yml` — `kubernetes_loki_*`,
  `kubernetes_pihole_*` placeholders (real values + the `pihole-admin` Vault secret live
  in the git-ignored `local` inventory).
- Removed `kubernetes/apps/pihole/pihole.yml` (chart owns it now); kept the macOS DNS
  helper scripts.

## Pinned versions (verified 2026-07-06)

| Component | Pin |
|---|---|
| Loki chart | `grafana-community/loki` 18.4.0 (Loki 3.7.3) |
| Pi-hole chart | `mojo2600/pihole` 2.37.0 |
| Pi-hole image | `2026.06.0` (v6) |
| Grafana Alloy | `grafana/alloy:v1.17.1` |
| pihole-exporter | `ekofr/pihole-exporter:v1.2.0` (Pi-hole v6 auth) |

## Migration & cutover (deliberate, like the Istio flip)

1. Preserve the `pihole-data` PVC and `pihole-admin` secret; the chart adopts the PVC via
   `existingClaim`. Back up `pihole-FTL.db` first.
2. Delete the retired raw `Deployment`/`Service`/`HTTPRoute` (NOT the PVC/secret) — Helm
   cannot adopt them and the DNS LoadBalancer IP can only be held by one Service. The role
   preflights this and fails with guidance if a non-Helm `pihole` Deployment is present.
3. `ansible-playbook playbooks/apps.yml` → the chart Service reclaims the DNS IP. Brief DNS
   outage during the flip (Pi-hole is the LAN resolver; macOS DNS helper scripts as fallback).

## Verification

1. `ansible-playbook playbooks/addons.yml` → Loki Ready; Grafana shows the Loki datasource;
   PrometheusRule loaded.
2. `ansible-playbook playbooks/apps.yml` → pihole pod = `[pihole, alloy]`; exporter scraped
   (`pihole_*` in Prometheus); `pihole.home.arpa` served.
3. Generate DNS traffic → Grafana Explore `{job="pihole"}` shows lines; both dashboards render.
4. `ansible-playbook playbooks/validate.yml` → Loki readiness check passes.

## Risks / follow-ups

- Chart v6 compatibility + value support: verified via `helm template` before implementation.
- Hand-authored dashboards may need minor LogQL/PromQL tuning against real data.
- Alerts show in the UI only until an Alertmanager receiver is configured.
- Pi-hole probe/securityContext hardening and Loki/Grafana TLS remain follow-ups.
- `CLAUDE.md` "Kubernetes is documentation-only" wording is stale post-Istio — track separately.
