"""Declarative data-quality checks. A failed 'critical' check stops the pipeline."""
from __future__ import annotations

from dataclasses import asdict, dataclass

import duckdb


@dataclass
class Check:
    name: str
    sql: str                 # must return a single integer: number of violating rows
    severity: str = "critical"


@dataclass
class Result:
    name: str
    severity: str
    violations: int

    @property
    def passed(self) -> bool:
        return self.violations == 0


class QualityError(RuntimeError):
    pass


def run_checks(con: duckdb.DuckDBPyConnection, checks: list[Check]) -> list[Result]:
    results = [Result(c.name, c.severity, int(con.execute(c.sql).fetchone()[0])) for c in checks]
    con.execute("CREATE OR REPLACE TABLE dq_results (name VARCHAR, severity VARCHAR, violations BIGINT, passed BOOLEAN)")
    con.executemany("INSERT INTO dq_results VALUES (?, ?, ?, ?)", [(r.name, r.severity, r.violations, r.passed) for r in results])
    failed = [r for r in results if r.severity == "critical" and not r.passed]
    if failed:
        raise QualityError("critical data-quality checks failed: " + ", ".join(f"{r.name}={r.violations}" for r in failed))
    return results


def as_records(results: list[Result]) -> list[dict]:
    return [asdict(r) | {"passed": r.passed} for r in results]
