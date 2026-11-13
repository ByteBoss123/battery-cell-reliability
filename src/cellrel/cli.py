"""Command line entry point: `cellrel run` (full pipeline) or `cellrel ingest-nhtsa` (live API pull)."""
from __future__ import annotations

import argparse
import logging


def main(argv=None):
    ap = argparse.ArgumentParser(prog="cellrel")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("run", help="build warehouse, run all analyses, write outputs/")
    sub.add_parser("figures", help="render figures from outputs/")
    sub.add_parser("publish-mysql", help="publish staging tables and marts to MySQL ($MYSQL_URL) and check parity")
    sub.add_parser("publish-mongo", help="publish complaint/recall documents to MongoDB ($MONGO_URI) and check parity")
    sub.add_parser("stream-kafka", help="replay complaints through Kafka ($KAFKA_BOOTSTRAP) and run the streaming p-chart")
    ing = sub.add_parser("ingest-nhtsa", help="pull a fresh complaints/recalls snapshot from api.nhtsa.gov")
    ing.add_argument("--out", default="data/raw")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if a.cmd == "run":
        from .pipeline import run
        run()
    elif a.cmd == "figures":
        from .figures import render
        render()
    elif a.cmd in ("publish-mysql", "publish-mongo", "stream-kafka"):
        import json

        import duckdb

        from .config import Paths, load_params
        duck = duckdb.connect(str(Paths().warehouse), read_only=True)
        if a.cmd == "publish-mysql":
            from .sinks import mysql_sink
            out = mysql_sink.publish(duck, mysql_sink.connect())
        elif a.cmd == "publish-mongo":
            from .sinks import mongo_sink
            out = mongo_sink.publish(duck, mongo_sink.client())
        else:
            from .streaming import kafka_stream as ks
            stg = duck.execute("SELECT * FROM stg_complaints").df()
            n = ks.produce(stg)
            alerts = ks.consume(load_params()["field"]["alerting"], ks.events(stg).month.max(), n)
            out = {"events": n, "alerts": alerts}
        print(json.dumps(out, indent=1, default=str))
        if not all(v for k, v in (out.get("parity") or {}).items() if k.endswith("_match")):
            raise SystemExit("parity check failed")
    else:
        from pathlib import Path

        from .ingest.nhtsa import NhtsaClient
        comp, rec = NhtsaClient().pull()
        Path(a.out).mkdir(parents=True, exist_ok=True)
        comp.sort_values(["model", "my", "odi"]).to_csv(Path(a.out) / "nhtsa_complaints_compact.csv", index=False)
        rec.sort_values(["canon", "my", "campaign"]).to_csv(Path(a.out) / "nhtsa_recalls.csv", index=False)


if __name__ == "__main__":
    main()
