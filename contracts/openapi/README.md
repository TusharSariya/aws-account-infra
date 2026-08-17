# OpenAPI contracts

Canonical HTTP API contracts live here. Root-level `specs/` is reserved for numbered
Spec Kit feature specifications; design notes remain under `docs/superpowers/specs/`.

| API | Contract | Notes |
| --- | --- | --- |
| Upace equipment | [`upace/openapi.yaml`](upace/openapi.yaml) | Reverse-engineered and unpublished. Do not publish wrappers to public PyPI or npm. |

`info.version` is the stable package version. Bump it in the PR that promotes to
CodeArtifact `sdk-stable`.

Lint with Spectral using [`.spectral.yaml`](.spectral.yaml). CI watches
`contracts/openapi/**`; generator configuration lives in [`sdk/`](../../sdk/), and
Swagger UI assets live in [`docs/api/`](../../docs/api/).
