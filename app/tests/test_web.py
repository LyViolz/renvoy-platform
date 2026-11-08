from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from renvoy_status import store
from renvoy_status.probe import CheckResult
from renvoy_status.web import create_app


def seed(engine, *, b_ok: bool) -> None:
    now = datetime.now(UTC)
    store.record(
        engine,
        [
            CheckResult("a", "https://a.test", True, 200, 101.0, None, now - timedelta(minutes=1)),
            CheckResult(
                "b",
                "https://b.test/<script>",
                b_ok,
                200 if b_ok else 503,
                90.0,
                None if b_ok else "expected HTTP 200",
                now - timedelta(minutes=1),
            ),
        ],
    )


@pytest.fixture
def client(engine):
    with TestClient(create_app(engine)) as c:
        yield c


def test_health_and_readiness(client):
    assert client.get("/healthz").json() == {"status": "ok"}
    assert client.get("/readyz").json() == {"status": "ready"}


def test_api_status_reports_failing_target(client, engine):
    seed(engine, b_ok=False)

    body = client.get("/api/status").json()

    assert body["all_ok"] is False
    by_target = {t["target"]: t for t in body["targets"]}
    assert by_target["a"]["ok"] is True
    assert by_target["a"]["uptime_24h"] == 1.0
    assert by_target["b"]["error"] == "expected HTTP 200"


def test_empty_database_is_not_reported_as_healthy(client):
    body = client.get("/api/status").json()
    assert body["all_ok"] is False
    assert body["targets"] == []
    assert "No checks recorded yet" in client.get("/").text


def test_status_page_renders_and_escapes(client, engine):
    seed(engine, b_ok=False)

    page = client.get("/").text

    assert "Renvoy Status" in page
    assert "1 of 2 checks failing" in page
    assert "<script>" not in page
    assert "&lt;script&gt;" in page


def test_status_page_all_operational(client, engine):
    seed(engine, b_ok=True)
    assert "All systems operational" in client.get("/").text


def test_metrics_exposes_per_target_gauges(client, engine):
    seed(engine, b_ok=False)

    metrics = client.get("/metrics").text

    assert 'renvoy_target_up{target="a"} 1.0' in metrics
    assert 'renvoy_target_up{target="b"} 0.0' in metrics
    assert 'renvoy_target_latency_ms{target="a"} 101.0' in metrics
    assert "renvoy_target_last_check_age_seconds" in metrics
