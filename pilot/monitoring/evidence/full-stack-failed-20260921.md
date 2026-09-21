# Kubernetes validation kv-f603f635f952c698

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
      "p95": 7.362335900979815,
      "max": 7.362335900979815
    },
    "workloads_admitted_from_first_seen": {
      "count": 28,
      "min": 0.0,
      "p50": 0.0,
      "p95": 124.01291168801254,
      "max": 124.01291168801254
    },
    "jobs_complete_from_first_seen": {
      "count": 28,
      "min": 37.30050579502131,
      "p50": 42.51267717502196,
      "p95": 163.77525904402137,
      "max": 163.77525904402137
    },
    "completed_jobs": 28,
    "jobs_per_second": 0.0868010648227029,
    "nodes_creation_to_ready": {
      "count": 1,
      "min": 62451.0,
      "p50": 62451.0,
      "p95": 62451.0,
      "max": 62451.0
    },
    "jobs_creation_to_complete": {
      "count": 28,
      "min": 38.0,
      "p50": 48.0,
      "p95": 165.0,
      "max": 167.0
    },
    "workloads_creation_to_admitted": {
      "count": 28,
      "min": 2.0,
      "p50": 4.0,
      "p95": 126.0,
      "max": 126.0
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
      "min": 605.5508921149885,
      "p50": 605.5508921149885,
      "p95": 605.5508921149885,
      "max": 605.5508921149885
    },
    "completed_jobs": 4,
    "jobs_per_second": 0.006541415371429994,
    "nodes_creation_to_ready": {
      "count": 1,
      "min": 62451.0,
      "p50": 62451.0,
      "p95": 62451.0,
      "max": 62451.0
    },
    "jobs_creation_to_complete": {
      "count": 4,
      "min": 609.0,
      "p50": 610.0,
      "p95": 610.0,
      "max": 610.0
    },
    "workloads_creation_to_admitted": {
      "count": 4,
      "min": 1.0,
      "p50": 2.0,
      "p95": 2.0,
      "max": 2.0
    },
    "pods_creation_to_ready": {
      "count": 4,
      "min": 1.0,
      "p50": 2.0,
      "p95": 3.0,
      "max": 3.0
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
      "min": 5.8558175019861665,
      "p50": 5.8558175019861665,
      "p95": 5.8558175019861665,
      "max": 5.8558175019861665
    },
    "jobs_complete_from_first_seen": {
      "count": 1,
      "min": 17.652754699985962,
      "p50": 17.652754699985962,
      "p95": 17.652754699985962,
      "max": 17.652754699985962
    },
    "completed_jobs": 1,
    "jobs_per_second": 0.05664838247601068,
    "jobs_creation_to_complete": {
      "count": 1,
      "min": 12.0,
      "p50": 12.0,
      "p95": 12.0,
      "max": 12.0
    },
    "workloads_creation_to_admitted": {
      "count": 1,
      "min": 3.0,
      "p50": 3.0,
      "p95": 3.0,
      "max": 3.0
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
