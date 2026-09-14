"""Exercise backup failure recovery without touching a cluster or private data."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


class BackupTests(unittest.TestCase):
    def test_failed_capture_restores_both_deployments(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            kubectl = root / 'kubectl'
            kubectl.write_text('''#!/usr/bin/env python3
import json,os,sys
with open(os.environ['CALLS'], 'a') as f: f.write(json.dumps(sys.argv[1:])+'\\n')
a=sys.argv[1:]
if 'get' in a and 'deployment' in a: print('1',end='')
if 'exec' in a and 'deployment/odysseus' in a: print('{"models":[]}')
if 'exec' in a and 'tar' in a: sys.exit(12)
''')
            kubectl.chmod(0o755)
            age = root / 'age'
            age.write_text('''#!/usr/bin/env python3
import pathlib,sys
sys.stdin.buffer.read()
pathlib.Path(sys.argv[sys.argv.index('-o')+1]).write_bytes(b'fixture-only')
''')
            age.chmod(0o755)
            env = {**os.environ, 'PATH': str(root) + os.pathsep + os.environ['PATH'], 'CALLS': str(root / 'calls')}
            result = subprocess.run(['bash', str(ROOT / 'scripts/odysseus-backup.sh'), 'age1fixture', str(root / 'output')], env=env, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            calls = (root / 'calls').read_text()
            for name in ['odysseus', 'chromadb']:
                self.assertIn('"deployment/' + name + '", "--replicas=0"', calls)
                self.assertIn('"deployment/' + name + '", "--replicas=1"', calls)
            self.assertIn('"delete", "pod", "odysseus-backup"', calls)
            self.assertFalse((root / 'output/checksum.txt').exists())


if __name__ == '__main__':
    unittest.main()
