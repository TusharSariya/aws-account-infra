## ADDED Requirements

### Requirement: Phone-reachable UI behind the wake gateway
The playground UI SHALL be reachable at the tailnet hostname `playground` through the `wake-playground` gateway, require login, and talk to the router with the router bearer.

#### Scenario: Cold tap
- **WHEN** the primary host is off and the phone opens the playground
- **THEN** the waking page is shown and refreshes until the app loads, within 15 minutes

### Requirement: Playground data in the application backup
The UI data claim and the router state claim SHALL be captured and restored by the AI data backup with the existing 24-hour loss bound.

#### Scenario: Restore proof
- **WHEN** the backup workflow runs
- **THEN** the isolated restore proof lists `playground-ui` and `playground-router` alongside models, workspace and vector
