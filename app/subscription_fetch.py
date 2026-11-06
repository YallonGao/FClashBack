"""Read the traffic and expiry an airport reports in its own headers.

A subscription URL answers with `subscription-userinfo: upload=…; download=…
; total=…; expire=…`, which is the same header the app shows on a profile.
Fetching it here means the console can fill those numbers instead of asking
the owner to type them in every month.
"""

from __future__ import annotations

import ipaddress
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone

USERINFO_PATTERN = re.compile(r"([a-zA-Z_-]+)\s*=\s*(\d+)")
TIMEOUT_SECONDS = 12
MAX_REDIRECTS = 3


class FetchError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class SubscriptionUsage:
    upload: int
    download: int
    total: int
    expire_at: datetime | None

    @property
    def used(self) -> int:
        return self.upload + self.download


def parse_userinfo(value: str | None) -> SubscriptionUsage:
    if not value:
        raise FetchError("no_userinfo")
    fields = {name.lower(): int(number) for name, number in USERINFO_PATTERN.findall(value)}
    if not fields:
        raise FetchError("no_userinfo")
    expire = fields.get("expire", 0)
    expire_at = (
        datetime.fromtimestamp(expire, tz=timezone.utc).replace(tzinfo=None)
        if expire > 0
        else None
    )
    return SubscriptionUsage(
        upload=fields.get("upload", 0),
        download=fields.get("download", 0),
        total=fields.get("total", 0),
        expire_at=expire_at,
    )


def _assert_public(host: str, port: int | None) -> None:
    try:
        addresses = socket.getaddrinfo(host, port or 80, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise FetchError("unresolvable_host") from exc
    for *_, sockaddr in addresses:
        address = ipaddress.ip_address(sockaddr[0])
        if (
            address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_reserved
            or address.is_multicast
        ):
            raise FetchError("blocked_address")


def fetch_usage(url: str, *, allow_private: bool = False) -> SubscriptionUsage:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise FetchError("invalid_url")
    if not allow_private:
        _assert_public(parsed.hostname, parsed.port)
    if parsed.port and parsed.port not in (80, 443) and not allow_private:
        raise FetchError("blocked_port")

    request = urllib.request.Request(
        url,
        headers={"User-Agent": "FClash-Console/1.0", "Accept": "*/*"},
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            if response.status >= 400:
                raise FetchError(f"http_{response.status}")
            header = response.headers.get("subscription-userinfo")
            response.close()
    except FetchError:
        raise
    except urllib.error.HTTPError as exc:
        raise FetchError(f"http_{exc.code}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise FetchError("fetch_failed") from exc
    return parse_userinfo(header)
