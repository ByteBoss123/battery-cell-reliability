"""NHTSA complaints/recalls ingestion client (api.nhtsa.gov).

Design points:
- NHTSA spells a nameplate differently by year ("BOLT" vs "BOLT EV", "MODEL Y 5-SEAT",
  "LEAF BEV"), so model names are discovered per (make, year) from the products endpoint and
  matched with a regex instead of being hard-coded.
- The API rate-limits by returning HTTP 400/429/5xx; requests retry with exponential backoff.
  A 400 whose body parses as an empty result set is a real "no data" answer, not an error.
- Records are deduplicated on (odiNumber, model year) because one complaint can be listed
  under several name variants.
- Output is a flat, typed record list; writing is idempotent (same input -> same file).
"""
from __future__ import annotations

import logging
import re
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass

import pandas as pd

log = logging.getLogger(__name__)
BASE = "https://api.nhtsa.gov"
COMPONENT_BATTERY = re.compile(r"TRACTION BATTERY|PROPULSION SYSTEM", re.I)
TEXT_BATTERY = re.compile(r"\bbatter(y|ies)\b|high[- ]voltage", re.I)


@dataclass(frozen=True)
class Nameplate:
    code: str            # short code used downstream (B, K, L, 3, Y, I)
    make: str
    pattern: str         # regex over NHTSA model names
    years: tuple[int, int]


NAMEPLATES = [
    Nameplate("B", "chevrolet", r"^BOLT( EV| EUV)?$", (2017, 2023)),
    Nameplate("K", "hyundai", r"^KONA (EV|ELECTRIC)", (2019, 2023)),
    Nameplate("L", "nissan", r"^LEAF", (2011, 2023)),
    Nameplate("3", "tesla", r"^MODEL 3", (2017, 2023)),
    Nameplate("Y", "tesla", r"^MODEL Y", (2020, 2023)),
    Nameplate("I", "volkswagen", r"^ID\.?4", (2021, 2023)),
]


class NhtsaClient:
    def __init__(self, get: Callable[[str], tuple[int, dict | None]] | None = None,
                 max_retries: int = 4, backoff_s: float = 1.5, pause_s: float = 0.3):
        self._get = get or self._http_get
        self.max_retries, self.backoff_s, self.pause_s = max_retries, backoff_s, pause_s

    @staticmethod
    def _http_get(path: str) -> tuple[int, dict | None]:  # pragma: no cover - network
        import requests
        r = requests.get(BASE + path, timeout=30)
        try:
            return r.status_code, r.json()
        except ValueError:
            return r.status_code, None

    def get(self, path: str) -> dict:
        for attempt in range(self.max_retries):
            status, body = self._get(path)
            if status == 200 and body is not None:
                return body
            if status == 400 and body is not None and not body.get("results"):
                return {"count": 0, "results": []}          # NHTSA's "no data" response
            wait = self.backoff_s * 2 ** attempt
            log.warning("GET %s -> %s, retry %d in %.1fs", path, status, attempt + 1, wait)
            time.sleep(wait)
        raise RuntimeError(f"NHTSA request failed after {self.max_retries} attempts: {path}")

    def model_names(self, make: str, year: int, issue_type: str, pattern: str) -> list[str]:
        body = self.get(f"/products/vehicle/models?modelYear={year}&make={make}&issueType={issue_type}")
        rx = re.compile(pattern)
        return sorted({r["model"] for r in body.get("results", []) if rx.search(r["model"])})

    def _vehicle(self, kind: str, make: str, model: str, year: int) -> list[dict]:
        from urllib.parse import quote
        path = f"/{kind}?make={quote(make)}&model={quote(model)}&modelYear={year}"
        out = self.get(path).get("results", [])
        time.sleep(self.pause_s)
        return out

    def pull(self, nameplates: Iterable[Nameplate] = NAMEPLATES) -> tuple[pd.DataFrame, pd.DataFrame]:
        comp_rows, rec_rows, seen_c, seen_r = [], [], set(), set()
        for np_ in nameplates:
            for y in range(np_.years[0], np_.years[1] + 1):
                for name in self.model_names(np_.make, y, "c", np_.pattern):
                    for x in self._vehicle("complaints/complaintsByVehicle", np_.make, name, y):
                        key = (x["odiNumber"], y)
                        if key in seen_c:
                            continue
                        seen_c.add(key)
                        comp_rows.append(normalize_complaint(x, np_.code, y))
                for name in self.model_names(np_.make, y, "r", np_.pattern):
                    for x in self._vehicle("recalls/recallsByVehicle", np_.make, name, y):
                        key = (x["NHTSACampaignNumber"], y, np_.code)
                        if key in seen_r:
                            continue
                        seen_r.add(key)
                        rec_rows.append(normalize_recall(x, np_.code, y))
        return pd.DataFrame(comp_rows), pd.DataFrame(rec_rows)


def _ym(us_date: str | None) -> str:
    m = re.fullmatch(r"(\d{2})/(\d{2})/(\d{4})", us_date or "")
    return f"{m[3]}{m[1]}" if m else ""


def normalize_complaint(x: dict, code: str, my: int) -> dict:
    """Map one API complaint to the snapshot schema (no free text kept: privacy + size)."""
    return {
        "model": code, "my": my % 100, "odi": int(x["odiNumber"]),
        "incident_ym": _ym(x.get("dateOfIncident")), "filed_ym": _ym(x.get("dateComplaintFiled")),
        "flags": "".join(str(int(b)) for b in (
            bool(COMPONENT_BATTERY.search(x.get("components") or "")),
            bool(TEXT_BATTERY.search(x.get("summary") or "")),
            bool(x.get("fire")), bool(x.get("crash")))),
        "injuries": int(x.get("numberOfInjuries") or 0),
    }


def normalize_recall(x: dict, code: str, my: int) -> dict:
    text = f"{x.get('Component') or ''} {x.get('Summary') or ''}"
    return {"canon": code, "my": my, "campaign": x["NHTSACampaignNumber"], "report_date": x.get("ReportReceivedDate"),
            "component": x.get("Component"), "batt_text": int(bool(re.search(r"batter|high voltage|propulsion", text, re.I))),
            "summary": (x.get("Summary") or "")[:160]}
