import unittest
from nexus_observation import parse, summarize


class OutboundLogTests(unittest.TestCase):
    def line(self, length='123', download='20', status='200'):
        return ('[16/Sep/2026:15:00:00 +0000] user '
                '"GET https://user:password@example.org/artifact?token=secret HTTP/1.1" '
                + status + ' ' + length + ' 10 ' + download + ' [qtp-1]')

    def test_payload_and_time_preserve_evidence_without_secrets(self):
        record = parse(self.line())
        self.assertEqual(record['declared_body_bytes'], 123)
        self.assertTrue(record['complete_payload_known'])
        self.assertEqual(record['download_ms'], 20)
        for sensitive in ('password', 'token', 'secret', '/artifact'):
            self.assertNotIn(sensitive, str(record))

    def test_chunked_failed_and_incomplete_responses_are_not_zero_bytes(self):
        for line in [self.line(length='-1'), self.line(download='---'), self.line(status='503')]:
            result = summarize([line])
            self.assertFalse(result['complete_payload_measurement'])
            self.assertEqual(result['unknown_get_responses'], 1)

    def test_unknown_shapes_fail_closed(self):
        with self.assertRaises(ValueError):
            parse('unrecognized or truncated log record')
        with self.assertRaises(ValueError):
            parse(self.line() + ' unexpected column')

    def test_legacy_format_is_not_misreported_as_payload(self):
        line = '[16/Sep/2026:15:00:00 +0000] - "GET https://example.org/a HTTP/1.1" 200 12 456 "Nexus/3.63" [qtp-1]'
        record = parse(line)
        self.assertEqual(record['received_bytes'], 456)
        self.assertFalse(record['complete_payload_known'])
