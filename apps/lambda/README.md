# Lambda zip functions

Python functions that do not need a container image. Layout is
`apps/lambda/python/<runtime>/<name>/`. GitHub Actions
(`.github/workflows/lambda-package.yml`) builds an arm64 zip, installs private
packages from CodeArtifact `sdk-stable`, and uploads an immutable git-sha object
to `lambda-releases` (`candidate/` on PRs, `stable/` on main). OpenTofu does not
retarget Lambda until `booker_api_zip_key` in
`config/environments/aws/staging/court-booker-api.tfvars` is a `stable/` key.

Packaging uses `uv` and the Lambda runtime is `python3.14`.

```bash
./scripts/lambda-package.sh python/3.14/court-booker
```
