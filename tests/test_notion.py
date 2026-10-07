"""The API client's retry rules and cache, against a scripted session."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import requests

from mnemo_bridge.sources.notion.client import NotionClient, NotionError, _expired_file_urls


class Response:
    def __init__(self, status=200, data=None, headers=None):
        self.status_code = status
        self._data = data if data is not None else {}
        self.headers = headers or {}
        self.text = json.dumps(self._data)

    def json(self):
        return self._data


class ScriptedSession(requests.Session):
    """Answers each call with the next scripted outcome (a Response or an exception)."""

    def __init__(self, *outcomes):
        super().__init__()
        self.outcomes = list(outcomes)
        self.calls = 0

    def request(self, method, url, **kwargs):  # type: ignore[override]
        self.calls += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def client(*outcomes, **kwargs) -> tuple[NotionClient, ScriptedSession]:
    session = ScriptedSession(*outcomes)
    return NotionClient("t", session=session, requests_per_second=0, **kwargs), session


@mock.patch("mnemo_bridge.sources.notion.client.time.sleep", lambda _s: None)
class Retries(unittest.TestCase):
    def test_reads_retry_through_server_errors(self):
        c, session = client(Response(502), Response(200, {"id": "p"}))
        self.assertEqual(c.get_page("p"), {"id": "p"})
        self.assertEqual(session.calls, 2)

    def test_writes_do_not_repeat_after_a_server_error(self):
        # Notion may have created the page before the gateway gave up.
        c, session = client(Response(504), Response(200, {"id": "dup"}))
        with self.assertRaises(NotionError):
            c.create_page("parent", "Title")
        self.assertEqual(session.calls, 1)

    def test_writes_do_not_repeat_after_a_timeout(self):
        c, session = client(requests.ReadTimeout("slow"), Response(200, {"id": "dup"}))
        with self.assertRaises(NotionError):
            c.append_children("b", [{"type": "divider", "divider": {}}])
        self.assertEqual(session.calls, 1)

    def test_writes_retry_when_the_connection_was_never_made(self):
        c, session = client(
            requests.ConnectionError("Failed to establish a new connection: getaddrinfo failed"),
            Response(200, {"id": "p"}),
        )
        self.assertEqual(c.create_page("parent", "Title"), {"id": "p"})

    def test_writes_retry_on_rate_limit(self):
        c, session = client(Response(429, headers={"Retry-After": "2"}), Response(200, {"id": "p"}))
        self.assertEqual(c.create_page("parent", "Title"), {"id": "p"})

    def test_retry_after_as_a_date_is_understood(self):
        c, _ = client(
            Response(429, headers={"Retry-After": "Wed, 21 Oct 2015 07:28:00 GMT"}),
            Response(200, {"id": "p"}),
        )
        self.assertEqual(c.get_page("p"), {"id": "p"})

    def test_network_failure_becomes_a_notion_error(self):
        c, _ = client(*[requests.ConnectionError("connection refused")] * 2, max_retries=2)
        with self.assertRaises(NotionError):
            c.get_page("p")

    def test_upload_send_failure_becomes_a_notion_error(self):
        c, _ = client(Response(200, {"id": "u1"}), requests.ReadTimeout("slow"))
        with self.assertRaises(NotionError):
            c.upload_file("a.png", "image/png", b"x")

    def test_status_rides_on_the_error(self):
        c, _ = client(Response(400, {"message": "bad"}))
        with self.assertRaises(NotionError) as caught:
            c.create_page("parent", "Title")
        self.assertEqual(caught.exception.status, 400)


@mock.patch("mnemo_bridge.sources.notion.client.time.sleep", lambda _s: None)
class Cache(unittest.TestCase):
    def test_expired_file_links_are_refetched(self):
        stale = {"results": [{"image": {"file": {"url": "u", "expiry_time": "2000-01-01T00:00:00.000Z"}}}]}
        self.assertTrue(_expired_file_urls(stale, 1e10))
        fresh = {"results": [{"image": {"file": {"url": "u", "expiry_time": "2999-01-01T00:00:00.000Z"}}}]}
        self.assertFalse(_expired_file_urls(fresh, 1e10))

    def test_truncated_entry_is_a_miss_not_a_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            c, session = client(Response(200, {"id": "p"}), cache_dir=Path(tmp))
            path = c._cache_path("GET", "/pages/p", None)
            path.write_text('{"id": "p', encoding="utf-8")
            self.assertEqual(c.get_page("p"), {"id": "p"})
            self.assertEqual(session.calls, 1)
            # And the repaired entry now answers on its own.
            self.assertEqual(c.get_page("p"), {"id": "p"})
            self.assertEqual(session.calls, 1)


if __name__ == "__main__":
    unittest.main()
