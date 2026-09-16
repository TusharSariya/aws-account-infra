import unittest
from build_cache import settings


class BuildCacheTests(unittest.TestCase):
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

    def test_export_is_maximal_oci_and_nonfatal(self):
        result = settings('build', 'linux/amd64', 'main')
        for option in ('mode=max', 'oci-mediatypes=true', 'image-manifest=true', 'ignore-error=true'):
            self.assertIn(option, result['cache-to'])
        self.assertNotIn('ghcr.io', result['cache-to'])
        self.assertNotIn('password', str(result))
        with self.assertRaises(ValueError):
            settings('build','linux/amd64,linux/arm64','main')
