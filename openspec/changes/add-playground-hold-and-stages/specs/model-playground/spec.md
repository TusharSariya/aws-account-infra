## ADDED Requirements

### Requirement: Owner hold
The owner SHALL be able to hold the playground awake from any tailnet device through a page on the wake gateway, and release it the same way. A hold SHALL keep the primary host and the runtime from stopping for idleness, SHALL be capped at 12 hours, and SHALL show its release time.

#### Scenario: Hold past the idle window
- **WHEN** the owner sets a hold and sends nothing for longer than the idle window
- **THEN** the runtime stays on and the host stays powered, and the page shows "held until" the cap

#### Scenario: Release
- **WHEN** the owner releases the hold or the cap passes
- **THEN** the runtime stops after the verified idle window and the host powers off after its own

### Requirement: Wait stage lines
While a chat waits for its first token the router SHALL name the sub-stage from cluster signals: `runtime starting` while the runtime pod is not ready, `loading weights` with memory progress while the model is absent from the backend's running list, and `processing prompt` with a token estimate once present. Typical durations SHALL come from measurements recorded per model from the backend's timing record, and the line SHALL say when none exists yet.

#### Scenario: Cold chat on a stopped runtime
- **WHEN** a chat arrives while the runtime is stopped
- **THEN** the stream shows `runtime starting`, then `loading weights, N of M GiB in memory`, then `processing prompt`, then the answer

#### Scenario: Second chat
- **WHEN** the same model is loaded again after a measured load
- **THEN** the loading line shows the measured typical for that model
