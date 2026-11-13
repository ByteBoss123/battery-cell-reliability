"""Deviation from cell specification: which test policies charge above the datasheet's recommended
fast-charge current, and what that costs in life (Weibull AFT, controlling for test batch)."""
from __future__ import annotations

import numpy as np
import pandas as pd
from lifelines import WeibullAFTFitter


def spec_deviation(cells: pd.DataFrame, spec: dict) -> dict:
    max_c = spec["recommended_fast_charge_a"] / spec["nominal_capacity_ah"]       # 5 A / 1.1 Ah = 4.55C
    d = cells.assign(peak_c=cells[["C1", "C2"]].max(axis=1))
    d["above_spec"] = (d.peak_c > max_c).astype(int)
    X = pd.get_dummies(d[["cycle_life", "above_spec", "lot"]], columns=["lot"], drop_first=True, dtype=int)
    s = WeibullAFTFitter().fit(X, "cycle_life").summary.loc[("lambda_", "above_spec")]
    by = d.groupby("above_spec").cycle_life.agg(["size", "median"])
    return {
        "max_recommended_c_rate": round(max_c, 3),
        "cells_above_spec": int(d.above_spec.sum()), "cells_total": len(d),
        "policies_above_spec": int(d.loc[d.above_spec == 1, "policy"].nunique()),
        "median_life_within_spec": float(by.loc[0, "median"]), "median_life_above_spec": float(by.loc[1, "median"]),
        "life_ratio_above_vs_within_batch_adjusted": float(s["exp(coef)"]),
        "ci95": [float(s["exp(coef) lower 95%"]), float(s["exp(coef) upper 95%"])], "p": float(s["p"]),
        "initial_capacity_vs_nominal": {"median_q2_ah": float(np.median(d.q2)), "nominal_ah": spec["nominal_capacity_ah"],
                                         "cells_below_nominal": int((d.q2 < spec["nominal_capacity_ah"]).sum())},
    }
