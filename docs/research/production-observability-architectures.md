# Production observability architectures for a small Kubernetes cluster

Research date: 2026-09-01

## Question and scope

This report compares coherent production-grade architectures for metrics, logs,
traces, profiling, alerting, SLOs, telemetry collection, retention, and
long-term storage on a small four-node Kubernetes cluster. It does **not** select
a final stack. The target is production operating discipline on modest hardware,
not enterprise traffic simulation.

Only first-party project documentation and repositories are cited. Resource
figures marked **estimate** are planning envelopes derived from the explicit
workload assumptions below; they are not vendor guarantees.

## What is common to all coherent architectures

OpenTelemetry (OTel) is a telemetry generation, enrichment, transport, and
export standard, not a durable observability database. Its stable signal set is
traces, metrics, and logs; profiles are currently Alpha. This makes OTel a good
portable collection plane while leaving backend selection independent by signal
([OTel signals](https://opentelemetry.io/docs/concepts/signals/),
[OTel profiles](https://opentelemetry.io/docs/concepts/signals/profiles/)).

A Kubernetes collection plane can use:

- a node-local Collector DaemonSet for container logs, host metrics, and node
  enrichment;
- an optional gateway Deployment for one OTLP endpoint, centralized sampling,
  filtering, routing, and backend credentials; and
- direct Prometheus scraping for Kubernetes and exporters where pull semantics
  are already mature.

OTel documents agent, gateway, and combined patterns and warns that the combined
agent-to-gateway pattern adds complexity. Stateful metric processors must keep a
given metric stream routed consistently, and gateways should be made highly
available when they are the sole ingest path
([Collector deployment patterns](https://opentelemetry.io/docs/collector/deploy/),
[agent-to-gateway pattern](https://opentelemetry.io/docs/collector/deploy/other/agent-to-gateway/)).
The official Helm chart supports DaemonSet, Deployment, or StatefulSet modes and
includes batching and memory limiting in its baseline configuration
([Collector Helm chart](https://opentelemetry.io/docs/platforms/kubernetes/helm/collector/)).

The control loop is also common:

1. instrument applications with OTel semantic conventions and propagate trace
   context so logs, metrics, and traces correlate;
2. define low-cardinality service metrics and explicit telemetry budgets;
3. express SLOs as Prometheus recording and multi-window burn-rate alert rules;
4. route actionable alerts through Alertmanager; and
5. test the entire notification path externally.

Prometheus deliberately separates rule evaluation from Alertmanager's grouping,
inhibition, silencing, and notification delivery
([alerting overview](https://prometheus.io/docs/alerting/latest/overview/)). Its
guidance is to alert on user-visible symptoms and keep pages actionable
([alerting practices](https://prometheus.io/docs/practices/alerting/)). Pyrra is
one optional thin SLO control plane: its Kubernetes operator converts SLO CRs to
Prometheus recording rules and multi-burn-rate alerts; it is not another metrics
database ([Pyrra repository](https://github.com/pyrra-dev/pyrra)).

## Architecture A: compact, signal-specific backends

```text
apps/exporters -> OTel node agents -> optional OTel gateway
                      |                         |
                      +-> Prometheus scrape    +-> Loki (logs)
                                                -> Tempo (traces)
                                                -> Pyroscope (profiles, optional)

Prometheus rules -> Alertmanager -> notification providers
Prometheus/Loki/Tempo/Pyroscope -> Grafana
```

Run one local Prometheus TSDB, Alertmanager, Grafana, Loki in monolithic mode,
Tempo in monolithic mode, and optionally Pyroscope in single-binary mode. Use
local persistent volumes for short retention and/or an S3-compatible object
store for the backends that support it. This preserves distinct failure and
retention policies per signal without deploying each backend as microservices.

This is internally coherent because:

- Prometheus local storage is intentionally single-node and non-replicated. It
  is a valid operational choice when loss of recent metrics is acceptable and
  alerting availability is handled explicitly. Prometheus states that NFS is
  unsupported for its TSDB and recommends local filesystems
  ([Prometheus storage](https://prometheus.io/docs/prometheus/latest/storage/)).
- Loki monolithic mode is documented for small volumes up to roughly 20 GB/day.
  It can use shared object storage, while current Simple Scalable Deployment is
  deprecated for removal in Loki 4.0
  ([Loki deployment modes](https://grafana.com/docs/loki/latest/get-started/deployment-modes/)).
- Tempo monolithic mode requires no Kafka, is documented for low-to-moderate
  volume, and recommends object storage in production. It cannot isolate query
  spikes from writes or scale components independently
  ([Tempo deployment modes](https://grafana.com/docs/tempo/latest/reference-tempo-architecture/deployment-modes/)).
- Loki retention is performed by a singleton Compactor and must be enabled; its
  marker files require persistent storage unless stored in object storage
  ([Loki retention](https://grafana.com/docs/loki/latest/operations/storage/retention/)).

Failure behavior: a backend pod/node loss causes a signal-specific outage, not
an application outage. Local Prometheus data follows its PV; corruption or PV
loss loses history since backup. An OTel node agent can buffer briefly, but the
gateway must not be treated as a durable queue. A failed object store stops block
flush/query and eventually creates backpressure. Alertmanager can run as an HA
gossip pair; it intentionally fails open during partitions, preferring duplicate
notifications over missed alerts, and Prometheus must send to every instance
([Alertmanager HA](https://prometheus.io/docs/alerting/latest/high_availability/)).

Best fit: low traffic, one operational team, tolerance for per-signal telemetry
gaps, and a desire to learn the complete observability workflow before learning
distributed backend internals.

## Architecture B: local ingest plus durable object-store metrics

Architecture B keeps the same OTel, Loki, Tempo, Grafana, SLO, and alerting
planes, but changes metrics to either:

- two Prometheus replicas with Thanos sidecars, Thanos Query, Store Gateway, and
  singleton Compactor; or
- Prometheus/agent remote-write into monolithic Mimir, later decomposable into
  Mimir microservices.

Thanos retains Prometheus pull and local rule semantics while uploading two-hour
TSDB blocks to object storage. The sidecar does not make Prometheus stateless:
loss before block upload can lose roughly two hours, so Prometheus still needs a
PV. Thanos Query can deduplicate HA replicas
([Thanos sidecar](https://thanos.io/tip/components/sidecar.md/)). Its Compactor is
a singleton for a block stream and needs substantial temporary disk relative to
the blocks it compacts
([Thanos Compactor](https://thanos.io/tip/components/compact.md/)).

Mimir receives remote write and provides a unified, horizontally scalable
PromQL store. Its official capacity model shows why full microservices mode is
usually disproportionate at homelab scale: even at low traffic each mandatory
component still needs a schedulable replica, while the published compactor
planning point is 1 CPU, 4 GB memory, and 300 GB temporary disk per 20 million
active series. The same guide says to keep 50% spare memory and disk capacity
([Mimir capacity planning](https://grafana.com/docs/mimir/latest/manage/run-production-environment/planning-capacity/)).

Remote write is not an infinite safety queue. Prometheus reads it from the WAL;
if the remote endpoint is unavailable for more than about two hours, WAL
compaction can discard unsent samples. Prometheus reports roughly 25% typical
memory overhead, workload-dependent
([remote-write tuning](https://prometheus.io/docs/practices/remote_write/)).

Failure behavior: two Prometheus replicas maintain scraping/rules across a pod or
node loss, and object storage preserves historical blocks. Querying old data
depends on the object store and Store Gateway/Mimir read path. Alert deduplication
still belongs in Alertmanager. Thanos/Mimir component redundancy on VMs sharing
one physical Proxmox host protects from process/VM failure, not host failure.

Best fit: long metric retention, HA scrape/rule evaluation, future multi-cluster
querying, or a deliberate goal to learn distributed metrics architecture.

## Architecture C: fully distributed LGTM-style backends

Use OTel node agents plus at least two gateways, Mimir microservices for metrics,
Loki microservices for logs, Tempo microservices for traces, Pyroscope v2
microservices for profiles, object storage, caches, and Grafana.

This maximizes independent scaling and failure isolation but carries fixed costs:

- Tempo microservices mode now requires a Kafka-compatible durable queue. It
  isolates querier, block-builder, and live-store failures, while all components
  use object storage
  ([Tempo architecture](https://grafana.com/docs/tempo/latest/introduction/architecture/)).
- Loki microservices mode separates distributor, ingester, query, index gateway,
  compactor, ruler, and scheduling components. Grafana documents it for very
  large deployments; its smallest published distributed sizing tier (less than
  3 TB/day) already totals tens of CPU cores and GiBs of memory, demonstrating
  that the table is not a small-cluster minimum
  ([Loki sizing](https://grafana.com/docs/loki/latest/setup/size/)).
- Pyroscope v2 writes data directly to object storage, but its distributed mode
  adds a persistent Raft metastore; local filesystem is only suitable for its
  single-node mode
  ([Pyroscope v2 deployment](https://grafana.com/docs/pyroscope/latest/reference-pyroscope-v2-architecture/deployment-modes/)).

Failure behavior: properly replicated components tolerate individual pod and VM
losses; Kafka and object storage become shared dependencies. Losing the single
physical host still loses every in-host replica. More components also create a
larger bootstrap paradox: the observability system needs independent health
checks and external notifications to detect its own total failure.

Best fit: materially higher ingest/query load, multiple physical failure domains,
or an explicit learning requirement to operate distributed observability and
Kafka. It is not justified merely by the label “production.”

## Compatibility alternatives and overlap

| Capability | Compatible alternatives | Important overlap or boundary |
|---|---|---|
| Collection | OTel Collector, Grafana Alloy | Choose one node log tailer/host collector path. OTel APIs/OTLP preserve backend portability. |
| Metrics | Prometheus local, Prometheus + Thanos, Mimir | All expose PromQL-like workflows; deploying Thanos and Mimir together usually duplicates long-term metrics storage. |
| Logs | Loki, OpenSearch | Loki indexes labels and stores compressed chunks; OpenSearch provides full-text indexing with a larger JVM/storage footprint. A single primary log store avoids duplicate ingestion. |
| Traces | Tempo, Jaeger | Both accept OTel. Tempo emphasizes object storage and Grafana correlation; Jaeger is a CNCF tracing backend. Do not dual-store except during migration/evaluation. |
| Profiles | Pyroscope, Parca | Profiles are optional and OTel profile transport is Alpha. Backend-native agents may currently be more mature than an all-OTel profile path. |
| SLOs | Prometheus rules by hand, Pyrra, Sloth | These generate/organize rules over the same metrics; use one source of truth. |
| Alert routing | Alertmanager, Grafana Alerting | Avoid two independent owners for the same page. Grafana may visualize alerts while Alertmanager remains the routing/deduplication authority. |

The product names do not replace an operating model. Dashboards, rules, SLO CRs,
Collector pipelines, retention, and notification routing should all be GitOps
configuration; backend data should not be committed to Git.

## Realistic small-cluster planning envelopes

### Explicit workload assumptions

- four Kubernetes nodes and 20-50 application/platform pods;
- 10,000-30,000 active metric series at a 30-second interval;
- 1-5 GB/day of uncompressed application and platform logs after dropping noisy
  debug/audit streams according to policy;
- 25-100 spans/second after head or tail sampling, average encoded span assumed
  at 0.5-1 KB;
- fewer than 10 concurrent dashboard users and light ad-hoc queries;
- 30 days metrics, 14 days logs, 7 days traces, and 7 days profiles initially;
- object-storage capacity is counted separately from pod-local scratch/PVs.

Measure actual `prometheus_tsdb_head_series`, samples/second, log bytes/day,
spans/second, query concurrency, and compression after a 2-4 week burn-in, then
replace every estimate.

### Capacity arithmetic

Prometheus documents an average 1-2 bytes per sample and the formula `retention
seconds * samples/second * bytes/sample`. At 10k-30k series / 30 seconds, 30 days
of compacted samples is about 0.9-5.2 GB. WAL, head chunks, indexes, compaction,
and safety margin make **15-40 GB local PV per Prometheus replica** a reasonable
initial allocation. Prometheus advises setting size retention to at most 80-85%
of allocated disk ([Prometheus storage](https://prometheus.io/docs/prometheus/latest/storage/)).

At 25-100 spans/s and 0.5-1 KB/span, seven raw days are roughly 7.6-60.5 GB before
backend encoding, indexes, generated metrics, or replication. At 1-5 GB/day raw
logs, fourteen raw days are 14-70 GB. Because real compression depends strongly
on content and labels, set retention both by time and capacity alerting rather
than assuming a compression ratio.

### Estimated requests and storage by architecture

These are starting envelopes for the assumptions above, with limits and burst
headroom tuned after measurement:

| Plane | Architecture A | Architecture B | Architecture C |
|---|---:|---:|---:|
| OTel node agents (4 total) | 0.4-1 CPU, 0.5-1.5 GiB | same | same |
| OTel gateways | 0.25-0.5 CPU, 0.5-1 GiB (1-2 pods) | 0.5-1 CPU, 1-2 GiB (2 pods) | 1-2 CPU, 2-4 GiB |
| Metrics + rules | 0.5-1.5 CPU, 2-4 GiB, 15-40 GB PV | 2-5 CPU, 5-12 GiB, 30-80 GB PV plus object store | 4-10 CPU, 12-30 GiB plus object store/scratch |
| Logs | 0.5-1.5 CPU, 1-3 GiB, 30-100 GB/object | 1-3 CPU, 3-8 GiB, object store | 8+ CPU, 20+ GiB, object store/caches |
| Traces | 0.25-1 CPU, 1-3 GiB, 15-100 GB/object | same or 2 replicas | 6+ CPU, 12+ GiB plus Kafka and object store |
| Grafana + Alertmanager + SLO controller | 0.4-1 CPU, 0.8-2 GiB | 0.8-2 CPU, 1.5-4 GiB | 1-3 CPU, 3-8 GiB |
| Profiling, optional | 0.25-1 CPU, 0.5-2 GiB, 10-30 GB/object | same | 3+ CPU, 6+ GiB plus metastore/object store |
| **Estimated steady total** | **2.5-7.5 CPU, 6-16.5 GiB** | **5-13 CPU, 12-30.5 GiB** | **23+ CPU, 56+ GiB**, plus Kafka |

Architecture C's floor is dominated by replica and component count, not the
assumed ingest rate. Official distributed sizing tables are calibrated for much
larger loads, so its numbers should be validated with chart rendering and a
prototype rather than treated as vendor minima.

## Retention and durable-storage implications

- **Metrics:** local Prometheus is simplest but non-replicated. Thanos adds
  object-store durability in two-hour blocks; Mimir adds remote-write ingestion
  and distributed query. Neither removes the need to monitor ingestion lag.
- **Logs:** use Loki TSDB index and Compactor-managed retention. Do not apply an
  unscoped bucket lifecycle rule: Loki warns it can delete index or cluster-state
  objects and corrupt queries
  ([Loki retention](https://grafana.com/docs/loki/latest/operations/storage/retention/)).
- **Traces:** object storage is the production-oriented backend for Tempo. Local
  storage is suitable for development/testing, and monolithic write durability
  has no Kafka buffer.
- **Profiles:** treat as optional until a concrete performance question and
  ingestion budget exist. OTel profiles are Alpha, while Pyroscope's own object
  storage path is production-oriented.
- **NAS:** do not place Prometheus TSDB on NFS. An S3-compatible service may use
  NAS-backed disks if its own durability and failure behavior are understood,
  but that remains in the same physical host failure domain unless replicated
  off-host.
- **Off-host:** export irreplaceable configuration and any history whose loss
  violates recovery objectives to AWS/object storage outside the Proxmox host.
  Observability history is usually lower criticality than PostgreSQL data, so
  retention tiering should reflect that.

## Decisions this research enables, but does not make

1. Is recent telemetry loss during a backend/pod failure acceptable, or must
   scrape, rule, and ingest paths survive an individual Kubernetes node loss?
2. Is long-term object-store metrics history required now, and if so is the
   desired learning model Thanos sidecars or Mimir remote write?
3. Should the platform operate an S3-compatible store locally, use AWS S3
   directly, or use a local cache plus off-host copy?
4. What measured per-signal ingest budgets and initial retention periods are
   acceptable?
5. Is profiling a day-one platform signal or an on-demand capability?
6. Does the learning goal justify running distributed Loki/Tempo/Mimir and Kafka
   before workload scale requires them?
7. Which one system owns SLO definitions and which one owns notification routing?

Those choices determine final replica counts, placement, disruption budgets,
storage classes, and the observability share of the cluster resource budget.
