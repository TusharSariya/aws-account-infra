# SDK factory

OpenAPI Generator targets for specs under [`specs/`](../specs/). Never edit
`generated/` — it is gitignored and rebuilt in CI.

```bash
./scripts/sdk-generate.sh upace python
./scripts/sdk-generate.sh upace typescript-fetch
```

Image pin: `openapitools/openapi-generator-cli:v7.24.0` (digest in
[`openapitools.json`](openapitools.json) and the workflows).

Generated clients are vendored directly into application deployment artifacts during
the pilot. CodeArtifact publishing is retained only for the existing staging account
until its old state is retired; new vended accounts do not depend on it.

The historical publishing workflows used these repositories:

| Repository | When | Version |
| --- | --- | --- |
| `sdk-candidate` | every PR | `{info.version}.dev{run}+pr{n}` (Python) / `{info.version}-pr.{n}.{run}` (npm) |
| `sdk-stable` | label `publish-stable` + GitHub Environment `sdk` | `info.version` |

Promote is apply-before-merge (same shape as tofu `apply` + `prod`). Do not
reuse those names — they mean AdministratorAccess. After `sdk-stable` publish
succeeds, the workflow enables squash auto-merge.

Create GitHub Environment `sdk` once (OIDC trust is `environment:sdk`).
Required-reviewer rules need a GitHub plan that supports environment
protection; this org's plan does not, so the promote gate is the
`publish-stable` label plus the environment-pinned IAM role. Enable GitHub
Pages with source **GitHub Actions**.

First PR that creates the CodeArtifact domain: add label `apply` and wait for
the account unit, then add `publish-stable` and approve Environment `sdk`.

```bash
aws codeartifact login --tool pip --domain aws-account-infra --domain-owner 992382747916 \
  --repository sdk-candidate --region us-east-1
pip install upace --extra-index-url https://pypi.org/simple
```

Swap `sdk-candidate` for `sdk-stable` for production consumers. Candidate is
not an upstream of stable.
