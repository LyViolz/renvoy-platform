"""One probe round: check every target, store the results, prune old rows.

Runs as a Kubernetes CronJob (`python -m renvoy_status.prober`). A failing
target is data, not a job failure: the job only fails when it cannot probe or
cannot write to the database.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from datetime import UTC, datetime, timedelta

from . import store
from .config import Settings, load_targets
from .probe import check_all

log = logging.getLogger("renvoy_status.prober")


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    settings = Settings.from_env()
    targets = load_targets(settings.targets_file)
    engine = store.make_engine(settings.database_url)
    try:
        store.init_db(engine)
        results = asyncio.run(check_all(targets, settings.probe_timeout))
        store.record(engine, results)
        pruned = store.prune(engine, datetime.now(UTC) - timedelta(days=settings.retention_days))
    finally:
        engine.dispose()

    for r in results:
        log.info(
            json.dumps(
                {
                    "event": "check",
                    "target": r.target,
                    "ok": r.ok,
                    "status_code": r.status_code,
                    "latency_ms": r.latency_ms,
                    "error": r.error,
                }
            )
        )
    failing = [r.target for r in results if not r.ok]
    log.info(
        json.dumps(
            {"event": "round", "checked": len(results), "failing": failing, "pruned": pruned}
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
