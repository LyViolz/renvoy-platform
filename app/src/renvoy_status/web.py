from __future__ import annotations

import html
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

from fastapi import FastAPI, Response
from fastapi.responses import HTMLResponse, JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, Gauge, generate_latest
from sqlalchemy import Engine
from sqlalchemy.exc import SQLAlchemyError

from . import store
from .config import Settings

log = logging.getLogger("renvoy_status.web")


def create_app(engine: Engine | None = None) -> FastAPI:
    if engine is None:
        engine = store.make_engine(Settings.from_env().database_url)
    schema_ready = False

    def ensure_schema() -> None:
        nonlocal schema_ready
        if not schema_ready:
            store.init_db(engine)
            schema_ready = True

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        try:
            ensure_schema()
        except SQLAlchemyError as exc:
            # Postgres may still be starting; /readyz keeps retrying.
            log.warning("database not ready at startup: %s", exc)
        yield
        engine.dispose()

    app = FastAPI(title="Renvoy Status", lifespan=lifespan)

    def snapshot() -> dict:
        now = datetime.now(UTC)
        uptime = store.uptime(engine, now - timedelta(hours=24))
        targets = [
            {
                "target": row["target"],
                "url": row["url"],
                "ok": row["ok"],
                "status_code": row["status_code"],
                "latency_ms": row["latency_ms"],
                "error": row["error"],
                "checked_at": row["checked_at"].isoformat(),
                "uptime_24h": uptime.get(row["target"]),
            }
            for row in store.latest(engine)
        ]
        return {
            "generated_at": now.isoformat(),
            "all_ok": bool(targets) and all(t["ok"] for t in targets),
            "targets": targets,
        }

    @app.get("/healthz")
    def healthz() -> dict:
        return {"status": "ok"}

    @app.get("/readyz")
    def readyz() -> JSONResponse:
        try:
            ensure_schema()
            store.ping(engine)
        except SQLAlchemyError as exc:
            log.warning("readiness check failed: %s", exc)
            return JSONResponse({"status": "unavailable"}, status_code=503)
        return JSONResponse({"status": "ready"})

    @app.get("/api/status")
    def api_status() -> dict:
        return snapshot()

    @app.get("/metrics")
    def metrics() -> Response:
        registry = CollectorRegistry()
        labels = ["target"]
        up = Gauge("renvoy_target_up", "1 if the last check passed", labels, registry=registry)
        latency = Gauge(
            "renvoy_target_latency_ms", "Latency of the last check", labels, registry=registry
        )
        ratio = Gauge(
            "renvoy_target_uptime_ratio_24h",
            "Share of passed checks in 24h",
            labels,
            registry=registry,
        )
        age = Gauge(
            "renvoy_target_last_check_age_seconds",
            "Seconds since the last check",
            labels,
            registry=registry,
        )
        now = datetime.now(UTC)
        for t in snapshot()["targets"]:
            up.labels(t["target"]).set(1 if t["ok"] else 0)
            if t["latency_ms"] is not None:
                latency.labels(t["target"]).set(t["latency_ms"])
            if t["uptime_24h"] is not None:
                ratio.labels(t["target"]).set(t["uptime_24h"])
            checked_at = datetime.fromisoformat(t["checked_at"])
            age.labels(t["target"]).set((now - checked_at).total_seconds())
        return Response(generate_latest(registry), media_type=CONTENT_TYPE_LATEST)

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return render_page(snapshot())

    return app


def render_page(data: dict) -> str:
    targets = data["targets"]
    if not targets:
        banner, banner_class = "No checks recorded yet", "unknown"
    elif data["all_ok"]:
        banner, banner_class = "All systems operational", "up"
    else:
        down = sum(1 for t in targets if not t["ok"])
        banner, banner_class = f"{down} of {len(targets)} checks failing", "down"

    def cell(value: object) -> str:
        return html.escape("—" if value is None else str(value))

    rows = []
    for t in targets:
        state = "up" if t["ok"] else "down"
        uptime = "—" if t["uptime_24h"] is None else f"{t['uptime_24h'] * 100:.2f}%"
        latency = "—" if t["latency_ms"] is None else f"{t['latency_ms']:.0f} ms"
        detail = t["status_code"] if t["ok"] else (t["error"] or t["status_code"])
        rows.append(
            f'<tr><td><span class="dot {state}"></span>{cell(t["target"])}</td>'
            f'<td><a href="{html.escape(t["url"])}">{cell(t["url"])}</a></td>'
            f"<td>{cell(detail)}</td><td>{latency}</td><td>{uptime}</td>"
            f'<td><time datetime="{cell(t["checked_at"])}">{cell(t["checked_at"][:19])}Z</time>'
            "</td></tr>"
        )
    return PAGE.format(
        banner=html.escape(banner),
        banner_class=banner_class,
        rows="\n".join(rows),
        generated=html.escape(data["generated_at"][:19]),
    )


PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="60">
<title>Renvoy Status</title>
<style>
:root {{ --bg:#f7f7f5; --fg:#1d1d1b; --muted:#6b6b66; --line:#e2e2dd; --up:#1f9d55; --down:#d64545;
        --unknown:#8a8a85; }}
@media (prefers-color-scheme: dark) {{
  :root {{ --bg:#141413; --fg:#ececea; --muted:#9a9a94; --line:#2c2c2a; }}
}}
body {{ margin:0; background:var(--bg); color:var(--fg);
       font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif; }}
main {{ max-width:960px; margin:0 auto; padding:32px 16px; }}
h1 {{ font-size:22px; margin:0 0 16px; }}
.banner {{ padding:14px 16px; border-radius:8px; color:#fff; font-weight:600; margin-bottom:24px; }}
.banner.up {{ background:var(--up); }} .banner.down {{ background:var(--down); }}
.banner.unknown {{ background:var(--unknown); }}
.table-wrap {{ overflow-x:auto; }}
table {{ width:100%; border-collapse:collapse; }}
th, td {{ text-align:left; padding:10px 8px; border-bottom:1px solid var(--line);
         white-space:nowrap; }}
th {{ color:var(--muted); font-weight:500; font-size:13px; }}
a {{ color:inherit; }}
.dot {{ display:inline-block; width:9px; height:9px; border-radius:50%; margin-right:8px; }}
.dot.up {{ background:var(--up); }} .dot.down {{ background:var(--down); }}
footer {{ color:var(--muted); font-size:13px; margin-top:24px; }}
</style>
</head>
<body>
<main>
<h1>Renvoy Status</h1>
<div class="banner {banner_class}">{banner}</div>
<div class="table-wrap">
<table>
<thead><tr><th>Check</th><th>URL</th><th>Result</th><th>Latency</th><th>Uptime 24h</th>
<th>Last check (UTC)</th></tr></thead>
<tbody>
{rows}
</tbody>
</table>
</div>
<footer>Generated {generated}Z · JSON at <a href="/api/status">/api/status</a> ·
metrics at <a href="/metrics">/metrics</a></footer>
</main>
</body>
</html>
"""

app = create_app()
