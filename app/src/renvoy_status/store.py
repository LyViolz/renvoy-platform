from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict
from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Engine,
    Float,
    Integer,
    MetaData,
    String,
    Table,
    and_,
    case,
    create_engine,
    func,
    select,
    text,
)
from sqlalchemy.engine import make_url

from .probe import CheckResult

metadata = MetaData()

checks = Table(
    "checks",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("target", String(100), nullable=False, index=True),
    Column("url", String(500), nullable=False),
    Column("ok", Boolean, nullable=False),
    Column("status_code", Integer),
    Column("latency_ms", Float),
    Column("error", String(500)),
    Column("checked_at", DateTime(timezone=True), nullable=False, index=True),
)


# Without it, connecting to a Postgres pod that had just gone away hung for 39 to 71 s in an
# outage drill on k3d (psycopg's own default is 130 s), and every request waiting on it hung too.
CONNECT_TIMEOUT_SECONDS = 3


def make_engine(url: str) -> Engine:
    connect_args = {}
    if make_url(url).get_backend_name() == "postgresql":
        connect_args["connect_timeout"] = CONNECT_TIMEOUT_SECONDS
    return create_engine(url, pool_pre_ping=True, connect_args=connect_args)


def init_db(engine: Engine) -> None:
    metadata.create_all(engine)


def ping(engine: Engine) -> None:
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))


def as_utc(value: datetime) -> datetime:
    # SQLite returns naive datetimes; everything is written in UTC.
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def record(engine: Engine, results: Iterable[CheckResult]) -> int:
    rows = [asdict(r) for r in results]
    if rows:
        with engine.begin() as conn:
            conn.execute(checks.insert(), rows)
    return len(rows)


def latest(engine: Engine) -> list[dict]:
    newest = (
        select(checks.c.target, func.max(checks.c.checked_at).label("checked_at"))
        .group_by(checks.c.target)
        .subquery()
    )
    stmt = (
        select(checks)
        .join(
            newest,
            and_(
                checks.c.target == newest.c.target,
                checks.c.checked_at == newest.c.checked_at,
            ),
        )
        .order_by(checks.c.target)
    )
    with engine.connect() as conn:
        rows = [dict(row._mapping) for row in conn.execute(stmt)]
    for row in rows:
        row["checked_at"] = as_utc(row["checked_at"])
    return rows


def uptime(engine: Engine, since: datetime) -> dict[str, float]:
    ratio = func.avg(case((checks.c.ok, 1.0), else_=0.0))
    stmt = (
        select(checks.c.target, ratio).where(checks.c.checked_at >= since).group_by(checks.c.target)
    )
    with engine.connect() as conn:
        return {target: float(value) for target, value in conn.execute(stmt)}


def prune(engine: Engine, older_than: datetime) -> int:
    with engine.begin() as conn:
        return conn.execute(checks.delete().where(checks.c.checked_at < older_than)).rowcount
