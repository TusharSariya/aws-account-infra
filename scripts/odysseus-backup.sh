#!/usr/bin/env bash
# Legacy replica-manipulating backup was retired with controller-owned runtime.
set -euo pipefail
printf 'Use the protected homelab-lifecycle-maintenance CI workflow. See docs/homelab-lifecycle.md for encrypted backup and isolated restore.\n' >&2
exit 2
