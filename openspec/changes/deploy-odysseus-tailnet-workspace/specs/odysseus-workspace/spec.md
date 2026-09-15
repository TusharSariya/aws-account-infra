## Purpose
Provide a privately reachable AI workspace and named CPU model API with reproducible infrastructure and independently recoverable application data.

## ADDED Requirements

### Requirement: Private authenticated workspace and model API
The service SHALL expose Odysseus and its model API over trusted HTTPS exclusively through Tailscale. Workspace authentication MUST remain enabled and internal storage/search services MUST not be exposed externally.
#### Scenario: Authorized tailnet access
- **WHEN** a tailnet client visits the workspace
- **THEN** it receives a trusted HTTPS login and can authenticate with the configured account
#### Scenario: Internal dependency access
- **WHEN** a client enumerates published services
- **THEN** only the workspace and model API are published, with no Funnel or database endpoint

### Requirement: Interactive model lifecycle
The operator SHALL download, list, select and explicitly remove models through the UI/API without editing Terraform. Downloaded weights MUST persist separately from loaded inference memory. Normal infrastructure deployment MUST not upgrade or remove models.
#### Scenario: Switch models
- **WHEN** a request selects a different downloaded model
- **THEN** inference uses that model with at most one model loaded and one inference request processed concurrently
#### Scenario: Download during normal service operation
- **WHEN** a large model is downloading
- **THEN** the workspace remains available and the transfer is not tied to deployment startup timeout

### Requirement: Bounded CPU operation
The initial service MUST operate on the existing x86 worker without GPU resources. Compatibility MUST be demonstrated on its AVX-only CPU before large-model acceptance. Initial context SHALL be 4096 tokens with a five-minute idle unload.
#### Scenario: CPU compatibility gate
- **WHEN** a candidate runtime is installed
- **THEN** a small-model inference test precedes sequential Qwen3.8 27B and Gemma4 31B tests, with speed and memory observations recorded

### Requirement: Reproducible private deployment
Images and upstream source MUST be pinned immutably. Infrastructure changes SHALL follow reviewed OpenTofu/Helm plans and applies, normally through GitHub CI. Explicitly authorized local execution during a CI outage MUST retain the same backend and saved-plan safeguards, identify its evidence as local and preserve required GitHub merge checks. Credentials MUST not be embedded in Git, image layers, plan output or Terraform state. Workspace agents MUST not receive host mounts, container runtime sockets or cluster administrator credentials.
#### Scenario: Clean rebuild
- **WHEN** the operator deploys from the recorded revision and restores separately held credentials
- **THEN** the reviewed execution path installs the same declared service images, resource limits, storage and private endpoints

### Requirement: Persistent data and honest recovery
The system SHALL retain models and workspace data across pod replacement and provide an encrypted application-consistent backup and isolated restore procedure. Model inventory SHALL include names and digests; reconstruction MUST reject changed or missing upstream models rather than silently substituting them. Persistent storage alone MUST not be claimed as a backup.
#### Scenario: Pod replacement
- **WHEN** an application pod is replaced
- **THEN** settings and data remain available from its original retained volume
#### Scenario: Independent recovery
- **WHEN** a saved backup is restored into an isolated test deployment
- **THEN** workspace and vector data can be verified without modifying production, and absent external credentials or model versions are reported explicitly

### Requirement: On-demand workspace operation
The workspace SHALL follow the shared homelab workload lifecycle contract. The migrated AI stack MUST default to off and run as one Pod reserving 35.75 CPU and 77 GiB RAM across Ollama, Odysseus, Chroma and Searx, including Ollama at 34 CPU and 64 GiB. CI MUST preserve intentional shutdown. Model unload alone MUST not be treated as service shutdown or proof of inactivity.

#### Scenario: Requested startup
- **WHEN** the operator starts AI and storage checks pass
- **THEN** the complete Pod is admitted together when its aggregate resources fit, with retained application data

#### Scenario: Graceful shutdown
- **WHEN** the operator stops AI
- **THEN** admission closes and active streams, downloads, document processing and background work drain before shutdown; unknown activity blocks normal shutdown

#### Scenario: Configured automatic shutdown
- **WHEN** every activity source confirms continuous inactivity for the configured service idle timeout
- **THEN** the aggregate AI Pod shuts down normally; the default is 1800 seconds and the current reviewed homelab setting is 300 seconds
- **AND** model-memory unload alone does not satisfy service shutdown, and unknown activity or controller recovery resets the verified interval
