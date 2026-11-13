"""Streaming version of the battery-share p-chart.

Producer: replays complaints to topic `nhtsa.complaints` in filed-month order, keyed by nameplate so
each nameplate's events stay ordered within one partition.
Consumer: keeps per-nameplate state; when a nameplate's events move to a later month, it closes every
month in between (including months with no complaints), evaluates the p-chart rule against the trailing
baseline, and publishes alerts to `battery.alerts`. The rule is identical to the batch pipeline, so
streaming and batch alerts must match exactly (checked in tests/integration)."""
from __future__ import annotations

import json
import os
from collections import defaultdict, deque

import numpy as np
import pandas as pd

TOPIC_IN, TOPIC_OUT = "nhtsa.complaints", "battery.alerts"


class StreamingPChart:
    def __init__(self, window: int, min_periods: int, k: float, min_n: int, min_b: int):
        self.window, self.min_periods, self.k, self.min_n, self.min_b = window, min_periods, k, min_n, min_b
        self.current = {}                                   # model -> open month
        self.open = defaultdict(lambda: [0, 0])             # model -> [n, b] of the open month
        self.history = defaultdict(lambda: deque(maxlen=window))
        self.alerts: list[dict] = []

    def _close(self, model: str, month: pd.Timestamp):
        n, b = self.open.pop(model, [0, 0])
        h = self.history[model]
        if len(h) >= self.min_periods:
            sn, sb = sum(x[0] for x in h), sum(x[1] for x in h)
            if sn > 0:
                p_bar = sb / sn
                ucl = p_bar + self.k * np.sqrt(p_bar * (1 - p_bar) / n) if n > 0 else np.nan
                if n >= self.min_n and b >= self.min_b and n > 0 and b / n > ucl:
                    self.alerts.append({"model": model, "month": str(month.date()), "n": n, "battery": b,
                                        "p": round(b / n, 4), "p_bar": round(p_bar, 4), "ucl": round(float(ucl), 4)})
        h.append((n, b))

    def process(self, model: str, month: pd.Timestamp, battery: int):
        cur = self.current.get(model)
        if cur is None:
            self.current[model] = month
        elif month < cur:
            raise ValueError(f"out-of-order event for {model}: {month} < {cur}")
        while self.current[model] < month:                    # close finished months, including empty ones
            self._close(model, self.current[model])
            self.current[model] = self.current[model] + pd.offsets.MonthBegin(1)
        self.open[model][0] += 1
        self.open[model][1] += battery

    def flush(self, end: pd.Timestamp):
        for model in list(self.current):
            while self.current[model] <= end:
                self._close(model, self.current[model])
                self.current[model] = self.current[model] + pd.offsets.MonthBegin(1)


def events(stg: pd.DataFrame):
    e = stg[["odi", "my", "model", "filed", "comp_batt"]].copy()
    e["month"] = pd.to_datetime(e.filed).dt.to_period("M").dt.to_timestamp()
    return e.sort_values(["month", "model", "odi"])


def produce(stg: pd.DataFrame, bootstrap: str | None = None) -> int:
    from kafka import KafkaProducer
    p = KafkaProducer(bootstrap_servers=bootstrap or os.environ["KAFKA_BOOTSTRAP"], acks="all",
                      key_serializer=str.encode, value_serializer=lambda v: json.dumps(v).encode())
    n = 0
    for r in events(stg).itertuples(index=False):
        p.send(TOPIC_IN, key=r.model, value={"odi": int(r.odi), "my": int(r.my), "model": r.model,
                                              "month": str(r.month.date()), "battery": int(r.comp_batt)})
        n += 1
    p.flush()
    return n


def consume(params: dict, end: pd.Timestamp, expected: int, bootstrap: str | None = None, timeout_s: int = 120) -> list[dict]:
    from kafka import KafkaConsumer, KafkaProducer
    bs = bootstrap or os.environ["KAFKA_BOOTSTRAP"]
    c = KafkaConsumer(TOPIC_IN, bootstrap_servers=bs, auto_offset_reset="earliest", enable_auto_commit=False,
                      group_id="cellrel-pchart", value_deserializer=lambda b: json.loads(b), consumer_timeout_ms=timeout_s * 1000)
    chart = StreamingPChart(params["baseline_months"], params["min_baseline_months"], params["sigma_k"],
                            params["min_complaints"], params["min_battery"])
    seen = 0
    for msg in c:
        v = msg.value
        chart.process(v["model"], pd.Timestamp(v["month"]), v["battery"])
        seen += 1
        if seen == expected:
            break
    c.close()
    chart.flush(end)
    out = KafkaProducer(bootstrap_servers=bs, value_serializer=lambda v: json.dumps(v).encode())
    for a in chart.alerts:
        out.send(TOPIC_OUT, a)
    out.flush()
    return chart.alerts
