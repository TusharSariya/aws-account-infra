# Retired staging network IPs

On 2026-09-24, imported and released these unattached Elastic IPs using OpenTofu:

- Ohio: `eipalloc-05b5c49d7b7a026e8` (`3.23.75.112`).
- Northern California: `eipalloc-0f210c67c611fcc76` (`13.56.147.42`).

Tags trace them to `excalidraw-tf/packages/backend/terraform/staging-multi-state/05-east-2-network`
and `04-west-1-network`. Neither allocation occurs in that project's available
local state or backups; its current local state contains LocalStack fixtures.
This dedicated retirement state avoids applying those obsolete full network roots.

Backend: `retired/network-ips/terraform.tfstate` in the existing state bucket.
The reviewed plan contained only these two deletions. AWS DescribeAddresses
returned empty results in both regions after apply. The remaining removed blocks
record retirement and cannot recreate the addresses. No original state was moved.
