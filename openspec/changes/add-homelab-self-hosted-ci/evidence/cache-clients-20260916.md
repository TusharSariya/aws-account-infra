# Cache client integration, 2026-09-16

The prerequisite image ran successful LocalStack and application-contract jobs on
fresh ARC Pods at source `57436364f89de69e7773d7ad2af247c003e6531f`.
`ci-runner-image-20260916.json` records observed Pod UIDs/image IDs and GitHub jobs.
The hosted admission plan failed its idle-runner guard while this batch was busy;
it requires a quiescent rerun, not removal of that guard.

Local Mac integration used empty npm/uv/Go client caches against the loopback
transport and a port-forward to Nexus. All three clients succeeded through Nexus
and through a deliberately unavailable-cache fixture. Go module and go.mod sums
matched on both paths. `cache-transport-local-20260916.json` records each response.
These are client integration receipts, not cold/warm runner measurements or Nexus
upstream-byte/cache-hit proof. Ubuntu noble-updates and noble-backports InRelease
reads also succeeded through the existing apt-ubuntu repository.

The transport spools complete responses in disposable scratch before serving them,
with two Nexus attempts then three upstream attempts. Package managers retain
signature/hash verification; complete content is never retried by the transport
because a package integrity verifier rejected it. Caller authorization headers and
write methods are not forwarded. Native package-manager retries are disabled in
the Talos-only setup. No hosted or Mac bootstrap defaults are changed.

A local fresh BuildKit instance successfully exported a disposable cache to the
hosted Docker repository using its separate writer. Options were mode=max,
oci-mediatypes=true,image-manifest=true,ignore-error=true. Another fresh builder
without credentials was denied both import and export (HTTP 401), while its OCI
build output succeeded with exit 0. Thus nonfatal denied upload was observed, but
anonymous cache reuse failed: hosted Docker forceBasicAuth was enabled. The
pending guarded configuration disables forced Basic authentication while retaining
anonymous read-only privileges and authenticated add/edit only for the separate
build-cache writer. Reuse must be repeated after deployment. No anonymous write
permission is added. Fixture: ci/acceptance-20260916/linux-amd64:cold.

The GitHub Actions secret NEXUS_BUILD_CACHE_PASSWORD contains only the existing
build-cache writer credential. It is consumed into a disposable Docker config
outside build contexts; administrators and release identities remain separate.

Pending at that point: deploy new repositories and Docker authentication setting
and bind cleanup policies (completed below). Still required: verify fresh Linux clients, nested
build clients and Docker pull fallback; capture whole-Pod sizing and upstream bytes;
complete all outstanding acceptance before global routing.

References used for implementation:
- https://docs.astral.sh/uv/reference/environment/
- https://docs.npmjs.com/using-npm/config/
- https://go.dev/ref/mod
- https://docs.docker.com/build/cache/backends/registry/
- https://docs.docker.com/build/buildkit/configure/

## Subsequent verification and deployment blocker

The Linux container APT test found the additional
`http://deb.debian.org/debian-security/` alias. Its routing regression test now
passes. The live Linux integration run remains failed/unverified; its rerun was
interrupted by loss of the private Proxmox/Talos route. Kubernetes API requests,
Tailscale ping to Proxmox, SSH by Tailscale IP and TCP 8006 failed while the Mac's
Tailscale netcheck still reported internet/DERP connectivity. No infrastructure
apply or global routing change was attempted during this outage. Host health,
Pi-hole and reservation cleanup cannot be asserted until access returns.

The stock BuildKit v0.32.2 image was pinned by its observed immutable digest. A
manifest-503 fixture made one cache and two upstream requests. A blob-503 fixture
made FOUR cache and EIGHT upstream requests because nested BuildKit retries
repeat the resolver's fallback sequence. See `buildkit-retry-20260916.json`.
Therefore stock BuildKit mirrors do NOT yet satisfy the strict retry requirement;
Docker fallback acceptance stays open. This failure must be repaired and retested,
not silently treated as the requested two/three-attempt policy.

New repository cleanup bindings still required after guarded deployment:
`raw-python-files` and `apt-git-core` use the 14-day dependency policy;
`raw-cilium` and `raw-tailscale` use the 30-day pinned-download policy.

The current outbound-log parser retains only sanitized host/path hashes and
explicitly rejects unrecognized fields or unknown payload lengths. Its live log
format and window coverage remain unverified. References:
https://support.sonatype.com/hc/en-us/articles/115015441707-How-to-Debug-Outbound-HTTP-Requests-in-Repository-3
and the pinned-version source must be reconciled before counting these bytes.

## Guarded deployment and readback at 16:12 UTC

Private connectivity recovered without a configuration change. Both Talos nodes
were Ready, Pi-hole DNS and HTTPS responded, and the ARC runner namespace was
empty before deployment. The root cause of the temporary private route failure
remains unresolved; no physical-host outage or reboot is inferred.

The fresh guarded CI-root plan changed only the cache release and homelab-talos
runner release. Apply succeeded and a new post-apply plan was empty.
`cache-deployment-20260916-04.json` preserves the capacity and plan receipt.
All four new repositories are online. Their cleanup policies were saved through
the supported Nexus UI and read back through REST.
`cache-settings-20260916-04.json` records bindings and the existing enabled daily
cleanup and later compaction schedules, both with previous successful executions.
This does not establish physical blob reclamation.

A newly created local BuildKit instance then imported the previously exported
Nexus OCI cache without credentials. COPY proof /proof was CACHED and its layer
was downloaded from Nexus. Anonymous manifest upload was denied and the build
still exited 0 with its OCI output. This repairs the anonymous-read failure above,
but is not a fresh ARC runner measurement or proof of bounded Docker retries.

Live Nexus outbound log shape was verified. Successful artifact GETs with known
Content-Length can be counted; several npm/Python metadata responses report -1.
The parser deliberately retains those as unknown rather than claiming zero
upstream bytes. Complete job upstream measurement remains open.

The corrected Debian-security route also passed a fresh local Linux arm64
container integration: signed APT indexes and PyYAML 6.0.3 installation succeeded
through Nexus. An earlier fixture omitted a trailing slash from its test cache
URL and consequently exercised successful upstream fallback instead; it is kept
as such, not counted as Nexus reuse. Both receipts are retained in
`cache-linux-local-20260916.json`. User reported no known host/network changes
during the private-route interruption.
