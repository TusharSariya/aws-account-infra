# Kubernetes validation kv-809514277e12c61f

Status: **incomplete**

| Scenario | Result | Evidence / prerequisite |
|---|---|---|
| preflight | passed | Assertions passed |
| smoke | passed | Assertions passed |
| cleanup-smoke | passed | Assertions passed |
| load-bursts | failed | TimeoutError: Admission after usable capacity: kv-809514277e12c61f-burst-1-6 |
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
    "workloads_admitted_from_first_seen": {
      "count": 14,
      "min": 0.0,
      "p50": 50.57449006501702,
      "p95": 104.16931208100868,
      "max": 104.16931208100868
    },
    "pods_ready_from_first_seen": {
      "count": 14,
      "min": 0.0,
      "p50": 0.0,
      "p95": 4.456578738987446,
      "max": 4.456578738987446
    },
    "jobs_complete_from_first_seen": {
      "count": 14,
      "min": 40.85141702700639,
      "p50": 85.78137754902127,
      "p95": 145.18628855701536,
      "max": 145.18628855701536
    },
    "completed_jobs": 14,
    "jobs_per_second": 0.08515255491261647,
    "nodes_creation_to_ready": {
      "count": 1,
      "min": 62451.0,
      "p50": 62451.0,
      "p95": 62451.0,
      "max": 62451.0
    },
    "jobs_creation_to_complete": {
      "count": 14,
      "min": 43.0,
      "p50": 88.0,
      "p95": 146.0,
      "max": 146.0
    },
    "workloads_creation_to_admitted": {
      "count": 14,
      "min": 3.0,
      "p50": 50.0,
      "p95": 107.0,
      "max": 107.0
    },
    "pods_creation_to_ready": {
      "count": 14,
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
      "min": 4.030081486998824,
      "p50": 4.030081486998824,
      "p95": 4.030081486998824,
      "max": 4.030081486998824
    },
    "jobs_complete_from_first_seen": {
      "count": 1,
      "min": 12.07269356699544,
      "p50": 12.07269356699544,
      "p95": 12.07269356699544,
      "max": 12.07269356699544
    },
    "completed_jobs": 1,
    "jobs_per_second": 0.08283155655783553,
    "jobs_creation_to_complete": {
      "count": 1,
      "min": 11.0,
      "p50": 11.0,
      "p95": 11.0,
      "max": 11.0
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
