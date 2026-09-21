# Kubernetes validation kv-c602f4cdb9325e36

Status: **passed**

| Scenario | Result | Evidence / prerequisite |
|---|---|---|
| preflight | passed | Assertions passed |
| smoke | passed | Assertions passed |
| cleanup-smoke | passed | Assertions passed |
| load-bursts | passed | Assertions passed |
| cleanup-load-bursts | passed | Assertions passed |
| load-sustained | passed | Assertions passed |
| cleanup-load-sustained | passed | Assertions passed |
| final-cleanup | passed | Assertions passed |
| physical-scale-to-zero | deferred | Migrate host services and approve physical shutdown https://github.com/TusharSariyaOrg/aws-account-infra/issues/113 |
| generalized-two-host-lifecycle | deferred | Generalized secondary lifecycle and cold resume adapter https://github.com/TusharSariyaOrg/aws-account-infra/issues/113 |
| ci-demand | deferred | Approved CI demand integration on always-on capacity https://github.com/TusharSariyaOrg/aws-account-infra/issues/97 |
| scheduled-demand | deferred | Approved schedule/deadline demand adapter https://github.com/TusharSariyaOrg/aws-account-infra/issues/113 |
| app-url-demand | deferred | Approved URL wake adapter and application readiness contract https://github.com/TusharSariyaOrg/aws-account-infra/issues/41 |
| application-policy | deferred | General application policy API beyond prototype annotations https://github.com/TusharSariyaOrg/aws-account-infra/issues/113 |
| automatic-consolidation | deferred | Approved automatic candidate selection and policy enforcement https://github.com/TusharSariyaOrg/aws-account-infra/issues/113 |
| cross-host-stateful | deferred | CSI storage ownership and cross-host topology support https://github.com/TusharSariyaOrg/aws-account-infra/issues/113 |
| worker-recreation-storage | deferred | Disposable class and supported lifecycle/reattachment path https://github.com/TusharSariyaOrg/aws-account-infra/issues/113 |
| production-budgets | deferred | Measured headroom and approved production quotas https://github.com/TusharSariyaOrg/aws-account-infra/issues/100 |
| performance-gates | deferred | Representative baselines and reviewed latency/throughput thresholds https://github.com/TusharSariyaOrg/aws-account-infra/issues/113 |
| larger-stress | deferred | Separately approved stress budgets and isolated target https://github.com/TusharSariyaOrg/aws-account-infra/issues/113 |
| upstream-conformance | deferred | Pinned upstream conformance suite and isolated target https://github.com/TusharSariyaOrg/aws-account-infra/issues/113 |
| backup-restore | deferred | Separate approval to resume deferred durability programme (#39) https://github.com/TusharSariyaOrg/aws-account-infra/issues/39 |
| outage-redundancy | deferred | Separately approved hardware/provider outage and redundancy scenarios https://github.com/TusharSariyaOrg/aws-account-infra/issues/113 |

Timing distributions (seconds; polling observations, no performance gate):

```json
{
  "load-bursts": {
    "nodes_ready_from_first_seen": {
      "count": 1,
      "min": 0.0,
      "p50": 0.0,
      "p95": 0.0,
      "max": 0.0
    },
    "pods_ready_from_first_seen": {
      "count": 28,
      "min": 0.0,
      "p50": 0.0,
      "p95": 6.903063798992662,
      "max": 7.491633540979819
    },
    "workloads_admitted_from_first_seen": {
      "count": 28,
      "min": 0.0,
      "p50": 0.0,
      "p95": 123.98865245198249,
      "max": 123.98865245198249
    },
    "jobs_complete_from_first_seen": {
      "count": 28,
      "min": 36.09283638198394,
      "p50": 43.29193690800457,
      "p95": 159.44443226300064,
      "max": 159.44443226300064
    },
    "completed_jobs": 28,
    "jobs_per_second": 0.08786688678345891,
    "nodes_creation_to_ready": {
      "count": 1,
      "min": 62451.0,
      "p50": 62451.0,
      "p95": 62451.0,
      "max": 62451.0
    },
    "jobs_creation_to_complete": {
      "count": 28,
      "min": 40.0,
      "p50": 46.0,
      "p95": 161.0,
      "max": 161.0
    },
    "workloads_creation_to_admitted": {
      "count": 28,
      "min": 2.0,
      "p50": 5.0,
      "p95": 122.0,
      "max": 122.0
    },
    "pods_creation_to_ready": {
      "count": 28,
      "min": 1.0,
      "p50": 2.0,
      "p95": 3.0,
      "max": 3.0
    }
  },
  "load-sustained": {
    "nodes_ready_from_first_seen": {
      "count": 1,
      "min": 0.0,
      "p50": 0.0,
      "p95": 0.0,
      "max": 0.0
    },
    "pods_ready_from_first_seen": {
      "count": 4,
      "min": 0.0,
      "p50": 0.0,
      "p95": 0.0,
      "max": 0.0
    },
    "workloads_admitted_from_first_seen": {
      "count": 4,
      "min": 0.0,
      "p50": 0.0,
      "p95": 0.0,
      "max": 0.0
    },
    "jobs_complete_from_first_seen": {
      "count": 4,
      "min": 604.522391157021,
      "p50": 611.4636952990259,
      "p95": 611.4636952990259,
      "max": 611.4636952990259
    },
    "completed_jobs": 4,
    "jobs_per_second": 0.006476373022999868,
    "nodes_creation_to_ready": {
      "count": 1,
      "min": 62451.0,
      "p50": 62451.0,
      "p95": 62451.0,
      "max": 62451.0
    },
    "jobs_creation_to_complete": {
      "count": 4,
      "min": 608.0,
      "p50": 609.0,
      "p95": 610.0,
      "max": 610.0
    },
    "workloads_creation_to_admitted": {
      "count": 4,
      "min": 1.0,
      "p50": 1.0,
      "p95": 2.0,
      "max": 2.0
    },
    "pods_creation_to_ready": {
      "count": 4,
      "min": 1.0,
      "p50": 2.0,
      "p95": 2.0,
      "max": 2.0
    }
  },
  "smoke": {
    "nodes_ready_from_first_seen": {
      "count": 1,
      "min": 0.0,
      "p50": 0.0,
      "p95": 0.0,
      "max": 0.0
    },
    "pods_ready_from_first_seen": {
      "count": 1,
      "min": 0.0,
      "p50": 0.0,
      "p95": 0.0,
      "max": 0.0
    },
    "workloads_admitted_from_first_seen": {
      "count": 1,
      "min": 6.133428443019511,
      "p50": 6.133428443019511,
      "p95": 6.133428443019511,
      "max": 6.133428443019511
    },
    "jobs_complete_from_first_seen": {
      "count": 1,
      "min": 13.545241396001074,
      "p50": 13.545241396001074,
      "p95": 13.545241396001074,
      "max": 13.545241396001074
    },
    "completed_jobs": 1,
    "jobs_per_second": 0.07382666508219096,
    "jobs_creation_to_complete": {
      "count": 1,
      "min": 10.0,
      "p50": 10.0,
      "p95": 10.0,
      "max": 10.0
    },
    "workloads_creation_to_admitted": {
      "count": 1,
      "min": 1.0,
      "p50": 1.0,
      "p95": 1.0,
      "max": 1.0
    },
    "nodes_creation_to_ready": {
      "count": 1,
      "min": 62451.0,
      "p50": 62451.0,
      "p95": 62451.0,
      "max": 62451.0
    },
    "pods_creation_to_ready": {
      "count": 1,
      "min": 1.0,
      "p50": 1.0,
      "p95": 1.0,
      "max": 1.0
    }
  }
}
```

Raw observations: events.jsonl. Kube-burner configurations and logs are retained alongside this report.
