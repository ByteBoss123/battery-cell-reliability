import numpy as np
import pandas as pd
import pytest

from cellrel import causal, spc
from cellrel.ingest.severson import parse_policy


def test_western_electric_rules_fire_on_constructed_patterns():
    z = np.zeros(20)
    z[3] = 3.5                         # rule 1
    z[8], z[10] = 2.4, 2.6             # rule 2 (2 of 3 beyond 2 sigma)
    z[12:20] = 0.5                     # rule 4 (8 in a row, same side)
    r = spc.western_electric(z)
    assert r["rule1"][3] and r["rule1"].sum() == 1
    assert r["rule2"][10]
    assert r["rule4"][19] and not r["rule4"][18]


def test_ewma_limits_hold_false_alarm_rate_in_control():
    rng = np.random.default_rng(0)
    x = rng.normal(0, 1, 200000)
    e = spc.ewma(x, 0.2, 0.0)
    hw = spc.ewma_halfwidth(1.0, 0.2, 3.0)
    assert (np.abs(e[100:]) > hw).mean() < 0.01


def test_pchart_excludes_current_period_from_baseline():
    n = pd.Series([100] * 15)
    d = pd.Series([2] * 14 + [30])
    ch = spc.p_chart(d, n, window=12, min_periods=6)
    assert ch.p_bar.iloc[-1] == pytest.approx(0.02) and ch.p.iloc[-1] > ch.ucl.iloc[-1]


def test_poisson_did_recovers_known_effect():
    rng = np.random.default_rng(1)
    rows = []
    for treated in (0, 1):
        for post in (0, 1):
            lam = 5.0 * (1.5 if post else 1.0) * (0.4 if treated and post else 1.0)
            rows += [{"treated": treated, "post": post, "n": v} for v in rng.poisson(lam, 400)]
    r = causal.poisson_did(pd.DataFrame(rows))
    assert r["ci95"][0] < 0.4 < r["ci95"][1]


def test_observed_over_expected_exact_interval():
    r = causal.observed_over_expected(9, 27.1)
    assert r["oe"] == pytest.approx(9 / 27.1)
    assert r["ci95"][0] == pytest.approx(0.1519, abs=1e-3) and r["ci95"][1] == pytest.approx(0.6305, abs=1e-3)


def test_policy_parser():
    assert parse_policy("5.4C(40%)-3.6C") == (5.4, 40.0, 3.6)
    with pytest.raises(ValueError):
        parse_policy("3-step")
