# Kubernetes observability

This document defines the observability roadmap for the homelab Kubernetes
cluster. The implementation is intentionally incremental: metrics and alerts
come first, followed by synthetic probes, GPU monitoring, application metrics,
logs, traces, and network visibility.

The cluster currently has one physical node and uses local-path storage.
Monitoring data therefore survives pod restarts, but it is not highly
available and is lost if the node or its local disk is lost.

## Architecture

```text
Kubernetes components ─┐
Node exporter ─────────┤
kube-state-metrics ────┼──> Prometheus ──> Grafana
Application metrics ───┤          │
DCGM GPU metrics ──────┘          └──> Alertmanager ──> notifications

Blackbox probes ──> DNS, HTTP and ingress availability
Alloy ──> Loki ──> centralized logs
OpenTelemetry Collector ──> Tempo ──> distributed traces
Cilium Hubble ──> network-flow visibility
```

## Phase 1: cluster metrics and alerting

Status: implemented in the `cluster_addons` Helmfile.

The pinned `kube-prometheus-stack` release installs:

- Prometheus Operator and Prometheus
- Alertmanager
- Grafana with Kubernetes dashboards
- node-exporter
- kube-state-metrics
- Kubernetes recording and alerting rules

The single-node configuration uses:

- Seven days of Prometheus retention, capped at 8 GB
- A 10 GiB Prometheus PVC
- A 1 GiB Alertmanager PVC with five days of retention
- A 2 GiB Grafana PVC
- The `local-path` StorageClass and `storage=local` node label
- ClusterIP services only; no unauthenticated LAN exposure

Install or reconcile it with:

```bash
cd ansible
ansible-playbook playbooks/addons.yml
```

Inspect the rollout:

```bash
kubectl get pods,pvc -n monitoring
kubectl get prometheus,alertmanager -n monitoring
```

Access Grafana through the shared Gateway API endpoint:

```bash
open http://grafana.home.arpa
```

The hostname is resolved by the Pi-hole `FTLCONF_dns_hostRecord` (set by the
`cluster_apps` role) and routed by an Istio Gateway API HTTPRoute.
The username is `admin`. Retrieve the generated password without committing it
to the repository:

```bash
kubectl get secret -n monitoring kube-prometheus-stack-grafana \
  -o jsonpath='{.data.admin-password}' | base64 --decode
echo
```

If Gateway API is unavailable during troubleshooting, use a temporary local
forward:

```bash
kubectl port-forward -n monitoring pod/kube-prometheus-stack-grafana-0 3001:3000
```

Initial alerts should cover node readiness, filesystem pressure, pod restart
loops, PVC capacity, Kubernetes API health, and etcd health. Alertmanager does
not send notifications until a receiver such as email, Slack, or Discord is
configured.

## Phase 2: synthetic availability

Install Prometheus Blackbox Exporter and define probes that exercise the same
paths clients use:

- DNS resolution through Pi-hole at `10.0.0.232:53`
- Pi-hole administration HTTP at `http://10.0.0.232/admin/`
- ingress-nginx through MetalLB at `10.0.0.231`
- The future RAG query endpoint

A successful pod health check is insufficient for DNS. The probe must perform
an actual DNS lookup and alert when resolution fails or becomes slow.

## Phase 3: GPU telemetry

The NVIDIA GPU Operator already runs `nvidia-dcgm-exporter`. Add a
`ServiceMonitor` so Prometheus records GPU utilization, VRAM, temperature,
power, throttling, and XID errors. The Phase 1 Prometheus configuration accepts
`ServiceMonitor` and `PodMonitor` resources from other releases and
namespaces.

## Phase 4: RAG application metrics

Every RAG service should expose a Prometheus `/metrics` endpoint. At minimum,
record:

- Queue depth and oldest queued-job age by priority
- Completed, retried, and failed jobs by pipeline stage
- Harvest, extraction, chunking, embedding, and indexing duration
- Documents and chunks processed
- Query latency and error rate
- Retrieval, reranking, and inference duration
- GPU queue wait time, tokens per second, and model identity

Prefer bounded labels. Do not use document IDs, request IDs, URLs, or arbitrary
error messages as Prometheus labels because their unbounded cardinality can
exhaust memory.

## Phase 5: centralized logs

Status: first slice implemented — Pi-hole DNS query logs.

A single-binary Grafana Loki (filesystem storage on `local-path`, bounded
retention via the compactor) is deployed by the `cluster_addons` Helmfile in the
`monitoring` namespace and wired into Grafana as a datasource. The first log
source is Pi-hole: an **Alloy sidecar** (in the Pi-hole pod, deployed by the
`cluster_apps` role) tails the FTL dnsmasq query log
(`/var/log/pihole/pihole.log`, a file — not stdout) and pushes to Loki. It
promotes only a bounded label set (`action`, and `client` on query lines); the
domain stays in the log line and is extracted at query time with LogQL, so
per-domain cardinality never enters the index. A "Pi-hole — DNS query logs"
Grafana dashboard ships alongside the exporter-fed "Pi-hole — metrics" one.

Retention and the PVC size are set from the inventory
(`kubernetes_loki_retention_hours`, `kubernetes_loki_storage_size`); the query
log stays LAN-internal (no external route). See `docs/gateway-api.md` and the
design spec `docs/superpowers/specs/2026-07-06-pihole-log-analytics-design.md`.

Next, extend the same pipeline to application logs: deploy a cluster-wide Alloy
DaemonSet for stdout collection once the RAG services exist. Those services
should emit structured JSON containing fields such as `request_id`,
`document_id`, `pipeline_stage`, `priority`, `model`, `duration_ms`, and a
bounded error category.

Keep short retention and explicit storage limits. Logs grow much faster than
metrics and use the same single local disk as the workloads they observe.
Secrets, document contents, prompts, and retrieved private text must not be
logged by default.

## Phase 6: distributed tracing

Instrument the online request path with the OpenTelemetry SDK and deploy an
OpenTelemetry Collector when requests cross several services:

```text
query API -> retrieval -> reranking -> model server
```

Export traces to Grafana Tempo. Propagate trace context through HTTP, gRPC, and
queued jobs. Use sampling so successful high-volume requests do not overwhelm
local storage, while retaining errors and slow traces at a higher rate.

## Phase 7: network visibility

Cilium provides Hubble network-flow data, but Hubble Relay and Hubble UI are
not currently deployed. Add them when service-to-service network policies or
multi-node troubleshooting make flow visibility useful.

Hubble complements application telemetry by showing accepted and dropped
connections, DNS traffic, and network-policy decisions. It does not replace
application metrics or tracing.

## Operational policy

- Alert on symptoms visible to users, not only pod state.
- Keep monitoring endpoints private until authentication and TLS are defined.
- Set requests, limits, retention, and storage caps for every telemetry system.
- Back up dashboards and alert configuration as code; do not rely on Grafana's
  local database as the only copy.
- Do not make Kubernetes recovery depend on Pi-hole or the monitoring stack.
- Review noisy alerts and unused high-cardinality metrics regularly.
- Treat outbound vendor telemetry separately from local observability and
  enable it only through an explicit decision.

## References

- [Prometheus Operator](https://prometheus-operator.dev/)
- [kube-prometheus-stack chart](https://github.com/prometheus-community/helm-charts/tree/main/charts/kube-prometheus-stack)
- [Prometheus storage](https://prometheus.io/docs/prometheus/latest/storage/)
- [Grafana Loki](https://grafana.com/docs/loki/latest/)
- [OpenTelemetry on Kubernetes](https://opentelemetry.io/docs/platforms/kubernetes/)
- [NVIDIA DCGM Exporter](https://docs.nvidia.com/datacenter/dcgm/latest/gpu-telemetry/dcgm-exporter.html)
- [Cilium Hubble](https://docs.cilium.io/en/stable/observability/hubble/)
