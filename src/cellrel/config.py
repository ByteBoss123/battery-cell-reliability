"""Configuration and project paths."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Paths:
    root: Path = ROOT

    @property
    def raw(self) -> Path:
        return self.root / "data" / "raw"

    @property
    def warehouse(self) -> Path:
        return self.root / "data" / "warehouse.duckdb"

    @property
    def outputs(self) -> Path:
        return self.root / "outputs"

    @property
    def config(self) -> Path:
        return self.root / "config" / "params.yaml"


def load_params(path: Path | None = None) -> dict:
    path = path or Paths().config
    with open(path) as fh:
        return yaml.safe_load(fh)


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()
