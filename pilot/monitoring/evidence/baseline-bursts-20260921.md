# Kubernetes validation kv-b2d2bf3b955ebd75

Status: **incomplete**

| Scenario | Result | Evidence / prerequisite |
|---|---|---|
| preflight | passed | Assertions passed |
| smoke | passed | Assertions passed |
| cleanup-smoke | passed | Assertions passed |
| load-bursts | failed | TimeoutError: Admission after usable capacity: kv-b2d2bf3b955ebd75-burst-3-11 |
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
      "count": 27,
      "min": 0.0,
      "p50": 4.7438265410019085,
      "p95": 114.47929954499705,
      "max": 114.47929954499705
    },
    "pods_ready_from_first_seen": {
      "count": 27,
      "min": 0.0,
      "p50": 3.938390780996997,
      "p95": 4.467277529998682,
      "max": 4.467277529998682
    },
    "jobs_complete_from_first_seen": {
      "count": 27,
      "min": 37.99346898699878,
      "p50": 48.444200777012156,
      "p95": 154.3603397019906,
      "max": 154.3603397019906
    },
    "completed_jobs": 27,
    "jobs_per_second": 0.08092033393246177,
    "nodes_creation_to_ready": {
      "count": 1,
      "min": 62451.0,
      "p50": 62451.0,
      "p95": 62451.0,
      "max": 62451.0
    },
    "jobs_creation_to_complete": {
      "count": 27,
      "min": 41.0,
      "p50": 47.0,
      "p95": 153.0,
      "max": 154.0
    },
    "workloads_creation_to_admitted": {
      "count": 27,
      "min": 2.0,
      "p50": 7.0,
      "p95": 111.0,
      "max": 112.0
    },
    "pods_creation_to_ready": {
      "count": 27,
      "min": 1.0,
      "p50": 2.0,
      "p95": 5.0,
      "max": 6.0
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
      "min": 7.470430457993643,
      "p50": 7.470430457993643,
      "p95": 7.470430457993643,
      "max": 7.470430457993643
    },
    "jobs_complete_from_first_seen": {
      "count": 1,
      "min": 14.88647104499978,
      "p50": 14.88647104499978,
      "p95": 14.88647104499978,
      "max": 14.88647104499978
    },
    "completed_jobs": 1,
    "jobs_per_second": 0.06717508783492984,
    "jobs_creation_to_complete": {
      "count": 1,
      "min": 15.0,
      "p50": 15.0,
      "p95": 15.0,
      "max": 15.0
    },
    "workloads_creation_to_admitted": {
      "count": 1,
      "min": 6.0,
      "p50": 6.0,
      "p95": 6.0,
      "max": 6.0
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
