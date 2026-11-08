from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class Target:
    name: str
    url: str
    group: str = "General"
    expected_status: int = 200


def load_targets(path: str | Path) -> list[Target]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    targets = [Target(**item) for item in data.get("targets", [])]
    if not targets:
        raise ValueError(f"no targets defined in {path}")
    names = [t.name for t in targets]
    if len(names) != len(set(names)):
        raise ValueError("target names must be unique")
    return targets


@dataclass(frozen=True)
class Settings:
    database_url: str
    targets_file: str
    probe_timeout: float
    retention_days: int

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            database_url=os.environ.get("DATABASE_URL", "sqlite:///./status.db"),
            targets_file=os.environ.get("TARGETS_FILE", "/config/targets.yaml"),
            probe_timeout=float(os.environ.get("PROBE_TIMEOUT_SECONDS", "10")),
            retention_days=int(os.environ.get("RETENTION_DAYS", "30")),
        )
