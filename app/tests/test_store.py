from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import event

from renvoy_status import store
from renvoy_status.probe import CheckResult

NOW = datetime(2026, 11, 8, 12, 0, tzinfo=UTC)


def result(target: str, ok: bool, minutes_ago: int) -> CheckResult:
    return CheckResult(
        target=target,
        url=f"https://{target}.test",
        ok=ok,
        status_code=200 if ok else 503,
        latency_ms=120.0 if ok else 80.0,
        error=None if ok else "expected HTTP 200",
        checked_at=NOW - timedelta(minutes=minutes_ago),
    )


def test_latest_returns_newest_row_per_target(engine):
    store.record(engine, [result("a", True, 10), result("b", True, 10)])
    store.record(engine, [result("a", False, 5), result("b", True, 5)])

    latest = {row["target"]: row for row in store.latest(engine)}

    assert set(latest) == {"a", "b"}
    assert latest["a"]["ok"] is False
    assert latest["a"]["checked_at"] == NOW - timedelta(minutes=5)


def test_uptime_is_share_of_passed_checks_in_window(engine):
    store.record(
        engine,
        [
            result("a", True, 30),
            result("a", False, 20),
            result("a", True, 10),
            result("a", True, 5),
            result("a", False, 60 * 25),  # outside the 24h window
        ],
    )

    assert store.uptime(engine, NOW - timedelta(hours=24)) == {"a": 0.75}


def test_prune_deletes_only_old_rows(engine):
    store.record(engine, [result("a", True, 60 * 24 * 40), result("a", True, 5)])

    deleted = store.prune(engine, NOW - timedelta(days=30))

    assert deleted == 1
    assert len(store.latest(engine)) == 1


def test_record_with_no_results_is_a_noop(engine):
    assert store.record(engine, []) == 0
    assert store.latest(engine) == []


def test_postgres_engine_sets_a_connect_timeout():
    engine = store.make_engine("postgresql+psycopg://u:p@db.invalid:5432/x")
    seen = {}

    @event.listens_for(engine, "do_connect")
    def capture(dialect, conn_rec, cargs, cparams):
        seen.update(cparams)
        raise RuntimeError("stop before connecting")

    with pytest.raises(RuntimeError, match="stop before connecting"):
        engine.connect()
    assert seen["connect_timeout"] == store.CONNECT_TIMEOUT_SECONDS
