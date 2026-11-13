"""Statistical process control: I-MR limits, EWMA, Western Electric rules, p-chart."""
from __future__ import annotations

import numpy as np
import pandas as pd


def imr_limits(phase1: np.ndarray, k: float = 3.0) -> dict:
    """Center line and sigma estimated from Phase I data via the average moving range (d2 = 1.128)."""
    phase1 = np.asarray(phase1, float)
    sigma = np.abs(np.diff(phase1)).mean() / 1.128
    cl = phase1.mean()
    return {"cl": cl, "sigma": sigma, "ucl": cl + k * sigma, "lcl": cl - k * sigma}


def ewma(x: np.ndarray, lam: float, start: float) -> np.ndarray:
    out, prev = np.empty(len(x)), start
    for i, v in enumerate(x):
        prev = lam * v + (1 - lam) * prev
        out[i] = prev
    return out


def ewma_halfwidth(sigma: float, lam: float, k: float = 3.0) -> float:
    """Asymptotic EWMA control-limit half-width."""
    return k * sigma * np.sqrt(lam / (2 - lam))


def western_electric(z: np.ndarray) -> dict[str, np.ndarray]:
    """Rule 1: one point beyond 3 sigma. Rule 2: 2 of 3 beyond 2 sigma on the same side.
    Rule 4: 8 consecutive points on the same side of the center line."""
    z = np.asarray(z, float)
    n = len(z)
    r1 = np.abs(z) > 3
    r2, r4 = np.zeros(n, bool), np.zeros(n, bool)
    for i in range(n):
        w3 = z[max(0, i - 2): i + 1]
        r2[i] = (w3 > 2).sum() >= 2 or (w3 < -2).sum() >= 2
        w8 = z[max(0, i - 7): i + 1]
        r4[i] = len(w8) == 8 and ((w8 > 0).all() or (w8 < 0).all())
    return {"rule1": r1, "rule2": r2, "rule4": r4}


def p_chart(defects: pd.Series, n: pd.Series, window: int, min_periods: int, k: float = 3.0) -> pd.DataFrame:
    """Rolling-baseline p-chart: the current period is compared with the pooled proportion of the
    previous `window` periods (current period excluded, so a spike cannot mask itself)."""
    p_bar = defects.shift(1).rolling(window, min_periods=min_periods).sum() / n.shift(1).rolling(window, min_periods=min_periods).sum()
    nz = n.replace(0, np.nan)
    ucl = p_bar + k * np.sqrt(p_bar * (1 - p_bar) / nz)
    return pd.DataFrame({"n": n, "defects": defects, "p": defects / nz, "p_bar": p_bar, "ucl": ucl})
