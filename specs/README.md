# OpenAPI specs

Canonical HTTP API contracts. Superpowers design notes live under
`docs/superpowers/specs/` and are not APIs.

| API | Spec | Notes |
| --- | --- | --- |
| Upace equipment | [`upace/openapi.yaml`](upace/openapi.yaml) | Reverse-engineered; unpublished. Do not publish wrappers to public PyPI/npm. |

`info.version` is the **stable** package version. Bump it in the PR that
promotes to CodeArtifact `sdk-stable`.

Lint: Spectral ([`.spectral.yaml`](.spectral.yaml)). CI is a required check on
`specs/**`. Generator config lives in [`sdk/`](../sdk/). Visual: GitHub Pages
Swagger UI from [`docs/api/`](../docs/api/).
