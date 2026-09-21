# Kubernetes validation kv-3d21ac677f9577fa

Status: **passed**

| Scenario | Result | Evidence / prerequisite |
|---|---|---|
| preflight | passed | Assertions passed |
| smoke | passed | Assertions passed |
| cleanup-smoke | passed | Assertions passed |
| load-bursts | passed | Assertions passed |
| cleanup-load-bursts | passed | Assertions passed |
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
      "p95": 4.969611217995407,
      "max": 4.969611217995407
    },
    "workloads_admitted_from_first_seen": {
      "count": 28,
      "min": 0.0,
      "p50": 0.0,
      "p95": 122.37867125699995,
      "max": 122.37867125699995
    },
    "jobs_complete_from_first_seen": {
      "count": 28,
      "min": 38.17570923399762,
      "p50": 44.792556437983876,
      "p95": 154.21859088199562,
      "max": 154.21859088199562
    },
    "completed_jobs": 28,
    "jobs_per_second": 0.09168991090235871,
    "nodes_creation_to_ready": {
      "count": 1,
      "min": 62451.0,
      "p50": 62451.0,
      "p95": 62451.0,
      "max": 62451.0
    },
    "jobs_creation_to_complete": {
      "count": 28,
      "min": 39.0,
      "p50": 45.0,
      "p95": 158.0,
      "max": 159.0
    },
    "workloads_creation_to_admitted": {
      "count": 28,
      "min": 2.0,
      "p50": 5.0,
      "p95": 121.0,
      "max": 122.0
    },
    "pods_creation_to_ready": {
      "count": 28,
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
      "min": 4.509439393994398,
      "p50": 4.509439393994398,
      "p95": 4.509439393994398,
      "max": 4.509439393994398
    },
    "jobs_complete_from_first_seen": {
      "count": 1,
      "min": 14.225380046002101,
      "p50": 14.225380046002101,
      "p95": 14.225380046002101,
      "max": 14.225380046002101
    },
    "completed_jobs": 1,
    "jobs_per_second": 0.07029689166589541,
    "jobs_creation_to_complete": {
      "count": 1,
      "min": 11.0,
      "p50": 11.0,
      "p95": 11.0,
      "max": 11.0
    },
    "workloads_creation_to_admitted": {
      "count": 1,
      "min": 2.0,
      "p50": 2.0,
      "p95": 2.0,
      "max": 2.0
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
