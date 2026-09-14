import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'apps/platform/storage'), str(ROOT / 'apps/platform/migration')]
import reset
spec = importlib.util.spec_from_file_location('migration_ci', ROOT / 'scripts/ai-migration.py')
migration_ci = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migration_ci)


def receipt():
    import uuid
    values = {}
    for number, name in enumerate(reset.CLAIMS, 1):
        uid = str(uuid.UUID(int=number))
        values[name] = {'claim_uid': uid, 'pv_uid': uid, 'pv_name': 'pvc-' + uid,
                        'basename': 'pvc-' + uid + '_homelab-models_' + name}
    return {'claims': values}


class MigrationTests(unittest.TestCase):
    def test_exact_claim_set_and_lineage_are_required(self):
        reset.validate_receipt(receipt())
        changed = receipt()
        changed['claims']['pihole'] = changed['claims'].pop('ollama-models')
        with self.assertRaises(ValueError):
            reset.validate_receipt(changed)
        for path in ('../pihole', 'ai-models', 'pvc-other_homelab-models_ollama-models'):
            changed = receipt()
            changed['claims']['ollama-models']['basename'] = path
            with self.assertRaises(ValueError):
                reset.validate_receipt(changed)

    def test_started_or_completed_receipt_cannot_replay_or_open_storage(self):
        for phase in ('started', 'completed'):
            record = {'immutable': True, 'metadata': {'annotations': {'homelab/reset-phase': phase}}}
            with patch.object(reset, 'api', return_value=record), patch.object(reset, 'open_mount') as mount, self.assertRaises(ValueError):
                reset.main()
            mount.assert_not_called()

    def test_pending_or_terminating_writer_blocks_reset_before_claim_reads(self):
        deployments = {'items': [{'metadata': {'name': name}, 'spec': {'replicas': 0}}
                                 for name in ('ollama', 'odysseus', 'chromadb', 'searxng')]}
        pods = {'items': [{'spec': {'volumes': [{'persistentVolumeClaim': {'claimName': 'ollama-models'}}]},
                           'status': {'phase': 'Pending'}}]}
        with patch.object(reset, 'api', side_effect=[deployments, pods]) as api, self.assertRaises(ValueError):
            reset.verify_stopped(receipt())
        self.assertEqual(api.call_count, 2)

    def test_reset_phase_transition_uses_resource_version_compare_and_swap(self):
        with patch.object(reset, 'api') as api:
            reset.transition({'metadata': {'resourceVersion': '123'}}, 'started')
        operations = api.call_args.args[2]
        self.assertEqual(operations[0], {'op': 'test', 'path': '/metadata/resourceVersion', 'value': '123'})
        self.assertEqual(operations[1]['value'], 'started')

    def test_anchored_deletion_removes_symlinks_without_following_neighbors(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target, neighbor = root / 'target', root / 'neighbor'
            target.mkdir()
            neighbor.mkdir()
            (neighbor / 'proof').write_text('preserve')
            (target / 'link').symlink_to(neighbor, target_is_directory=True)
            (target / 'nested').mkdir()
            (target / 'nested' / 'data').write_bytes(b'authorized data')
            fd = os.open(target, os.O_RDONLY | os.O_DIRECTORY)
            try:
                reset.erase_contents(fd, os.fstat(fd).st_dev)
            finally:
                os.close(fd)
            self.assertEqual(list(target.iterdir()), [])
            self.assertEqual((neighbor / 'proof').read_text(), 'preserve')

    def test_pr_or_missing_confirmation_cannot_start_migration(self):
        for env in ({'GITHUB_ACTIONS': 'true', 'GITHUB_REF': 'refs/pull/68/merge', 'AI_RESET_CONFIRM': 'reset-three-ai-volumes-v1'},
                    {'GITHUB_ACTIONS': 'true', 'GITHUB_REF': 'refs/heads/main'}):
            with patch.dict(os.environ, env, clear=True), patch.object(migration_ci.subprocess, 'run') as run, self.assertRaises(ValueError):
                migration_ci.main()
            run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
