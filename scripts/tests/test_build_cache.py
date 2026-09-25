import unittest
from unittest.mock import patch
from build_cache import settings, pod_cgroup_parent


class BuildCacheTests(unittest.TestCase):
    def test_builder_is_bound_to_the_observed_pod(self):
        uid = 'edb2ab4c-354a-4966-8f0b-9e4643619db6'
        parent = '/kubepods/pod' + uid
        with patch.dict('os.environ', {'HOMELAB_RUNNER_POD_UID': uid}), \
                patch('build_cache.Path.read_text', return_value=parent + '\n'):
            value = settings('build', 'linux/amd64', 'main', cgroup_parent=pod_cgroup_parent())
        self.assertIn('cgroup-parent=' + parent, value['driver-opts'].splitlines())
        for invalid in ['/docker/buildx', '/', parent + '\nnetwork=host']:
            with self.assertRaises(ValueError):
                settings('build', 'linux/amd64', 'main', cgroup_parent=invalid)
        with patch.dict('os.environ', {'HOMELAB_RUNNER_POD_UID': uid}), \
                patch('build_cache.Path.read_text', return_value='/docker/buildx'):
            with self.assertRaises(ValueError):
                pod_cgroup_parent()

    def test_scope_isolates_workflows_platforms_and_branches(self):
        first = settings('Ollama image', 'linux/amd64', 'feature/cache')
        for args in [('Other workflow','linux/amd64','feature/cache'),
                     ('Ollama image','linux/arm64','feature/cache'),
                     ('Ollama image','linux/amd64','feature-cache')]:
            self.assertNotEqual(first['cache-to'], settings(*args)['cache-to'])
        self.assertEqual(len(first['cache-from'].splitlines()), 2)
        main = settings('Ollama image', 'linux/amd64', 'main')
        self.assertEqual(len(main['cache-from'].splitlines()), 1)
        self.assertIn(main['cache-from'], first['cache-from'])
        # Branch ref is imported first; main's is a read-only fallback never exported to.
        branch_ref = first['cache-to'].split(',')[1]
        self.assertEqual(first['cache-from'].splitlines()[0], 'type=registry,' + branch_ref)
        self.assertEqual(first['cache-from'].splitlines()[1], main['cache-from'])
        self.assertNotIn(main['cache-from'].split(',')[1], first['cache-to'])

    def test_export_is_maximal_oci_and_nonfatal(self):
        result = settings('build', 'linux/amd64', 'main')
        for option in ('mode=max', 'oci-mediatypes=true', 'image-manifest=true', 'ignore-error=true'):
            self.assertIn(option, result['cache-to'])
        self.assertNotIn('ghcr.io', result['cache-to'])
        self.assertNotIn('password', str(result))
        with self.assertRaises(ValueError):
            settings('build','linux/amd64,linux/arm64','main')
