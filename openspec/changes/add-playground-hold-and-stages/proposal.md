## Why

The playground works end to end, but two things the owner hit on day one are missing. The host and the runtime each sleep after a fixed 5 minute idle window, with no way to say "I am still using this". And while a chat waits for its first token, the router shows one line, "model loading", for three different waits: the runtime restarting after an idle stop, the weights being read into memory (16.5 GB for a 27B model), and prompt processing at about 7.5 tokens per second on the CPU worker. Its "0:40 typical" is a constant from the 1B tests.

## What Changes

- A **hold** the owner sets from the phone: a page on the `wake-playground` gateway with Hold and Release. Hold writes the durable power-hold lease the coordinator already honours, capped at 12 hours; the gateway releases it when the cap passes. The lifecycle controller reads the same lease and does not stop the runtime while it is held. Nothing changes in the coordinator.
- **Wait stages** in the router: while the chat is silent it names the sub-stage from what the cluster shows: `runtime starting`, `loading weights, N of M GiB in memory`, `processing prompt, ~T tokens at R tok/s`. The "typical" figures come from the timing record Ollama sends with every answer, stored per model, instead of a constant.

## Capabilities

### Modified Capabilities

- `model-playground`: owner hold; wait stage lines and measured timings.
