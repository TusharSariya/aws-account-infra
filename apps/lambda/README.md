# Lambda zip functions

Python functions that do not need a container image. Layout is
`apps/lambda/python/<runtime>/<name>/`. GitHub Actions
(`.github/workflows/lambda-package.yml`) builds an arm64 zip, installs private
packages from CodeArtifact `sdk-stable`, and uploads an immutable git-sha object
to `lambda-releases` (`candidate/` on PRs, `stable/` on main). OpenTofu does not
retarget Lambda until `booker_api_zip_key` is a `stable/` key.

```bash
./scripts/lambda-package.sh python/3.12/court-booker
```
