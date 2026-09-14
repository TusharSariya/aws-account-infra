from pathlib import Path
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'apps/platform/storage'))
from physical import collect, parse_lvs


class PhysicalTests(unittest.TestCase):
    def setUp(self):
        self.row = {'vg_name': 'pve', 'lv_name': 'data', 'segtype': 'thin-pool',
                    'lv_attr': 'twi-a-tz--', 'data_percent': '80.01', 'metadata_percent': '90.00'}

    def parse(self, rows=None):
        return parse_lvs({'report': [{'lv': [self.row] if rows is None else rows}]}, 'pve/data', 100)

    def test_data_and_metadata_are_independent(self):
        samples = self.parse()
        self.assertEqual(samples['pool.data']['used_percent'], 80.01)
        self.assertEqual(samples['pool.metadata']['used_percent'], 90)
        self.assertEqual(samples['pool.data']['measured_at'], 100)

    def test_absent_duplicate_wrong_or_unhealthy_pool_rejected(self):
        for rows in [[], [self.row, self.row], [{**self.row, 'lv_name': 'other'}],
                     [{**self.row, 'segtype': 'thin'}], [{**self.row, 'lv_attr': 'twi---tz--'}],
                     [{**self.row, 'lv_attr': 'twi-a-tzD-'}]]:
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                self.parse(rows)

    def test_missing_or_invalid_metadata_is_not_replaced_with_data(self):
        for value in ['', 'nan', 'inf', '-1', '101', None]:
            with self.subTest(value=value), self.assertRaises((ValueError, TypeError)):
                self.parse([{**self.row, 'metadata_percent': value}])
        del self.row['metadata_percent']
        with self.assertRaises(KeyError):
            self.parse()

    @patch('physical.subprocess.run')
    def test_fixed_readonly_command_never_interpolates_pool(self, run):
        run.return_value.stdout = '{"report": [{"lv": []}]}'
        with self.assertRaises(ValueError):
            collect('pve/data; dangerous')
        command = run.call_args.args[0]
        self.assertEqual(command[0], '/usr/sbin/lvs')
        self.assertNotIn('--readonly', command)  # This option omits live device-mapper state.
        self.assertFalse(any('dangerous' in value for value in command))
        self.assertNotIn('shell', run.call_args.kwargs)


if __name__ == '__main__':
    unittest.main()
