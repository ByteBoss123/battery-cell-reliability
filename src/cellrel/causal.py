"""Corrective-action verification: Poisson difference-in-differences and observed/expected ratios."""
from __future__ import annotations

import numpy as np
import pandas as pd
import statsmodels.api as sm
import statsmodels.formula.api as smf
from scipy import stats


def poisson_did(panel: pd.DataFrame) -> dict:
    """panel columns: n (count per period), treated (0/1), post (0/1). HC0-robust errors."""
    fit = smf.glm("n ~ treated * post", panel, family=sm.families.Poisson()).fit(cov_type="HC0")
    ci = np.exp(fit.conf_int().loc["treated:post"])
    rates = panel.groupby(["treated", "post"]).n.mean()
    return {"rate_ratio": float(np.exp(fit.params["treated:post"])), "ci95": [float(ci[0]), float(ci[1])],
            "p": float(fit.pvalues["treated:post"]),
            "treated_pre": float(rates[(1, 0)]), "treated_post": float(rates[(1, 1)]),
            "control_pre": float(rates[(0, 0)]), "control_post": float(rates[(0, 1)])}


def observed_over_expected(observed: int, expected: float) -> dict:
    """O/E with an exact (Garwood) Poisson interval on the observed count."""
    lo = stats.chi2.ppf(0.025, 2 * observed) / 2 if observed > 0 else 0.0
    hi = stats.chi2.ppf(0.975, 2 * observed + 2) / 2
    return {"observed": observed, "expected": expected, "oe": observed / expected, "ci95": [lo / expected, hi / expected]}
