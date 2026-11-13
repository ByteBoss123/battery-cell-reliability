"""Publish warehouse staging tables and marts to MySQL (relational serving layer) and verify parity."""
from __future__ import annotations

import os

import duckdb
import pandas as pd

DDL = {
    "stg_complaints": """CREATE TABLE stg_complaints (
        odi BIGINT NOT NULL, my SMALLINT NOT NULL, model CHAR(1) NOT NULL, filed DATE NOT NULL, incident DATE NULL,
        age_months SMALLINT NULL, comp_batt TINYINT NOT NULL, text_batt TINYINT NOT NULL, fire TINYINT NOT NULL,
        crash TINYINT NOT NULL, injuries SMALLINT NOT NULL,
        PRIMARY KEY (odi, my), KEY ix_model_filed (model, filed), KEY ix_model_incident (model, incident)) ENGINE=InnoDB""",
    "mart_battery_monthly_filed": """CREATE TABLE mart_battery_monthly_filed (
        model CHAR(1) NOT NULL, month DATE NOT NULL, complaints INT NOT NULL, batt INT NOT NULL, batt_broad INT NOT NULL,
        PRIMARY KEY (model, month)) ENGINE=InnoDB""",
    "recall_units": """CREATE TABLE recall_units (
        campaign VARCHAR(12) PRIMARY KEY, units_affected INT NOT NULL, report_date DATE NOT NULL) ENGINE=InnoDB""",
}
COLUMNS = {"stg_complaints": ["odi", "my", "model", "filed", "incident", "age_months", "comp_batt", "text_batt", "fire", "crash", "injuries"],
           "mart_battery_monthly_filed": ["model", "month", "complaints", "batt", "batt_broad"],
           "recall_units": ["campaign", "units_affected", "report_date"]}
SOURCE = {"stg_complaints": "SELECT * FROM stg_complaints", "mart_battery_monthly_filed": "SELECT * FROM mart_battery_monthly_filed",
          "recall_units": "SELECT * FROM raw_recall_units"}


def connect(url: str | None = None):
    import pymysql
    url = url or os.environ.get("MYSQL_URL", "mysql://cellrel:cellrel@127.0.0.1:3306/cellrel")
    rest = url.split("://", 1)[1]
    cred, host = rest.split("@", 1)
    user, pw = cred.split(":", 1)
    hostport, db = host.split("/", 1)
    h, p = (hostport.split(":") + ["3306"])[:2]
    return pymysql.connect(host=h, port=int(p), user=user, password=pw, database=db, autocommit=False)


def _rows(df: pd.DataFrame, cols: list[str]):
    out = df[cols].astype(object).where(df[cols].notna(), None)
    for c in cols:
        if pd.api.types.is_datetime64_any_dtype(df[c]):
            out[c] = df[c].dt.date.astype(object).where(df[c].notna(), None)
    return [tuple(r) for r in out.itertuples(index=False)]


def publish(duck: duckdb.DuckDBPyConnection, mysql_conn) -> dict:
    """Idempotent: drop + recreate + bulk insert in one transaction per table, then parity checks."""
    cur = mysql_conn.cursor()
    loaded = {}
    for table, ddl in DDL.items():
        df = duck.execute(SOURCE[table]).df()
        cur.execute(f"DROP TABLE IF EXISTS {table}")
        cur.execute(ddl)
        cols = COLUMNS[table]
        cur.executemany(f"INSERT INTO {table} ({','.join(cols)}) VALUES ({','.join(['%s'] * len(cols))})", _rows(df, cols))
        mysql_conn.commit()
        loaded[table] = len(df)
    return {"loaded": loaded, "parity": parity(duck, mysql_conn)}


def parity(duck, mysql_conn) -> dict:
    """The same aggregate computed in both engines must agree exactly."""
    cur = mysql_conn.cursor()
    cur.execute("SELECT model, COUNT(*), SUM(comp_batt), SUM(fire * GREATEST(comp_batt, text_batt)) FROM stg_complaints GROUP BY model ORDER BY model")
    m = [tuple(int(x) if not isinstance(x, str) else x for x in r) for r in cur.fetchall()]
    d = [tuple(r) for r in duck.execute("SELECT model, count(*), sum(comp_batt), sum(fire * batt_broad) FROM stg_complaints GROUP BY model ORDER BY model").fetchall()]
    cur.execute("SELECT COUNT(*), SUM(batt) FROM mart_battery_monthly_filed")
    mm = tuple(int(x) for x in cur.fetchone())
    dm = tuple(int(x) for x in duck.execute("SELECT count(*), sum(batt) FROM mart_battery_monthly_filed").fetchone())
    return {"by_model_match": m == [tuple(int(x) if not isinstance(x, str) else x for x in r) for r in d],
            "monthly_mart_match": mm == dm, "mysql_by_model": m}
