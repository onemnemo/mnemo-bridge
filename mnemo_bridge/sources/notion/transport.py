"""HTTP helpers for the Notion client: retry timing, cache expiry, connection failures."""

from __future__ import annotations

import time
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import Any

import requests

API_ROOT = "https://api.notion.com/v1"


def _retry_after(response: requests.Response) -> float:
    """Seconds Notion asked us to wait. The header may also be an HTTP date."""
    value = response.headers.get("Retry-After") or ""
    try:
        return max(0.0, float(value))
    except ValueError:
        pass
    try:
        return max(0.0, parsedate_to_datetime(value).timestamp() - time.time())
    except (TypeError, ValueError, IndexError):
        return 1.0


def _expired_file_urls(data: Any, now: float) -> bool:
    """
    Whether a cached response holds a Notion-hosted file link that has expired.

    Uploaded files are signed S3 links with an ``expiry_time`` about an hour
    out, so an expired one would 403 on download and counts as a cache miss.
    """
    stack = [data]
    while stack:
        item = stack.pop()
        if isinstance(item, dict):
            expiry = item.get("expiry_time")
            if isinstance(expiry, str):
                try:
                    moment = datetime.fromisoformat(expiry.replace("Z", "+00:00")).timestamp()
                except ValueError:
                    return True
                # A minute of margin: the download happens a little later.
                if moment - 60 <= now:
                    return True
            stack.extend(item.values())
        elif isinstance(item, list):
            stack.extend(item)
    return False


def _never_connected(exc: requests.ConnectionError) -> bool:
    """
    Whether a connection error happened before the request left this machine.

    DNS failures and refused connections mean Notion never saw the request,
    so even a write is safe to send again. A reset mid-response is not.
    """
    text = str(exc).lower()
    return any(
        marker in text
        for marker in (
            "name resolution",
            "getaddrinfo",
            "nodename nor servname",
            "name or service not known",
            "connection refused",
            "failed to establish a new connection",
            "network is unreachable",
        )
    )
