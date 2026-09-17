## MODIFIED Requirements

### Requirement: Atomic AI resource admission
Ollama, Odysseus, Chroma and Searx SHALL share one schedulable Pod, with zero replicas off and one on. Their combined reservation MUST be 31.25 CPU and 77 GiB RAM, including Ollama at 29.5 CPU and 64 GiB. The shared AI/CI pool SHALL be 31.5 CPU / 144 GiB, with platform reserve 6 CPU / 24 GiB. Platform components MUST have separate budgets and VM CPU/RAM MUST remain unchanged. Deployment MUST NOT interrupt active AI/CI work to reclaim capacity.

#### Scenario: Insufficient capacity
- **WHEN** the aggregate reservation does not fit
- **THEN** the entire AI Pod remains Pending, no subset starts and Pi-hole continues serving DNS

#### Scenario: Active workload during rollout
- **WHEN** AI or CI work is still active
- **THEN** the capacity change waits without terminating that work
