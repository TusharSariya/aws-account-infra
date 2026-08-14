# ECR images

Each subdirectory is a container image. The directory name is the ECR repository
name. GitHub Actions (`.github/workflows/ecr-push.yml`) builds `linux/arm64` and
pushes an immutable git-sha tag. Lambda images must be built with
`--provenance=false` (attestation indexes are rejected).

```bash
./scripts/ecr-image.sh court-booker
```

Pushing an image does not retarget Lambda. Set `booker_image_tag` in
`config/environments/aws/staging.tfvars` and apply the court-booker unit.
