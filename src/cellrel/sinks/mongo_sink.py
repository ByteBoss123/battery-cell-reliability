"""Publish complaints and recalls to MongoDB as documents (NoSQL serving layer) and verify parity with
the warehouse using an aggregation pipeline."""
from __future__ import annotations

import os

import duckdb
import pandas as pd

from ..warehouse import MODEL_NAMES


def client(uri: str | None = None):
    from pymongo import MongoClient
    return MongoClient(uri or os.environ.get("MONGO_URI", "mongodb://127.0.0.1:27017"), serverSelectionTimeoutMS=5000)


def _dt(x):
    return None if pd.isna(x) else pd.Timestamp(x).to_pydatetime()


def complaint_docs(df: pd.DataFrame):
    for r in df.itertuples(index=False):
        yield {"_id": f"{r.odi}-{r.my}", "odi": int(r.odi), "model": r.model, "model_name": MODEL_NAMES[r.model],
               "model_year": int(r.my), "filed": _dt(r.filed), "incident": _dt(r.incident),
               "age_months": None if pd.isna(r.age_months) else int(r.age_months),
               "flags": {"component_battery": bool(r.comp_batt), "text_battery": bool(r.text_batt),
                         "fire": bool(r.fire), "crash": bool(r.crash)}, "injuries": int(r.injuries)}


def publish(duck: duckdb.DuckDBPyConnection, mongo, db_name: str = "cellrel") -> dict:
    from pymongo import ASCENDING, ReplaceOne
    db = mongo[db_name]
    comp = duck.execute("SELECT * FROM stg_complaints").df()
    rec = duck.execute("SELECT * FROM stg_recalls").df()
    ops = [ReplaceOne({"_id": d["_id"]}, d, upsert=True) for d in complaint_docs(comp)]   # idempotent upserts
    res = db.complaints.bulk_write(ops, ordered=False)
    db.complaints.create_index([("model", ASCENDING), ("filed", ASCENDING)])
    db.complaints.create_index([("flags.component_battery", ASCENDING)])
    rdocs = [{"_id": f"{r.campaign}-{r.model}-{r.my}", "campaign": r.campaign, "model": r.model, "model_year": int(r.my),
              "report_date": _dt(r.report_date), "component": r.component, "battery_related": bool(r.batt_text)}
             for r in rec.itertuples(index=False)]
    db.recalls.bulk_write([ReplaceOne({"_id": d["_id"]}, d, upsert=True) for d in rdocs], ordered=False)
    return {"complaints": db.complaints.count_documents({}), "recalls": db.recalls.count_documents({}),
            "upserted": res.upserted_count, "parity": parity(duck, db)}


def parity(duck, db) -> dict:
    pipeline = [{"$group": {"_id": "$model", "complaints": {"$sum": 1},
                            "batt": {"$sum": {"$cond": ["$flags.component_battery", 1, 0]}}}}, {"$sort": {"_id": 1}}]
    m = [(d["_id"], d["complaints"], d["batt"]) for d in db.complaints.aggregate(pipeline)]
    d = [tuple(int(x) if not isinstance(x, str) else x for x in r)
         for r in duck.execute("SELECT model, count(*), sum(comp_batt) FROM stg_complaints GROUP BY model ORDER BY model").fetchall()]
    return {"by_model_match": m == d, "mongo_by_model": m}
