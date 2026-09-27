## Why

With the runtime settings (change 1) and the router (change 2) in place, the playground needs its phone-facing half: Open WebUI behind the `wake-playground` gateway, with its data and the router's state in the application backup. This is what makes the goal true: pick up the phone and it works.

## What Changes

- Enable the Open WebUI Deployment in `homelab-playground`: retained data claim, Tailscale hostname `playground` through the wake gateway, login on, Ollama connection to the router with the router bearer, long client timeout for silent loads.
- Add the two playground claims (`playground-ui-data`, `playground-router-state`) to the AI data backup: snapshot and restore fixtures, archive volume list, backup scope and proof.
- Verify acceptance criteria 1 to 5 and 7 on the real hardware and record the evidence on the map.

## Capabilities

### Modified Capabilities

- `model-playground`: UI reachability, backup scope.
