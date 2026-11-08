from __future__ import annotations

import asyncio
import time
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx

from .config import Target

USER_AGENT = "renvoy-status-probe/0.1 (+https://github.com/LyViolz/renvoy-platform)"


@dataclass(frozen=True)
class CheckResult:
    target: str
    url: str
    ok: bool
    status_code: int | None
    latency_ms: float | None
    error: str | None
    checked_at: datetime


async def check(client: httpx.AsyncClient, target: Target) -> CheckResult:
    checked_at = datetime.now(UTC)
    started = time.perf_counter()
    try:
        response = await client.get(target.url)
    except httpx.HTTPError as exc:
        error = f"{type(exc).__name__}: {exc}".strip(": ")[:500]
        return CheckResult(target.name, target.url, False, None, None, error, checked_at)
    latency_ms = round((time.perf_counter() - started) * 1000, 1)
    ok = response.status_code == target.expected_status
    error = None if ok else f"expected HTTP {target.expected_status}"
    return CheckResult(
        target.name, target.url, ok, response.status_code, latency_ms, error, checked_at
    )


async def check_all(
    targets: Iterable[Target],
    timeout: float,
    transport: httpx.AsyncBaseTransport | None = None,
) -> list[CheckResult]:
    async with httpx.AsyncClient(
        timeout=timeout,
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT},
        transport=transport,
    ) as client:
        return list(await asyncio.gather(*(check(client, t) for t in targets)))
