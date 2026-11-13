"""Severson et al. (2019) cell data: SI Table 9 joined to per-cell Q(V) arrays (cycles 2-100)."""
from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

SPLITS = {"Train": "train", "Prim. Test": "test1", "Sec. test": "test2", "Sec. Test": "test2"}
POLICY = re.compile(r"([\d.]+)C\(([\d.]+)%\)-([\d.]+)C")


def parse_policy(p: str) -> tuple[float, float, float]:
    m = POLICY.fullmatch(p.strip())
    if not m:
        raise ValueError(f"unparseable charging policy: {p!r}")
    return float(m[1]), float(m[2]), float(m[3])


def early_life_features(a: np.ndarray) -> dict:
    """a: 1000 voltage points x 99 cycles (cycle n in column n-2)."""
    dq = a[:, 98] - a[:, 8]                       # Q100(V) - Q10(V)
    qd = a.max(axis=0)                            # discharge capacity per cycle
    return dict(
        log_var_dq=np.log10(np.var(dq)), log_abs_min_dq=np.log10(abs(dq.min())), mean_dq=dq.mean(),
        log_skew_dq=np.log10(abs(stats.skew(dq))), log_kurt_dq=np.log10(abs(stats.kurtosis(dq, fisher=False))),
        q2=qd[0], q100=qd[98], qmax_minus_q2=qd.max() - qd[0],
        fade_slope_2_100=np.polyfit(np.arange(2, 101), qd, 1)[0],
        fade_slope_91_100=np.polyfit(np.arange(91, 101), qd[89:], 1)[0])


def build_cells(raw: Path) -> pd.DataFrame:
    t9 = pd.read_csv(raw / "severson_et_al_SI_table9.csv", encoding="utf-8-sig")
    t9.columns = ["barcode", "dataset", "batch_date", "cycle_life", "policy"]
    t9["split"] = t9["dataset"].map(SPLITS)
    if t9["split"].isna().any():
        raise ValueError(f"unknown dataset labels: {t9.loc[t9.split.isna(), 'dataset'].unique()}")
    t9["idx"] = t9.groupby("split").cumcount() + 1
    arrays = raw / "severson_arrays"
    for s in ("train", "test1", "test2"):      # ordering contract with the author-exported files
        cl = pd.read_csv(arrays / f"cycle_lives/{s}_cycle_lives.csv", header=None)[0].to_numpy()
        if not (t9.loc[t9.split == s, "cycle_life"].to_numpy() == cl).all():
            raise ValueError(f"SI Table 9 order does not match exported cycle lives for {s}")
    t9["lot"] = pd.to_datetime(t9["batch_date"], format="%m/%d/%y").dt.strftime("%Y-%m-%d")
    t9[["C1", "Q1", "C2"]] = pd.DataFrame(t9["policy"].map(parse_policy).tolist(), index=t9.index)
    t9["t80_min"] = 60 * (t9.Q1 / 100 / t9.C1 + (80 - t9.Q1) / 100 / t9.C2)
    feats = [dict(barcode=r.barcode, **early_life_features(np.loadtxt(arrays / f"{r.split}/cell{r.idx}.csv", delimiter=",")))
             for r in t9.itertuples()]
    return t9.drop(columns="idx").merge(pd.DataFrame(feats), on="barcode")
