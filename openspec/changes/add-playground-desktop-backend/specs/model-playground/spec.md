## ADDED Requirements

### Requirement: Backend selection by path prefix
The router SHALL serve each backend as its own Ollama API under the path prefix `/b/<backend>`, pinning chats, generates and pulls under that prefix to that backend and listing only that backend's copies in its `/api/tags`. The unprefixed root SHALL mean the default backend. Open WebUI SHALL have one connection per backend with a `prefix_id` equal to the backend name, and the router SHALL NOT move a request to another backend.

#### Scenario: Chat on a desktop model
- **WHEN** the owner picks `desktop.<model>` in the dropdown and sends a chat while the desktop is on
- **THEN** the router forwards it to the desktop backend only and the answer streams from there

#### Scenario: Pull to the desktop
- **WHEN** the owner pulls `hf.co/<org>/<repo>:Q4_K_M` choosing the `desktop` connection
- **THEN** the copy is pulled to and recorded for the desktop backend and lists as `desktop.<model>`, not under `server`

#### Scenario: Unprefixed request
- **WHEN** a client calls `/api/chat` at the root without a prefix
- **THEN** the router uses the default backend

### Requirement: Manual-power refusal
For a backend marked manual power, the router SHALL refuse a chat, generate or pull at once with "desktop is off, power it on and retry" when the backend does not answer, SHALL NOT call any wake gateway for it, and SHALL NOT fall back to another backend.

#### Scenario: Desktop off
- **WHEN** a chat or pull targets `/b/desktop` while the desktop is powered off
- **THEN** the router returns the refusal line immediately and sends nothing to the server backend

### Requirement: Pending delete on an asleep backend
Deleting a model SHALL delete every reachable copy and record copies on unreachable backends as pending. When a backend with a pending copy is next merged while awake, the router SHALL delete that copy instead of re-adding it to the catalog.

#### Scenario: Delete while the desktop is off
- **WHEN** the owner deletes a model held on both backends while the desktop is off
- **THEN** the server copy is deleted, the desktop copy is recorded as pending, and after the desktop is powered on the next tags merge deletes it and the model does not reappear

### Requirement: Desktop fit rule with partial offload
The fit rule SHALL apply unchanged to the desktop backend with its budget equal to the pod RAM limit plus VRAM minus headroom, and its overhead measured with a 27B model loaded at 8192 context. Until measured, the budget SHALL be 26 GiB and the overhead 2 GiB. Desktop wait stage lines SHALL come from the backend's running list (`/api/ps`) only.

#### Scenario: 27B at 8k on the desktop
- **WHEN** a chat asks a 27B Q4_K_M on the desktop for 8192 context and weights plus context reserve plus overhead are within the desktop budget
- **THEN** the router forwards it and the model loads with part of its layers on the GPU and the rest in RAM

#### Scenario: Context that does not fit the desktop
- **WHEN** the requested context pushes the total above the desktop budget
- **THEN** the router refuses with the one-line fit message naming the desktop budget and the largest preset that fits

### Requirement: Desktop never wakes the servers
The desktop Ollama SHALL take its quota from the `desktop-compute` ClusterQueue, which has no host-ready admission check, and SHALL tolerate only the `compute` taint. Desktop demand SHALL NOT wake or hold the server hosts, and lifting the quarantine taint SHALL remain an operator step after desktop acceptance.

#### Scenario: Desktop runtime waiting for quota
- **WHEN** the desktop Ollama is pending admission in `desktop-compute`
- **THEN** the coordinator does not power on or hold any server host

#### Scenario: Quarantined desktop
- **WHEN** the desktop still carries the quarantine taint
- **THEN** the desktop Ollama stays Pending and the playground's server models are unaffected
