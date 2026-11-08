from __future__ import annotations

import asyncio

import httpx

from renvoy_status.config import Target
from renvoy_status.probe import check_all


def handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/ok":
        return httpx.Response(200)
    if request.url.path == "/moved":
        return httpx.Response(301, headers={"Location": "https://example.test/ok"})
    if request.url.path == "/fail":
        return httpx.Response(503)
    if request.url.path == "/created":
        return httpx.Response(201)
    raise httpx.ConnectError("connection refused", request=request)


def run(targets: list[Target]):
    results = asyncio.run(check_all(targets, timeout=5, transport=httpx.MockTransport(handler)))
    return {r.target: r for r in results}


def test_passing_check_records_status_and_latency():
    result = run([Target("ok", "https://example.test/ok")])["ok"]
    assert result.ok
    assert result.status_code == 200
    assert result.latency_ms is not None
    assert result.error is None


def test_redirects_are_followed():
    assert run([Target("moved", "https://example.test/moved")])["moved"].ok


def test_unexpected_status_fails_with_reason():
    result = run([Target("fail", "https://example.test/fail")])["fail"]
    assert not result.ok
    assert result.status_code == 503
    assert result.error == "expected HTTP 200"


def test_custom_expected_status():
    result = run([Target("created", "https://example.test/created", expected_status=201)])
    assert result["created"].ok


def test_connection_error_is_a_failed_check_not_an_exception():
    result = run([Target("down", "https://example.test/down")])["down"]
    assert not result.ok
    assert result.status_code is None
    assert result.latency_ms is None
    assert result.error.startswith("ConnectError")
