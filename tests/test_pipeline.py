"""End-to-end: quality gates pass and every published number is reproduced (golden regression)."""
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_quality_gates_and_manifest(metrics):
    man = json.load(open(ROOT / "outputs" / "run_manifest.json"))
    crit = [r for r in man["data_quality"] if r["severity"] == "critical"]
    assert crit and all(r["passed"] for r in crit)
    assert set(man["raw_sha256"]) >= {"nhtsa_complaints_compact.csv", "severson_et_al_SI_table9.csv"}


def test_cells_golden(metrics, golden):
    wb = {w["lot"]: w for w in metrics["cells"]["weibull_by_batch"]}
    for lot, b10 in golden["weibull_B10"].items():
        assert wb[lot]["B10"] == pytest.approx(b10, abs=1e-3)
    aft = metrics["cells"]["aft_policy_adjusted"]
    assert aft["lot_2017_06_30"]["ratio"] == pytest.approx(golden["aft_lot_2017_06_30"], abs=1e-4)
    assert aft["lot_2018_04_12"]["ratio"] == pytest.approx(golden["aft_lot_2018_04_12"], abs=1e-4)
    assert metrics["cells"]["doe"]["r2"] == pytest.approx(golden["doe_r2"], abs=1e-9)
    assert metrics["cells"]["doe"]["lack_of_fit"]["p"] == pytest.approx(golden["doe_lof_p"], abs=1e-9)
    assert metrics["cells"]["spc"]["q2"]["2018-04-12"]["ewma_alarm"] == golden["spc_q2_ewma_alarms_2018"]


def test_screening_golden(metrics, golden):
    s = metrics["cells"]["screening"]
    assert s["regression"]["test1"]["RMSE"] == golden["screen_rmse_test1"]
    assert s["regression"]["test2_unseen_batch"]["RMSE"] == golden["screen_rmse_test2"]
    assert s["conformal"]["coverage"] == golden["conformal_coverage"]
    assert {k: s["early_failure"]["test1"][k] for k in golden["clf_test1"]} == golden["clf_test1"]


def test_field_golden(metrics, golden):
    f = metrics["field"]
    assert f["n_complaints"] == golden["n_complaints"]
    assert round(f["bolt_fleet"]["per_1000"], 2) == golden["bolt_per_1000"]
    did = f["corrective_action_did"]["comp_batt|primary"]
    assert round(did["rate_ratio"], 3) == golden["did_primary_rr"] and did["p"] == pytest.approx(golden["did_primary_p"], rel=1e-9)
    pm = f["population_model"]
    sw = pm["scenarios"]["sales_weighted"]
    assert pm["observed_in_window"] == golden["pop_observed"]
    assert round(sw["shape_beta"], 2) == golden["pop_beta"] and round(sw["rate_per_1000_at_horizon"], 2) == golden["pop_rate_96"]
    assert round(sw["expected_no_remedy"], 1) == golden["pop_expected"] and round(sw["oe_oe"], 2) == golden["pop_oe"]
    a = f["alerting_pchart"]
    assert a["first_in_family_with_alert"] == golden["pchart_first_in_family"] and a["alert_months"] == golden["pchart_alert_months"]
