## 1. UI and backup

- [x] 1.1 Enable `ui` in `playground-values.yaml`; verify the Ingress points at `wake-playground` and the policy chain gateway to UI to router.
- [x] 1.2 Backup: extend `archive.py` VOLUMES, the `ai-maintenance` snapshot fixture mounts, `ai-data-backup.py` scope; tests updated.
- [x] 1.3 Deploy through the `apply` label; first sign-up from the phone; disable sign-up.
- [x] 1.4 Acceptance on hardware: cold tap loads the app within 15 min; cold chat streams stage lines then the answer; verified-idle stop and host off; hf.co pull, list, delete from the phone; oversized context refused (CI); both claims in the restore proof. Record on map #237.

Verified 2026-09-27 (PRs #263, #264, #265): first sign-up from the browser (one admin; sign-up switch-off left to the owner), cold chat streams stage lines then the answer (89 s on the 27B), verified-idle runtime stop observed, oversized context refused in CI. The owner dropped the cold tap from the phone (the web path is the phone path) and the hf.co delete check; the host power-off and the restore proof are tracked under change 4's tasks.
