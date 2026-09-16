"""Parse supported Nexus outbound logs without retaining signed URLs or identities.

Unknown body lengths are explicitly unverified, never counted as zero-byte hits.
The live Nexus log shape must be checked before adopting these observations.
"""
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

PREFIX = re.compile(r'^\[([^]]+)\] \S+ "(GET|HEAD|POST|PUT|DELETE|PATCH|OPTIONS) (\S+) HTTP/[^"]+" (\d{3}) (.*)$')
CURRENT = re.compile(r'^(-?\d+) (\d+) (\d+|---) \[([^]]+)\]$')
LEGACY = re.compile(r'^(\d+) (\d+) "[^"]*" \[([^]]+)\]$')


def parse(line):
    match = PREFIX.fullmatch(line.strip())
    if not match:
        raise ValueError('Unrecognized Nexus outbound log prefix')
    timestamp, method, url, status, tail = match.groups()
    parsed = urlsplit(url)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname:
        raise ValueError('Unexpected outbound origin')
    value = {
        'time': datetime.strptime(timestamp, '%d/%b/%Y:%H:%M:%S %z').isoformat(),
        'method': method, 'host': parsed.hostname,
        # Omit query parameters, userinfo and source path from portable receipts.
        'path_sha256': hashlib.sha256(parsed.path.encode()).hexdigest(),
        'status': int(status),
    }
    current = CURRENT.fullmatch(tail)
    legacy = LEGACY.fullmatch(tail)
    if current:
        length, response_ms, download_ms, thread = current.groups()
        value.update(format='content-length-and-timing', declared_body_bytes=int(length),
                     response_ms=int(response_ms),
                     download_ms=None if download_ms == '---' else int(download_ms), thread=thread)
        # Content-Length is declared, not a count of bytes received after a
        # failed/interrupted transfer. Only successful completed reads qualify.
        value['complete_payload_known'] = (
            method == 'GET' and 200 <= int(status) < 300 and int(length) >= 0 and download_ms != '---')
    elif legacy:
        sent, received, thread = legacy.groups()
        value.update(format='legacy-transfer-bytes', sent_bytes=int(sent), received_bytes=int(received),
                     thread=thread, complete_payload_known=False)
    else:
        raise ValueError('Unrecognized Nexus outbound log fields')
    return value


def summarize(lines):
    records = [parse(line) for line in lines if line.strip()]
    unknown = [row for row in records if row['method'] == 'GET' and not row['complete_payload_known']]
    return {'records': records,
            'known_completed_payload_bytes': sum(row['declared_body_bytes'] for row in records if row['complete_payload_known']),
            'unknown_get_responses': len(unknown),
            'complete_payload_measurement': not unknown}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('log', type=Path)
    args = parser.parse_args()
    print(json.dumps(summarize(args.log.read_text().splitlines()), indent=2))
