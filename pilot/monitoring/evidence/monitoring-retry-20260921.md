# Kubernetes validation kv-d151ad813cb294db

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
      "p95": 5.934211690007942,
      "max": 6.6218198419956025
    },
    "workloads_admitted_from_first_seen": {
      "count": 28,
      "min": 0.0,
      "p50": 38.30230042000767,
      "p95": 118.81602168999962,
      "max": 118.81602168999962
    },
    "jobs_complete_from_first_seen": {
      "count": 28,
      "min": 38.30230042000767,
      "p50": 75.35490459401626,
      "p95": 160.76082076801686,
      "max": 160.76082076801686
    },
    "completed_jobs": 28,
    "jobs_per_second": 0.08891737697712725,
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
      "p50": 77.0,
      "p95": 161.0,
      "max": 163.0
    },
    "workloads_creation_to_admitted": {
      "count": 28,
      "min": 1.0,
      "p50": 39.0,
      "p95": 120.0,
      "max": 123.0
    },
    "pods_creation_to_ready": {
      "count": 28,
      "min": 1.0,
      "p50": 2.0,
      "p95": 2.0,
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
      "p50": 6.192246426013298,
      "p95": 6.192246426013298,
      "max": 6.192246426013298
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
      "min": 606.9009634010145,
      "p50": 606.9009634010145,
      "p95": 612.2140085959982,
      "max": 612.2140085959982
    },
    "completed_jobs": 4,
    "jobs_per_second": 0.006473715821225643,
    "nodes_creation_to_ready": {
      "count": 1,
      "min": 62451.0,
      "p50": 62451.0,
      "p95": 62451.0,
      "max": 62451.0
    },
    "jobs_creation_to_complete": {
      "count": 4,
      "min": 611.0,
      "p50": 611.0,
      "p95": 612.0,
      "max": 612.0
    },
    "workloads_creation_to_admitted": {
      "count": 4,
      "min": 2.0,
      "p50": 3.0,
      "p95": 4.0,
      "max": 4.0
    },
    "pods_creation_to_ready": {
      "count": 4,
      "min": 2.0,
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
      "min": 4.97293646199978,
      "p50": 4.97293646199978,
      "p95": 4.97293646199978,
      "max": 4.97293646199978
    },
    "jobs_complete_from_first_seen": {
      "count": 1,
      "min": 15.142515255982289,
      "p50": 15.142515255982289,
      "p95": 15.142515255982289,
      "max": 15.142515255982289
    },
    "completed_jobs": 1,
    "jobs_per_second": 0.06603922684541687,
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
