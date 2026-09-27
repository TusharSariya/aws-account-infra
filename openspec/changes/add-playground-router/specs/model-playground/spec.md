## ADDED Requirements

### Requirement: Router presents the Ollama API
The playground router SHALL present the Ollama API to the UI, proxy each request to the inference backend that holds the model, and require a bearer token from the UI and present the backend's own bearer token upstream.

#### Scenario: Unauthenticated request
- **WHEN** a request arrives without the router bearer
- **THEN** it is answered 401 and no backend is contacted

### Requirement: Fit rule before any backend call
For `/api/chat` and `/api/generate` the router SHALL resolve the requested context to a preset, apply the fit rule against the backend's budget and overhead, and refuse with one explanatory line naming the largest fitting preset, without contacting or waking the backend, unless the model's override flag is set.

#### Scenario: Oversized context
- **WHEN** a chat requests a context whose reserve does not fit the backend budget
- **THEN** the stream contains a single done message with the refusal line and the backend receives no request

#### Scenario: Missing context
- **WHEN** a chat carries no `num_ctx`
- **THEN** the forwarded request uses the 8192 preset, or the native maximum when smaller

### Requirement: Wake progress in the stream
When the chosen backend is cold, the router SHALL trigger the wake through the backend's gateway and stream `[waking] <stage>` progress lines in the Ollama response shape until the gateway proxies, then `[waking] model loading` lines while the forwarded request is silent, then the backend's own stream; after the wake cap it SHALL end the stream with one line naming the stage reached.

#### Scenario: Cold backend
- **WHEN** a chat targets a backend whose gateway answers 503
- **THEN** the client receives progress chunks, then `[waking] ready`, then the answer, in one HTTP response

### Requirement: Catalog from pulls
A successful `/api/pull` SHALL record the model's technical facts derived from the backend's `/api/show` and its copy digest, and `/api/tags` SHALL merge awake backends' lists with catalog copies of asleep backends marked offline.

#### Scenario: Pull then list
- **WHEN** a model is pulled to a backend
- **THEN** the catalog holds its weight, native context, bytes per token and fixed cache, and the merged list shows the backend that holds it
