#!/usr/bin/env bash
# Isolated Linux container/CI runner only. Never receives a production device.
set -euo pipefail
[[ $(uname -s) == Linux && ${QUOTA_DISPOSABLE_TEST:-} == yes ]]
[[ ! -e /quota-test && ! -e /quota-test.img ]]
cleanup() {
  mountpoint -q /quota-test && umount /quota-test
  if [[ -n ${loop_device:-} ]]; then losetup -d "$loop_device"; fi
  rm -f /quota-test.img
  rmdir /quota-test 2>/dev/null || true
}
trap cleanup EXIT
truncate -s 400M /quota-test.img
loop_device=$(losetup --find --show /quota-test.img)
mkfs.xfs -f "$loop_device" >/dev/null
mkdir /quota-test
mount -o prjquota "$loop_device" /quota-test
python3 /source/scripts/tests/storage/quota_linux.py "$loop_device" "$(blkid -s UUID -o value "$loop_device")"
umount /quota-test
mount -o prjquota "$loop_device" /quota-test
python3 - "$loop_device" <<'PY'
import os, sys
sys.path.insert(0, '/source/apps/platform/storage')
from xfs import get_quota, open_mount, open_project, project_attributes
fd = open_mount('/quota-test', sys.argv[1])
assert get_quota(fd, 62001).hard * 512 == 10 * 1024**3
project = open_project(fd, 'ai-test-first')
assert project_attributes(project)[3] == 62001
os.close(project)
os.close(fd)
print('PASS: limits and inherited project identity survive unmount/remount')
PY
umount /quota-test
mount -o noquota "$loop_device" /quota-test
python3 - "$loop_device" <<'PY'
import sys
sys.path.insert(0, '/source/apps/platform/storage')
from xfs import open_mount
for path, source in [('/quota-test', sys.argv[1]), ('/quota-test/ai-test-first', sys.argv[1]), ('/quota-test', '/dev/wrong')]:
    try:
        open_mount(path, source)
    except (OSError, ValueError):
        pass
    else:
        raise AssertionError('Disabled quota, missing mount or wrong source accepted')
print('PASS: disabled enforcement, non-mount directory and wrong source rejected')
PY
