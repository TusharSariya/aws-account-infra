"""Bounded authenticated Data API reads; downloads never receive bearer tokens."""

import json
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin, urlsplit
from urllib.request import Request, build_opener

from .auth import NoRedirect

ORIGIN = "https://members-ng.iracing.com"
DOWNLOAD_HOSTS = {
    "scorpio-assets.s3.us-east-1.amazonaws.com",
    "scorpio-assets.s3.amazonaws.com",
}


class ContractError(RuntimeError):
    pass


def public_data(value):
    """Remove account-specific fields and expiring signed URLs from cache/fixtures."""
    if isinstance(value, list):
        return [public_data(v) for v in value]
    if isinstance(value, dict):
        return {
            k: public_data(v)
            for k, v in value.items()
            if k
            not in {
                "weather_url",
                "allowed_season_members",
                "elig",
                "eligible",
                "reg_user_count",
                "next_race_session",
                "member",
                "cust_id",
                "access_token",
                "refresh_token",
            }
        }
    return value


class DataAPI:
    def __init__(
        self, token, cache=None, clock=time.time, sleep=time.sleep, opener=None
    ):
        self.token = token
        self.cache = cache or {}
        self.used = {}
        self.clock, self.sleep = clock, sleep
        self.opener = opener or build_opener(NoRedirect())
        self.requests = 0

    def _get(self, url, authenticated=False):
        parsed = urlsplit(url)
        allowed = (
            parsed.hostname == "members-ng.iracing.com"
            if authenticated
            else parsed.hostname in DOWNLOAD_HOSTS
        )
        if (
            not allowed
            or parsed.scheme != "https"
            or parsed.username
            or parsed.password
            or parsed.port not in (None, 443)
            or parsed.fragment
        ):
            raise ContractError("Unapproved API or download URL")
        headers = {"Authorization": "Bearer " + self.token} if authenticated else {}
        for attempt in range(3):
            self.requests += 1
            if self.requests > 300:
                raise ContractError("API request budget exhausted")
            try:
                with self.opener.open(
                    Request(url, headers=headers), timeout=20
                ) as response:
                    body = response.read(24 * 1024 * 1024 + 1)
                    if len(body) > 24 * 1024 * 1024:
                        raise ContractError("API response exceeded size limit")
                    return json.loads(body)
            except HTTPError as exc:
                status = exc.code
                delay = exc.headers.get("Retry-After", str(2**attempt))
                exc.close()
                if status not in (429, 500, 502, 503, 504) or attempt == 2:
                    raise ContractError(
                        f"Data API HTTP {status}; previous calendar retained"
                    ) from None
                if not delay.isdigit() or int(delay) > 10:
                    raise ContractError(
                        "Data API rate limit exceeds retry budget"
                    ) from None
                self.sleep(int(delay))
            except URLError, OSError:
                if attempt == 2:
                    raise ContractError("Data API transport failure") from None
                self.sleep(2**attempt)
            except ValueError:
                raise ContractError("Data API returned invalid JSON") from None
        raise ContractError("API retry budget exhausted")

    def get(self, endpoint, **params):
        if endpoint not in {
            "series/seasons",
            "series/season_schedule",
            "series/stats_series",
            "series/get",
            "data/doc",
        }:
            raise ContractError("Unsupported API endpoint")
        key = endpoint + "?" + urlencode(sorted(params.items()))
        saved = self.cache.get(key)
        if saved and saved["expires"] > self.clock():
            self.used[key] = saved
            return saved["data"]
        data = self._get(ORIGIN + "/data/" + key, authenticated=True)
        for _ in range(3):
            if not isinstance(data, dict) or "link" not in data:
                break
            data = self._get(data["link"])
        if isinstance(data, dict) and "link" in data:
            raise ContractError("API link chain exceeded limit")
        if isinstance(data, dict) and data.get("chunk_info"):
            chunks = data["chunk_info"]
            names = chunks["chunk_file_names"]
            if len(names) > 128:
                raise ContractError("API chunk budget exceeded")
            rows = []
            for name in names:
                part = self._get(urljoin(chunks["base_download_url"], name))
                if not isinstance(part, list):
                    raise ContractError("Malformed API chunk")
                rows.extend(part)
            if "num_results" in chunks and len(rows) != chunks["num_results"]:
                raise ContractError("Incomplete API pagination")
            data = rows
        if isinstance(data, dict) and any(
            k in data for k in ("next", "next_page", "next_token", "next_cursor")
        ):
            raise ContractError(
                "Unsupported pagination contract; capture before publishing"
            )
        data = public_data(data)
        self.used[key] = {"expires": self.clock() + 300, "data": data}
        return data
