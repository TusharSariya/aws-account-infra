#!/usr/bin/env python3
"""Compatibility entry point; use homelab-backup.py for new callers."""
from pathlib import Path
import runpy
import sys

if __name__ == '__main__':
    command = Path(__file__).with_name('homelab-backup.py')
    sys.argv = [str(command), *['capture', *sys.argv[1:]]]
    runpy.run_path(str(command), run_name='__main__')
