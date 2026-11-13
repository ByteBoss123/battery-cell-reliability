import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def metrics():
    """Run the full pipeline once per test session and return metrics.json."""
    from cellrel.pipeline import run
    return json.loads(json.dumps(run(), default=float))


@pytest.fixture(scope="session")
def golden():
    return json.load(open(ROOT / "tests" / "golden_v1.json"))


@pytest.fixture(scope="session")
def duck(metrics):
    """Read-only warehouse connection, opened only after the pipeline has (re)built the file."""
    import duckdb

    from cellrel.config import Paths
    return duckdb.connect(str(Paths().warehouse), read_only=True)
