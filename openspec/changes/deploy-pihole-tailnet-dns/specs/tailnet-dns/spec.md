## ADDED Requirements
### Requirement: Declarative private DNS service
The system SHALL deploy one persistent Pi-hole instance through reviewed OpenTofu/Helm CI and expose DNS on TCP/UDP 53 and authenticated HTTPS administration only within the tailnet.
#### Scenario: Reproducible application deployment
- **WHEN** an approved CI apply runs
- **THEN** pinned releases and a retained worker volume are reconciled without replacing Talos identity or exposing credentials in state or logs
#### Scenario: Shared operator retention
- **WHEN** Pi-hole is removed
- **THEN** its shared Tailscale operator and unrelated services remain available
### Requirement: Optional client participation
Devices SHALL be able to opt out of Pi-hole DNS without disconnecting Tailscale, using native client DNS preferences.
#### Scenario: Independent bypass
- **WHEN** one client disables acceptance of Tailscale DNS
- **THEN** it uses its normal local resolver while another participating client remains filtered
#### Scenario: Server outage
- **WHEN** Pi-hole is unavailable and a client opts out
- **THEN** public DNS works through the local resolver and Tailscale IP connectivity remains available
### Requirement: Verified cutover and rollback
The operator SHALL verify DNS, private administration, persistence and client controls before relying on the service and preserve the previous tailnet DNS configuration.
#### Scenario: Rollback
- **WHEN** DNS cutover causes failures
- **THEN** the operator restores the recorded previous DNS configuration without changing the router
