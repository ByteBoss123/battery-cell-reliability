"""Command line entry point: `cellrel run` (full pipeline) or `cellrel ingest-nhtsa` (live API pull)."""
from __future__ import annotations

import argparse
import logging


def main(argv=None):
    ap = argparse.ArgumentParser(prog="cellrel")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("run", help="build warehouse, run all analyses, write outputs/")
    sub.add_parser("figures", help="render figures from outputs/")
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
    else:
        from pathlib import Path

        from .ingest.nhtsa import NhtsaClient
        comp, rec = NhtsaClient().pull()
        Path(a.out).mkdir(parents=True, exist_ok=True)
        comp.sort_values(["model", "my", "odi"]).to_csv(Path(a.out) / "nhtsa_complaints_compact.csv", index=False)
        rec.sort_values(["canon", "my", "campaign"]).to_csv(Path(a.out) / "nhtsa_recalls.csv", index=False)


if __name__ == "__main__":
    main()
