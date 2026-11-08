from __future__ import annotations

from pathlib import Path

import pytest

from renvoy_status.config import load_targets

SHIPPED_TARGETS = Path(__file__).resolve().parents[2] / "deploy/k8s/base/targets.yaml"


def test_shipped_targets_file_is_valid():
    targets = load_targets(SHIPPED_TARGETS)
    assert len(targets) >= 1
    assert all(t.url.startswith("https://") for t in targets)


def test_duplicate_names_are_rejected(tmp_path):
    path = tmp_path / "targets.yaml"
    path.write_text(
        "targets:\n  - {name: a, url: https://a.test}\n  - {name: a, url: https://b.test}\n"
    )
    with pytest.raises(ValueError, match="unique"):
        load_targets(path)


def test_empty_file_is_rejected(tmp_path):
    path = tmp_path / "targets.yaml"
    path.write_text("targets: []\n")
    with pytest.raises(ValueError, match="no targets"):
        load_targets(path)
