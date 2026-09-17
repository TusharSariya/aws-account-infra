# Disposable CI runner image

The image extends the existing checksum-pinned ARC runner with the recurring APT
prerequisites already requested by workflows and AWS CLI 2.36.45 at its existing
SHA-256. It records installed Debian package versions in `/opt/ci-packages.tsv`.
Node, Go and additional Python versions continue to use their workflow pins.

Build from a Mac or hosted Linux recovery environment with Docker available:

```sh
bash scripts/ci-runner-image.sh --load --tag homelab-ci-runner:verify
```

The build always downloads directly from the original upstreams and verifies the
AWS archive. Its temporary build context contains only the Dockerfile and the
checksum downloader. Docker credentials stay outside that context. The hosted
`ci-runner-image` workflow verifies the tools, publishes to private GHCR using its
job credential, checks private visibility and uploads the image manifest and
package inventory. Adopt only the observed immutable digest through a fresh
saved CI-root plan after runners become idle.

Runner image pulls use a separately enrolled `ghcr-read` imagePullSecret, never a
release or build-cache writer credential. Enrollment verifies the supplied token
has exactly `read:packages` scope. After the existing GitHub App enrollment creates
the ARC namespace, a private owned mode-0600 Docker configuration can be enrolled:

```sh
uv run --with PyYAML==6.0.3 python scripts/homelab-ci.py enroll-registry \
  --private /path/to/private-workspace --registry-json /path/to/private-registry.json
```

The file must contain only `auths.ghcr.io.auth` in Docker's Basic-auth encoding.
It must remain outside the checkout and build context. No credential enters
OpenTofu state or a runner environment/volume; Kubernetes uses the Secret only
for image pulls. The existing read-only GHCR credential can be reused when its
account has access to this private package. Keep the private source configuration
available for independent recovery when the cluster Secret is absent.

Cleanup previews, deployment receipts and remaining measured-sizing acceptance
are tracked in `openspec/changes/add-homelab-self-hosted-ci/`.
