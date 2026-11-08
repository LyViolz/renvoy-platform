from __future__ import annotations

import os

import pytest

from renvoy_status import store


@pytest.fixture
def engine(tmp_path):
    # CI also runs the suite against a real Postgres via TEST_DATABASE_URL.
    url = os.environ.get("TEST_DATABASE_URL") or f"sqlite:///{tmp_path / 'test.db'}"
    eng = store.make_engine(url)
    store.metadata.drop_all(eng)
    store.init_db(eng)
    yield eng
    store.metadata.drop_all(eng)
    eng.dispose()
