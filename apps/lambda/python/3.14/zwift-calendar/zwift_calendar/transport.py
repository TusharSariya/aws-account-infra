"""Bounded HTTP requests; credentials are sent only to fixed Zwift origins."""

import re
import time
from urllib.parse import urlsplit

import httpx

from .errors import (
    AuthenticationError,
    BudgetExceeded,
    ContractError,
    CursorRejected,
    EventUnavailable,
    RateLimited,
    UpstreamError,
)

API = "https://us-or-rly101.zwift.com/api/"
TOKEN_URL = "https://secure.zwift.com/auth/realms/zwift/tokens/access/codes"


class Transport:
    def __init__(
        self,
        client=None,
        *,
        budget=500,
        clock=time.monotonic,
        sleep=time.sleep,
        seconds=420,
        interval=0,
        defer_rate_limits=False,
    ):
        self.client = client or httpx.Client(
            timeout=httpx.Timeout(12, connect=4), follow_redirects=False
        )
        self.remaining = budget
        self.clock, self.sleep = clock, sleep
        self.deadline = clock() + seconds
        self.interval = interval
        self.next_request = clock()
        self.defer_rate_limits = defer_rate_limits

    def download_fit(self, url):
        parsed = urlsplit(url)
        if parsed.scheme != "https" or not re.fullmatch(
            r"[a-z0-9][a-z0-9-]{1,61}[a-z0-9]\.s3\.amazonaws\.com", parsed.netloc
        ):
            raise ContractError("Untrusted FIT destination")
        if self.remaining <= 0 or self.clock() >= self.deadline:
            raise BudgetExceeded("FIT budget exhausted")
        self.remaining -= 1
        try:
            with self.client.stream(
                "GET",
                url,
                headers={"Accept": "application/octet-stream"},
                timeout=min(12, max(0.1, self.deadline - self.clock())),
                follow_redirects=False,
            ) as response:
                if response.status_code != 200:
                    raise UpstreamError("FIT download failed")
                body = bytearray()
                for chunk in response.iter_bytes():
                    if self.clock() >= self.deadline:
                        raise BudgetExceeded("FIT budget exhausted")
                    body.extend(chunk)
                    if len(body) > 16_000_000:
                        raise ContractError("FIT response too large")
                return bytes(body)
        except httpx.HTTPError:
            raise UpstreamError("FIT transport failed") from None

    def request(self, url, *, token=None, form=None):
        if not (url.startswith(API) or url == TOKEN_URL):
            raise ContractError("Untrusted upstream destination")
        if token and not url.startswith(API):
            raise ContractError("Bearer token destination rejected")
        if form is not None and url != TOKEN_URL:
            raise ContractError("Credential destination rejected")
        headers = {
            "Accept": "application/json",
            "Source": "zwift-web",
            "Zwift-Api-Version": "2.5",
        }
        if token:
            headers["Authorization"] = "Bearer " + token
        attempts = 1 if form is not None else 3
        for attempt in range(attempts):
            if self.remaining <= 0 or self.clock() >= self.deadline:
                raise BudgetExceeded("Upstream request budget exhausted")
            delay = max(0, self.next_request - self.clock())
            if self.clock() + delay + 12 >= self.deadline:
                raise BudgetExceeded("Upstream request budget exhausted")
            self.sleep(delay)
            self.next_request = self.clock() + self.interval
            self.remaining -= 1
            try:
                with self.client.stream(
                    "POST" if form is not None else "GET",
                    url,
                    headers=headers,
                    data=form,
                    timeout=min(12, max(0.1, self.deadline - self.clock())),
                ) as response:
                    status = response.status_code
                    if self.defer_rate_limits and status == 429:
                        try:
                            delay = max(
                                60, float(response.headers.get("Retry-After", "10800"))
                            )
                            if not 0 < delay < float("inf"):
                                delay = 10800
                        except ValueError:
                            delay = 10800
                        raise RateLimited(delay)
                    if status in (400, 410) and "/event-feed?cursor=" in url:
                        raise CursorRejected("Historical cursor expired")
                    if status in (401, 403) or (form is not None and status == 400):
                        raise AuthenticationError(
                            "Zwift authentication requires attention"
                        )
                    if status == 429 or status >= 500:
                        if attempt + 1 == attempts:
                            raise UpstreamError("Zwift temporarily unavailable")
                        try:
                            delay = min(
                                10,
                                max(
                                    1,
                                    float(
                                        response.headers.get("Retry-After", 2**attempt)
                                    ),
                                ),
                            )
                        except ValueError:
                            delay = 2**attempt
                        if self.clock() + delay >= self.deadline:
                            raise BudgetExceeded("Upstream time budget exhausted")
                        self.sleep(delay)
                        continue
                    if status == 404 and url.startswith(API + "public/events/"):
                        raise EventUnavailable("Historical event unavailable")
                    if status != 200:
                        raise UpstreamError("Unexpected Zwift HTTP response")
                    body = bytearray()
                    for chunk in response.iter_bytes():
                        if self.clock() >= self.deadline:
                            raise BudgetExceeded("Upstream time budget exhausted")
                        body.extend(chunk)
                        if len(body) > 8_000_000:
                            raise ContractError("Upstream response too large")
                    import json

                    try:
                        return json.loads(body)
                    except ValueError, UnicodeError:
                        raise ContractError("Invalid upstream JSON") from None
            except httpx.HTTPError:
                if attempt + 1 == attempts:
                    raise UpstreamError("Zwift transport failed") from None
                self.sleep(2**attempt)
        raise UpstreamError("Zwift request failed")
