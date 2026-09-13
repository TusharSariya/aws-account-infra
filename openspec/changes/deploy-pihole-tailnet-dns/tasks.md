## 1. Declarative deployment
- [x] 1.1 Add pinned Helm application root, retained storage and shared operator protection.
- [x] 1.2 Integrate application plan/apply, private credentials, secret exclusion and failure gates into existing CI.
- [x] 1.3 Add render/validation and deployment-selection tests plus operator/client runbook.
## 2. Rollout
- [ ] 2.1 Configure dedicated operator credentials and private application password, then deploy through reviewed CI.
- [ ] 2.2 Verify UDP/TCP allowed/blocked queries, private HTTPS authentication and persistence across pod replacement.
- [ ] 2.3 Configure tailnet DNS and verify laptop/desktop, remote access, independent bypass/re-enable and restored local DNS after disconnect.
- [ ] 2.4 Explicitly rehearse Pi-hole outage and DNS-settings rollback without disconnecting Tailscale; record evidence.

Implementation evidence: local chart render/safety/selection tests and strict OpenSpec validation passed. An authenticated application-root plan proposes only helm_release.pihole and helm_release.tailscale_operator creation. No application apply or DNS cutover has occurred. Deployment awaits the dedicated operator credential and protected Pi-hole password, followed by reviewed CI apply. Runtime/client tasks remain unchecked.

PR #64 apply run 34781721505 stopped at Proxmox preflight before any apply: disabling runner Tailscale DNS removed MagicDNS resolution. The correction resolves private HTTPS hosts through the Tailscale peer map while retaining hostname/certificate verification and DNS opt-out. Live Proxmox HTTPS verification, nine application regression tests and workflow lint passed. Application credentials are now checked before any deployment; rollout still requires the three protected prod secrets.

Initial credentialed rollout reached healthy operator, DNS proxy and Pi-hole pods. Runtime checks exposed an ingress HTTP/TLS hostname mismatch and an invalid expectation of LoadBalancer status on an annotated ClusterIP Service. Corrected the ingress rule to omit host matching, and discover DNS via the Tailscale peer map after the proxy readiness condition. Both failures have regression coverage (ten application tests pass); HTTPS and complete CI acceptance still await the corrected rollout.

Corrected rollout 34785814234 applied its exact saved plan successfully, then exposed CLI hostname fallback to OS DNS in endpoint verification. Peer resolution now reads tailscale status JSON directly, normalizes trailing dots and waits briefly for new peers. Eleven regression tests and the full live endpoint helper passed: DNS 100.82.190.54, UDP/TCP allowed and blocked queries, trusted https://pihole-admin.tail2f646b.ts.net/admin/ and unauthenticated API rejection. CI rerun and remaining persistence/client checks are still pending.
