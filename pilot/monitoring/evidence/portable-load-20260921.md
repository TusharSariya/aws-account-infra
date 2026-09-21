# Kubernetes validation kv-5583ebeeda6e94d9

Status: **incomplete**

| Scenario | Result | Evidence / prerequisite |
|---|---|---|
| preflight | passed | Assertions passed |
| smoke | passed | Assertions passed |
| cleanup-smoke | passed | Assertions passed |
| load-bursts | failed | TimeoutError: Admission after usable capacity: kv-5583ebeeda6e94d9-burst-3-11 |
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
      "count": 24,
      "min": 0.0,
      "p50": 0.0,
      "p95": 4.10449675199925,
      "max": 4.10449675199925
    },
    "workloads_admitted_from_first_seen": {
      "count": 24,
      "min": 3.9602345710154623,
      "p50": 7.118115624005441,
      "p95": 112.46928466297686,
      "max": 112.46928466297686
    },
    "jobs_complete_from_first_seen": {
      "count": 20,
      "min": 39.68337585602421,
      "p50": 45.75804464399698,
      "p95": 108.52938350802287,
      "max": 108.52938350802287
    },
    "completed_jobs": 20,
    "jobs_per_second": 0.06783552680967103,
    "nodes_creation_to_ready": {
      "count": 1,
      "min": 62451.0,
      "p50": 62451.0,
      "p95": 62451.0,
      "max": 62451.0
    },
    "jobs_creation_to_complete": {
      "count": 20,
      "min": 41.0,
      "p50": 44.0,
      "p95": 107.0,
      "max": 108.0
    },
    "workloads_creation_to_admitted": {
      "count": 24,
      "min": 4.0,
      "p50": 8.0,
      "p95": 112.0,
      "max": 112.0
    },
    "pods_creation_to_ready": {
      "count": 24,
      "min": 1.0,
      "p50": 1.0,
      "p95": 2.0,
      "max": 2.0
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
      "p95": 3.821873256994877,
      "max": 3.821873256994877
    },
    "workloads_admitted_from_first_seen": {
      "count": 4,
      "min": 3.9133507760125212,
      "p50": 3.9133507760125212,
      "p95": 3.9133507760125212,
      "max": 3.9133507760125212
    },
    "jobs_complete_from_first_seen": {
      "count": 4,
      "min": 612.2865690270264,
      "p50": 612.2865690270264,
      "p95": 616.1490255200188,
      "max": 616.1490255200188
    },
    "completed_jobs": 4,
    "jobs_per_second": 0.006453867885154097,
    "nodes_creation_to_ready": {
      "count": 1,
      "min": 62451.0,
      "p50": 62451.0,
      "p95": 62451.0,
      "max": 62451.0
    },
    "jobs_creation_to_complete": {
      "count": 4,
      "min": 615.0,
      "p50": 616.0,
      "p95": 617.0,
      "max": 617.0
    },
    "workloads_creation_to_admitted": {
      "count": 4,
      "min": 5.0,
      "p50": 5.0,
      "p95": 6.0,
      "max": 6.0
    },
    "pods_creation_to_ready": {
      "count": 4,
      "min": 1.0,
      "p50": 1.0,
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
      "min": 3.4597033050085884,
      "p50": 3.4597033050085884,
      "p95": 3.4597033050085884,
      "max": 3.4597033050085884
    },
    "jobs_complete_from_first_seen": {
      "count": 1,
      "min": 9.958347370004049,
      "p50": 9.958347370004049,
      "p95": 9.958347370004049,
      "max": 9.958347370004049
    },
    "completed_jobs": 1,
    "jobs_per_second": 0.1004182684982592,
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
