from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'apps/platform/storage'))
from capacity import CapacityGate


class CapacityTests(unittest.TestCase):
    def setUp(self):
        self.expected = {'filesystem.bytes': 'fs-1', 'filesystem.inodes': 'fs-1',
                         'models': '31001', 'workspace': '31002', 'vector': '31003',
                         'pool.data': 'pve/data', 'pool.metadata': 'pve/data'}
        self.gate = CapacityGate(self.expected)

    def sample(self, percent=10, **updates):
        result = {name: {'identity': identity, 'healthy': True, 'measured_at': 1000,
                         'used_percent': percent} for name, identity in self.expected.items()}
        result['pool.metadata'].update(updates)
        return result

    def tick(self, seconds=0, samples=None):
        return self.gate.evaluate(samples or self.sample(measured_at=1000 + seconds),
                                  wall_time=1000, monotonic_time=seconds)

    def recover(self):
        for second in range(0, 301, 30):
            result = self.gate.evaluate(self.sample(), wall_time=1000, monotonic_time=second)
        self.assertTrue(result.admission)

    def test_startup_requires_full_healthy_interval(self):
        for second in range(0, 300, 30):
            self.assertFalse(self.tick(second, self.sample()).admission)
        self.assertTrue(self.tick(300, self.sample()).admission)

    def test_each_required_measurement_fails_closed(self):
        for name in self.expected:
            samples = self.sample()
            del samples[name]
            result = self.tick(samples=samples)
            self.assertFalse(result.admission)
            self.assertTrue(result.drain)
            self.assertIn(name, result.reasons[0])

    def test_all_invalid_sample_forms(self):
        invalid = [{'identity': 'other'}, {'healthy': False}, {'healthy': 1},
                   {'measured_at': 909}, {'measured_at': 1001}, {'measured_at': float('nan')},
                   {'used_percent': None}, {'used_percent': -1}, {'used_percent': 101},
                   {'used_percent': float('inf')}, {'used_percent': True}]
        for update in invalid:
            with self.subTest(update=update):
                result = self.tick(samples=self.sample(**update))
                self.assertFalse(result.admission)
                self.assertTrue(result.drain)

    def test_exact_freshness_boundary(self):
        self.assertFalse(self.tick(samples=self.sample(measured_at=910)).drain)
        self.assertTrue(self.tick(samples=self.sample(measured_at=909.99)).drain)

    def test_warning_does_not_drain_open_gate(self):
        self.recover()
        result = self.tick(330, self.sample(80))
        self.assertTrue(result.admission)
        self.assertTrue(result.warning)
        self.assertFalse(result.drain)

    def test_pressure_latches_and_recovers_but_does_not_start(self):
        self.recover()
        result = self.tick(330, self.sample(90))
        self.assertTrue(result.drain)
        self.assertFalse(result.admission)
        for second in range(360, 660, 30):
            self.assertFalse(self.tick(second, self.sample()).admission)
        result = self.tick(660, self.sample())
        self.assertTrue(result.admission)
        self.assertFalse(result.drain)
        self.assertFalse(hasattr(result, 'start'))

    def test_warning_resets_recovery(self):
        for second in range(0, 300, 30):
            self.tick(second, self.sample())
        self.tick(300, self.sample(80))
        self.assertFalse(self.tick(330, self.sample()).admission)

    def test_clock_gap_or_regression_breaks_continuity(self):
        for final in [400, -10]:
            self.gate = CapacityGate(self.expected)
            for second in range(0, 300, 30):
                self.tick(second, self.sample())
            self.assertFalse(self.tick(final, self.sample()).admission)

    def test_restart_cannot_reuse_prior_interval(self):
        self.recover()
        self.gate = CapacityGate(self.expected)
        self.assertFalse(self.tick(330, self.sample()).admission)

    def test_overcommit_does_not_consult_declared_total(self):
        self.recover()
        self.assertTrue(self.tick(330, self.sample(20)).admission)


if __name__ == '__main__':
    unittest.main()
