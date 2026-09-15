# Homelab CI

The dedicated VM/nested-KVM runner design is superseded by the approved shared Kueue/ARC migration. See [shared compute operations](homelab-kueue.md) for retirement, independent bootstrap, admission and cutover.

The previous design and checkmarks remain under `openspec/changes/add-homelab-self-hosted-ci/evidence/pre-kueue-plan/`. Existing VM bootstrap scripts remain for recorded recovery and the narrowly guarded retirement stage; do not enable the retired VM as part of Kueue rollout.
