import unittest
from datetime import datetime, timezone

from sli import message_age_seconds


class MessageLatencyTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 16, 12, 0, 5, tzinfo=timezone.utc)

    def test_elapsed_time_and_timezone_conversion(self):
        self.assertEqual(message_age_seconds("2026-10-16T12:00:00Z", self.now), 5)
        self.assertEqual(message_age_seconds("2026-10-16T15:30:00+03:30", self.now), 5)
        self.assertEqual(message_age_seconds("2026-10-16T12:00:04.750000+00:00", self.now), .25)

    def test_bad_timestamp_does_not_become_a_fast_sample(self):
        for timestamp in (None, 42, "invalid", "2026-10-16T12:00:00", "2026-10-16T12:00:06Z"):
            with self.subTest(timestamp=timestamp), self.assertRaises((ValueError, TypeError)):
                message_age_seconds(timestamp, self.now)

    def test_old_valid_messages_remain_visible_as_slow(self):
        self.assertEqual(message_age_seconds("2026-10-15T12:00:05Z", self.now), 86400)


if __name__ == "__main__":
    unittest.main()
