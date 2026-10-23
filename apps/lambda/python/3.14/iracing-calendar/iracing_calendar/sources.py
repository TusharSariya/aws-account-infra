"""Bounded public downloads shared by inventory and announcement discovery."""

import base64
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

NEWS = "https://www.iracing.com/category/news/"
ALLOWED = {"www.iracing.com"}


class Fetcher:
    def __init__(self, cache=None):
        self.cache = cache or {}
        self.used = {}
        self.requests = 0
        self.deadline = time.monotonic() + 420

    def get(self, url):
        if urlparse(url).scheme != "https" or urlparse(url).hostname not in ALLOWED:
            raise ValueError(f"Unsupported public source: {url}")
        if url in self.used:
            return base64.b64decode(self.used[url]["body"])
        self.requests += 1
        if self.requests > 24 or time.monotonic() > self.deadline:
            raise ValueError("Source request budget exceeded")
        old = self.cache.get(url, {})
        headers = {"User-Agent": "iracing-calendar/0.1 (public schedule reader)"}
        for field, header in (
            ("etag", "If-None-Match"),
            ("modified", "If-Modified-Since"),
        ):
            if old.get(field):
                headers[header] = old[field]
        for attempt in range(3):
            try:
                with urlopen(Request(url, headers=headers), timeout=12) as response:
                    if urlparse(response.url).hostname not in ALLOWED:
                        raise ValueError("Unexpected source redirect")
                    body = response.read(12_000_001)
                    if len(body) > 12_000_000:
                        raise ValueError("Oversized source")
                    self.used[url] = {
                        "body": base64.b64encode(body).decode(),
                        "etag": response.headers.get("ETag"),
                        "modified": response.headers.get("Last-Modified"),
                    }
                    return body
            except HTTPError as exc:
                if exc.code == 304 and old:
                    self.used[url] = old
                    return base64.b64decode(old["body"])
                if exc.code not in (429, 500, 502, 503, 504) or attempt == 2:
                    raise
            except URLError, TimeoutError:
                if attempt == 2:
                    raise
            time.sleep(0.25 * 2**attempt)
        raise RuntimeError("Unreachable fetch failure")
