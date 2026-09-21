import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from capacity import swapping


def samples(traffic):
    result = [{"time": 0, "page_size": 4096, "swap": {"pswpin": 0, "pswpout": 0}}]
    for pages in traffic:
        result.append(
            {
                "time": result[-1]["time"] + 15,
                "page_size": 4096,
                "swap": {"pswpin": 0, "pswpout": result[-1]["swap"]["pswpout"] + pages},
            }
        )
    return result


class CapacityTests(unittest.TestCase):
    def test_isolated_reclaim_burst_does_not_imply_sustained_paging(self):
        self.assertTrue(swapping(samples([12000, 0, 1, 0, 0]))["no_sustained_swap"])

    def test_continuous_paging_for_one_minute_fails(self):
        report = swapping(samples([240, 240, 240, 240]))
        self.assertFalse(report["no_sustained_swap"])
        self.assertEqual(report["longest_sustained_seconds"], 60)

    def test_idle_interval_breaks_paging_streak(self):
        self.assertTrue(swapping(samples([240, 240, 0, 240, 240]))["no_sustained_swap"])

    def test_missing_sampling_window_and_counter_reset_fail_closed(self):
        for bad in [[], samples([-1]), samples([1])]:
            if bad and bad[-1]["swap"]["pswpout"] == 1:
                bad[-1]["time"] = 90
            self.assertFalse(swapping(bad)["no_sustained_swap"])
