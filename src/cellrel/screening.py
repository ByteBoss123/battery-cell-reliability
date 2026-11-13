"""Early-life screening from the first 100 cycles: lifetime regression, split-conformal intervals,
early-failure classifier. Train/test splits are the dataset authors' own."""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.linear_model import ElasticNetCV, LogisticRegressionCV
from sklearn.metrics import accuracy_score, precision_score, recall_score, roc_auc_score
from sklearn.model_selection import KFold, StratifiedKFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

FEATURES = ["log_var_dq", "log_abs_min_dq", "log_skew_dq", "log_kurt_dq", "q2", "qmax_minus_q2", "q100", "fade_slope_91_100"]


def _err(y, p) -> dict:
    e = p - y
    return {"RMSE": round(float(np.sqrt((e ** 2).mean())), 1), "MAPE": round(float((np.abs(e) / y).mean() * 100), 1)}


def _models(cv_reg, cv_clf, seed):
    reg = make_pipeline(StandardScaler(), ElasticNetCV(l1_ratio=[.1, .5, .9, 1], cv=cv_reg, random_state=seed, max_iter=100000))
    clf = make_pipeline(StandardScaler(), LogisticRegressionCV(Cs=10, cv=cv_clf, l1_ratios=(0,), scoring="accuracy", max_iter=10000,
                                                               use_legacy_attributes=False))
    return reg, clf


def run(d: pd.DataFrame, early_cycles: int, level: float, seed: int, robustness_seeds: int = 20) -> dict:
    # Canonical row order (batch, barcode): unshuffled CV folds depend on it, so it is fixed here.
    d = d.sort_values(["lot", "barcode"]).reset_index(drop=True)
    tr, t1, t2 = (d[d.split == s] for s in ("train", "test1", "test2"))
    reg, clf = _models(5, 5, seed)
    reg.fit(tr[FEATURES], np.log10(tr.cycle_life))
    out = {"regression": {"test1": _err(t1.cycle_life, 10 ** reg.predict(t1[FEATURES])),
                          "test2_unseen_batch": _err(t2.cycle_life, 10 ** reg.predict(t2[FEATURES]))}}
    # variance-only baseline (replicates Severson et al.'s published variance model)
    u = np.polyfit(tr.log_var_dq, np.log10(tr.cycle_life), 1)
    out["variance_baseline"] = {s: _err(g.cycle_life, 10 ** np.polyval(u, g.log_var_dq)) for s, g in (("test1", t1), ("test2", t2))}
    # split conformal: calibrate on test1, evaluate coverage on the unseen batch
    cal = np.sort(np.abs(np.log10(t1.cycle_life) - reg.predict(t1[FEATURES])))
    q = cal[int(np.ceil((len(cal) + 1) * level)) - 1]
    p2 = reg.predict(t2[FEATURES])
    lo, hi = 10 ** (p2 - q), 10 ** (p2 + q)
    out["conformal"] = {"level": level, "coverage": round(float(((t2.cycle_life >= lo) & (t2.cycle_life <= hi)).mean()), 3),
                        "median_width_cycles": round(float(np.median(hi - lo)), 0)}
    # early-failure classifier
    y = lambda g: (g.cycle_life < early_cycles).astype(int)  # noqa: E731
    clf.fit(tr[FEATURES], y(tr))
    for name, g in (("test1", t1), ("test2_unseen_batch", t2)):
        pr = clf.predict_proba(g[FEATURES])[:, 1]
        ph = (pr >= 0.5).astype(int)
        out.setdefault("early_failure", {})[name] = {
            "n": len(g), "actual_early": int(y(g).sum()), "flagged": int(ph.sum()),
            "accuracy": round(accuracy_score(y(g), ph), 3), "precision": round(precision_score(y(g), ph, zero_division=0), 3),
            "recall": round(recall_score(y(g), ph, zero_division=0), 3),
            "roc_auc": None if y(g).nunique() < 2 else round(roc_auc_score(y(g), pr), 3)}
    # Robustness: refit with shuffled CV folds; a result that only holds for one fold split is not a result.
    rows = []
    for s in range(robustness_seeds):
        r2, c2 = _models(KFold(5, shuffle=True, random_state=s), StratifiedKFold(5, shuffle=True, random_state=s), seed)
        r2.fit(tr[FEATURES], np.log10(tr.cycle_life))
        c2.fit(tr[FEATURES], y(tr))
        ph = c2.predict(t1[FEATURES])
        rows.append({**{f"rmse_{k}": _err(g.cycle_life, 10 ** r2.predict(g[FEATURES]))["RMSE"] for k, g in (("test1", t1), ("test2", t2))},
                     "recall_test1": recall_score(y(t1), ph), "precision_test1": precision_score(y(t1), ph, zero_division=0),
                     "auc_test1": roc_auc_score(y(t1), c2.predict_proba(t1[FEATURES])[:, 1])})
    rb = pd.DataFrame(rows)
    out["cv_fold_robustness"] = {"n_fold_seeds": robustness_seeds,
                                 **{c: {"median": round(float(rb[c].median()), 3), "min": round(float(rb[c].min()), 3),
                                        "max": round(float(rb[c].max()), 3)} for c in rb.columns}}
    return out
