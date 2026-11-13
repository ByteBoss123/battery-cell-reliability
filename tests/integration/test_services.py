"""Integration tests against real MySQL, MongoDB and Kafka. Skipped unless the service URL is set;
CI (.github/workflows/ci.yml) starts all three as service containers."""
import pandas as pd

from cellrel.config import load_params

from .conftest import needs


@needs("MYSQL_URL")
def test_mysql_publish_and_parity(duck):
    from cellrel.sinks import mysql_sink
    con = mysql_sink.connect()
    out = mysql_sink.publish(duck, con)
    assert out["loaded"]["stg_complaints"] == 11051
    assert out["parity"]["by_model_match"] and out["parity"]["monthly_mart_match"]
    again = mysql_sink.publish(duck, con)                       # idempotent rerun
    assert again["loaded"] == out["loaded"]


@needs("MONGO_URI")
def test_mongo_publish_and_parity(duck):
    from cellrel.sinks import mongo_sink
    cli = mongo_sink.client()
    cli.drop_database("cellrel_test")
    out = mongo_sink.publish(duck, cli, "cellrel_test")
    assert out["complaints"] == 11051 and out["parity"]["by_model_match"]
    again = mongo_sink.publish(duck, cli, "cellrel_test")       # upserts: no duplicates on rerun
    assert again["complaints"] == 11051 and again["upserted"] == 0


@needs("KAFKA_BOOTSTRAP")
def test_kafka_streaming_matches_batch(duck, tmp_path):
    from cellrel.streaming import kafka_stream as ks
    stg = duck.execute("SELECT * FROM stg_complaints").df()
    n = ks.produce(stg)
    alerts = ks.consume(load_params()["field"]["alerting"], ks.events(stg).month.max(), n)
    batch = duck.execute("SELECT model, month, batt, complaints FROM mart_battery_monthly_filed").df()
    assert n == 11051 and len(batch) > 0
    from cellrel.config import Paths
    chart = pd.read_csv(Paths().outputs / "tables" / "pchart_monthly.csv")
    expected = sorted(map(tuple, chart[chart.alert == 1][["model", "month"]].astype(str).to_numpy()))
    assert sorted((a["model"], a["month"]) for a in alerts) == expected
