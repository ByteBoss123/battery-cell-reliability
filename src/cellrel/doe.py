"""Response-surface DOE with blocking, pure-error lack-of-fit, and an optimum restricted to the tested region."""
from __future__ import annotations

import numpy as np
import pandas as pd
import statsmodels.api as sm
import statsmodels.formula.api as smf
from scipy import stats
from scipy.spatial import cKDTree

RSM = "ly ~ C(lot) + C1 + Q1 + C2 + C1:Q1 + C1:C2 + Q1:C2 + I(C1**2) + I(C2**2) + I(Q1**2)"


def fit_rsm(d: pd.DataFrame):
    d = d.assign(ly=np.log10(d.cycle_life))
    return smf.ols(RSM, d).fit(), d


def lack_of_fit(model, d: pd.DataFrame, group: str = "policy") -> dict:
    g = d.groupby(group)["ly"]
    sse_pe = float(((d.ly - g.transform("mean")) ** 2).sum())
    df_pe = len(d) - d[group].nunique()
    df_lof = model.df_resid - df_pe
    f = ((model.ssr - sse_pe) / df_lof) / (sse_pe / df_pe)
    return {"F": float(f), "p": float(1 - stats.f.cdf(f, df_lof, df_pe)), "df_lof": int(df_lof), "df_pe": int(df_pe),
            "replicated_policies": int((d[group].value_counts() > 1).sum())}


def anova(model) -> pd.DataFrame:
    return sm.stats.anova_lm(model, typ=2)


def best_policy_near_tested(model, d: pd.DataFrame, t80: tuple[float, float], radius: float, block: str) -> dict:
    grid = pd.DataFrame([(c1, q1, c2) for c1 in np.arange(3, 8.01, .1) for q1 in range(5, 76) for c2 in np.arange(3, 6.01, .1)],
                        columns=["C1", "Q1", "C2"])
    grid["t80_min"] = 60 * (grid.Q1 / 100 / grid.C1 + (80 - grid.Q1) / 100 / grid.C2)
    grid = grid[grid.t80_min.between(*t80)]
    obs = d[["C1", "Q1", "C2"]].drop_duplicates().to_numpy()
    sc = obs.std(axis=0)
    dist, _ = cKDTree(obs / sc).query(grid[["C1", "Q1", "C2"]].to_numpy() / sc)
    grid = grid[dist < radius].assign(lot=block)
    grid["pred_life"] = 10 ** model.predict(grid)
    return grid.sort_values("pred_life").iloc[-1][["C1", "Q1", "C2", "t80_min", "pred_life"]].astype(float).round(2).to_dict()
