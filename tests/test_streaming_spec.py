"""Streaming p-chart must reproduce the batch alerts exactly; spec-deviation check is wired in."""
import pandas as pd

from cellrel.config import Paths, load_params
from cellrel.streaming.kafka_stream import StreamingPChart, events


def test_streaming_pchart_matches_batch(metrics, duck):
    p = load_params()["field"]["alerting"]
    stg = duck.execute("SELECT * FROM stg_complaints").df()
    ch = StreamingPChart(p["baseline_months"], p["min_baseline_months"], p["sigma_k"], p["min_complaints"], p["min_battery"])
    ev = events(stg)
    for r in ev.itertuples(index=False):
        ch.process(r.model, r.month, int(r.comp_batt))
    ch.flush(ev.month.max())
    batch = pd.read_csv(Paths().outputs / "tables" / "pchart_monthly.csv")
    expected = sorted(map(tuple, batch[batch.alert == 1][["model", "month"]].astype(str).to_numpy()))
    assert sorted((a["model"], a["month"]) for a in ch.alerts) == expected
    assert len(expected) == metrics["field"]["alerting_pchart"]["alert_months"]


def test_streaming_rejects_out_of_order_events():
    ch = StreamingPChart(12, 6, 3.0, 10, 3)
    ch.process("B", pd.Timestamp("2021-02-01"), 1)
    try:
        ch.process("B", pd.Timestamp("2021-01-01"), 1)
    except ValueError:
        return
    raise AssertionError("out-of-order event accepted")


def test_spec_deviation(metrics):
    s = metrics["cells"]["spec_deviation"]
    assert abs(s["max_recommended_c_rate"] - 5.0 / 1.1) < 1e-3 and s["cells_above_spec"] == 114
    assert s["ci95"][1] < 1.0
