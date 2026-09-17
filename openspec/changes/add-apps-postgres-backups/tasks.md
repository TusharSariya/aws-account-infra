## 1. Infrastructure and access

- [x] 1.1 Implement separate backup bucket, lifecycle, identity and alarms; verify OpenTofu mock tests and validation.
- [x] 1.2 Pin operator chart/images and implement single-primary Helm resources, network policy and capacity changes; verify Helm rendering and resource assertions.
- [x] 1.3 Implement secret delivery and onboarding; verify credentials cannot enter plans and schema isolation tests pass.

## 2. Backup and recovery

- [x] 2.1 Implement serialized archive/staging/promotion with checksums and alerts; verify failure-injection tests preserve latest.
- [x] 2.2 Implement exact-version disposable restore and documentation; verify archive/restore guards and permissions tests.
- [x] 2.3 Integrate immutable image builds, deployment filters and guarded plans; verify focused workflow tests and secret scans.

## 3. Deployment and acceptance

- [x] 3.1 Deploy AWS resources and enroll dedicated certificate; record live retention, denied deletion and alert evidence.
- [x] 3.2 Verify free storage and idle workloads, apply coordinated capacity/database changes; record saved-plan and deployment evidence.
- [x] 3.3 Verify concurrent app access, denied cross-schema and plaintext/network access, explicit shared grants and restart persistence using temporary apps.
- [x] 3.4 Inject backup failures and restore current/older versions into disposable instances; record data, ownership and grants evidence.
- [x] 3.5 Run strict OpenSpec validation and focused checks; record remaining limitations without marking unverified acceptance complete.
