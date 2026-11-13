"""End-to-end pipeline: ingest -> warehouse (quality gates) -> analyses -> outputs + run manifest."""
from __future__ import annotations

import json
import logging
import platform
from datetime import datetime, timezone

import numpy as np
import pandas as pd
from lifelines import WeibullAFTFitter
from scipy import stats

from . import __version__, causal, doe, screening, spc, warehouse
from .config import Paths, file_sha256, load_params
from .ingest.severson import build_cells
from .quality import as_records
from .reliability import bootstrap_b_life, fit_weibull, ks_pvalue, log_param_cov

log = logging.getLogger("cellrel")


# ------------------------------------------------------------------ cells
def cell_weibull(d: pd.DataFrame, draws: int, rng) -> list[dict]:
    rows = []
    for lot, g in [("ALL", d), *d.groupby("lot")]:
        x = g.cycle_life.to_numpy()
        f = fit_weibull(x)
        lo, hi = bootstrap_b_life(x, 0.10, draws, rng)
        rows.append({"lot": lot, "n": len(x), "shape_beta": f.shape, "scale_eta": f.scale, "B10": f.b_life(),
                     "B10_lo": lo, "B10_hi": hi, "KS_p": ks_pvalue(x, f)})
    return rows


def cell_aft(d: pd.DataFrame) -> dict:
    X = d[["cycle_life", "C1", "Q1", "C2"]].copy()
    for lot in sorted(d.lot.unique())[1:]:
        X[f"lot_{lot.replace('-', '_')}"] = (d.lot == lot).astype(int)
    s = WeibullAFTFitter().fit(X, "cycle_life").summary.loc["lambda_"]
    return {k: {"ratio": float(v["exp(coef)"]), "ci95": [float(v["exp(coef) lower 95%"]), float(v["exp(coef) upper 95%"])],
                "p": float(v["p"])} for k, v in s.iterrows() if k != "Intercept"}


def cell_spc(d: pd.DataFrame, p: dict) -> tuple[pd.DataFrame, dict]:
    import statsmodels.formula.api as smf
    d = d.copy()
    d["dq_resid"] = smf.ols("log_var_dq ~ C1 + Q1 + C2", d).fit().resid      # policy-adjusted degradation
    d = d.sort_values(["lot", "barcode"]).reset_index(drop=True)
    d["seq"] = np.arange(1, len(d) + 1)
    frames, summary = [], {}
    for metric in ("q2", "dq_resid"):
        lim = spc.imr_limits(d.loc[d.lot == p["phase1_batch"], metric], p["sigma_k"])
        x = d[metric].to_numpy()
        z = (x - lim["cl"]) / lim["sigma"]
        rules = spc.western_electric(z)
        e = spc.ewma(x, p["ewma_lambda"], lim["cl"])
        hw = spc.ewma_halfwidth(lim["sigma"], p["ewma_lambda"], p["sigma_k"])
        f = d[["seq", "barcode", "lot", "cycle_life"]].assign(
            metric=metric, value=x, CL=lim["cl"], UCL=lim["ucl"], LCL=lim["lcl"], ewma=e,
            ewma_UCL=lim["cl"] + hw, ewma_LCL=lim["cl"] - hw, **{k: v.astype(int) for k, v in rules.items()},
            ewma_alarm=(np.abs(e - lim["cl"]) > hw).astype(int), ewma_upper=(e > lim["cl"] + hw).astype(int),
            ewma_lower=(e < lim["cl"] - hw).astype(int))
        frames.append(f)
        summary[metric] = f.groupby("lot")[["rule1", "rule2", "rule4", "ewma_alarm", "ewma_upper", "ewma_lower"]].sum().to_dict("index")
    out = pd.concat(frames)
    flagged = out.assign(any=out[["rule1", "rule2", "rule4", "ewma_alarm"]].max(axis=1)).groupby("barcode")["any"].max()
    life = d.set_index("barcode").cycle_life
    mw = stats.mannwhitneyu(life[flagged == 1], life[flagged == 0])
    summary["flagged_vs_life"] = {"flagged": int(flagged.sum()), "median_flagged": float(life[flagged == 1].median()),
                                  "median_unflagged": float(life[flagged == 0].median()), "mannwhitney_p": float(mw.pvalue)}
    return out, summary


def cell_doe(d: pd.DataFrame, p: dict) -> dict:
    m, dd = doe.fit_rsm(d)
    return {"r2": float(m.rsquared), "adj_r2": float(m.rsquared_adj), "lack_of_fit": doe.lack_of_fit(m, dd),
            "pvalues": {k: float(v) for k, v in m.pvalues.items()},
            "anova": doe.anova(m).round(5).reset_index().rename(columns={"index": "term"}).to_dict("records"),
            "best_policy_near_tested": doe.best_policy_near_tested(m, dd, tuple(p["target_t80_min"]), p["near_tested_radius"],
                                                                   sorted(d.lot.unique())[0]),
            "best_observed_10min": d[d.t80_min.round(1).between(*p["target_t80_min"])].groupby("policy").cycle_life.mean()
                                   .sort_values().tail(3).round(1).to_dict()}


# ------------------------------------------------------------------ field
def _month_series(c: pd.DataFrame, months, col="comp_batt") -> np.ndarray:
    m = c[c[col] == 1].dropna(subset=["incident"])
    return pd.to_datetime(m.incident).dt.to_period("M").dt.to_timestamp().value_counts().reindex(months, fill_value=0).to_numpy()


def corrective_action_did(c: pd.DataFrame, p: dict) -> tuple[dict, pd.DataFrame]:
    months = pd.date_range(p["pre"][0], p["post_sensitivity_end"], freq="MS")
    res, panel_out = {}, None
    for col in ("comp_batt", "batt_broad"):
        tr = c[(c.model == p["treated"]["model"]) & (c.my <= p["treated"]["max_my"])]
        ct = c[(c.model == p["control"]["model"]) & (c.my <= p["control"]["max_my"])]
        panel = pd.concat([pd.DataFrame({"month": months, "n": _month_series(tr, months, col), "treated": 1}),
                           pd.DataFrame({"month": months, "n": _month_series(ct, months, col), "treated": 0})])
        panel["period"] = np.where(panel.month < p["rollout_excluded"][0], "pre",
                                   np.where(panel.month <= p["rollout_excluded"][1], "rollout", "post"))
        if col == "comp_batt":
            panel_out = panel
        for tag, end in (("primary", p["post_primary_end"]), ("sensitivity", p["post_sensitivity_end"])):
            q = panel[(panel.period != "rollout") & (panel.month <= end)].assign(post=lambda x: (x.period == "post").astype(int))
            res[f"{col}|{tag}"] = causal.poisson_did(q)
    return res, panel_out


def population_model(c: pd.DataFrame, p: dict, rng) -> dict:
    """Censored Weibull on a recalled cohort fit before the recall; projects the no-remedy failure
    count in a post-remedy window and compares with what was observed."""
    mys, units = p["model_years"], p["units"]
    f = c[(c.model == "B") & c.my.isin(mys) & (c.comp_batt == 1)].dropna(subset=["incident"]).copy()
    f["incident"] = pd.to_datetime(f.incident)
    censor = pd.Timestamp(p["censor_date"])
    w0, w1 = (pd.Timestamp(x) for x in p["eval_window"])

    def age(ts, my):
        return (ts.year - (my - 1)) * 12 + ts.month - 10

    pre = f[f.incident <= censor]   # incident dates are month starts, so <= censor date keeps all of Oct 2020
    fail_t = ((pre.incident.dt.year - (pre.my - 1)) * 12 + pre.incident.dt.month - 10).to_numpy(float) + 0.5
    observed = int(((f.incident >= w0) & (f.incident <= w1)).sum())
    sales = np.array(p["my_weights_sales"], float)
    scenarios = {"sales_weighted": sales / sales.sum(), "equal_split": np.ones(3) / 3,
                 "all_oldest_MY": np.array([1., 0, 0]), "all_newest_MY": np.array([0, 0, 1.])}
    out = {"cohort_units": units, "pre_recall_failures": int(len(pre)), "observed_in_window": observed, "scenarios": {}}
    for name, w in scenarios.items():
        ct = np.array([age(censor, m) + 0.5 for m in mys])
        cw = units * w - np.array([(pre.my == m).sum() for m in mys])
        keep = cw > 0
        fit = fit_weibull(fail_t, ct[keep], cw[keep])
        cov = log_param_cov(fit, fail_t, ct[keep], cw[keep])

        def expected(k, eta, w=w):
            return float(sum(units * wi * (stats.weibull_min.cdf(age(w1, m) + 1, k, scale=eta) - stats.weibull_min.cdf(age(w0, m), k, scale=eta))
                             for m, wi in zip(mys, w, strict=True)))
        draws = np.exp(rng.multivariate_normal(np.log([fit.shape, fit.scale]), cov, 2000))
        exp_draws = np.array([expected(k, e) for k, e in draws])
        h = p["horizon_months"]
        rate_draws = np.array([stats.weibull_min.cdf(h, k, scale=e) for k, e in draws]) * 1000
        E = expected(fit.shape, fit.scale)
        se_logk = float(np.sqrt(cov[0, 0]))
        out["scenarios"][name] = {
            "shape_beta": fit.shape, "shape_ci95": list(np.exp(np.log(fit.shape) + np.array([-1.96, 1.96]) * se_logk)),
            "scale_months": fit.scale, "rate_per_1000_at_horizon": float(fit.cdf(h) * 1000),
            "rate_ci95": list(np.percentile(rate_draws, [2.5, 97.5])), "units_affected_at_horizon": float(units * fit.cdf(h)),
            "expected_no_remedy": E, "expected_ci95": list(np.percentile(exp_draws, [2.5, 97.5])),
            **{f"oe_{k}": v for k, v in causal.observed_over_expected(observed, E).items() if k in ("oe", "ci95")}}
    return out


def field_age_weibull(c: pd.DataFrame, horizon: int, snapshot: pd.Timestamp, names: dict) -> list[dict]:
    rows = []
    for m, g in c[(c.comp_batt == 1) & c.age_months.notna()].groupby("model"):
        observed_months = (snapshot.year - (g.my - 1)) * 12 + snapshot.month - 10
        g = g[(observed_months >= horizon) & (g.age_months <= horizon)]
        if len(g) < 20:
            continue
        x = g.age_months.to_numpy(float) + 0.5
        f = fit_weibull(x)
        bk = [fit_weibull(np.random.default_rng(i).choice(x, len(x))).shape for i in range(300)]
        rows.append({"model": names[m], "n": len(x), "shape_beta": f.shape, "beta_ci95": list(np.percentile(bk, [2.5, 97.5])),
                     "scale_months": f.scale, "median_age_months": float(np.median(x))})
    return rows


def alerting(con, units: pd.DataFrame, camp_model: dict, p: dict) -> tuple[pd.DataFrame, dict]:
    mf = con.execute("SELECT * FROM mart_battery_monthly_filed").df()
    end = mf.month.max()
    flags, frames = {}, []
    for m, g in mf.groupby("model"):
        g = g.set_index("month").reindex(pd.date_range(g.month.min(), end, freq="MS"), fill_value=0)
        ch = spc.p_chart(g.batt, g.complaints, p["baseline_months"], p["min_baseline_months"], p["sigma_k"])
        ch["alert"] = ((ch.p > ch.ucl) & (ch.n >= p["min_complaints"]) & (ch.defects >= p["min_battery"])).astype(int)
        flags[m] = ch.alert.astype(bool)
        frames.append(ch.assign(model=m).rename_axis("month").reset_index())
    u = units.set_index("campaign")
    evals = []
    for camp, m in camp_model.items():
        rd = pd.Timestamp(u.loc[camp, "report_date"])
        follow = any(mm == m and rd - pd.DateOffset(months=p["follow_on_months"]) <= pd.Timestamp(u.loc[k, "report_date"]) < rd
                     for k, mm in camp_model.items())
        win = flags[m][(flags[m].index < rd) & (flags[m].index >= rd - pd.DateOffset(months=p["lookback_months"]))]
        first = win[win].index.min()
        evals.append({"campaign": camp, "model": m, "report_date": str(rd.date()), "follow_on": follow,
                      "alert_before": bool(win.any()),
                      "lead_months": None if pd.isna(first) else int((rd.year - first.year) * 12 + rd.month - first.month)})
    ev = pd.DataFrame(evals)
    chart = pd.concat(frames)
    fi = ev[~ev.follow_on]
    return chart, {"alert_months": int(chart.alert.sum()), "nameplate_months": int(chart.p.notna().sum()),
                   "recalls_with_alert": f"{int(ev.alert_before.sum())}/{len(ev)}",
                   "first_in_family_with_alert": f"{int(fi.alert_before.sum())}/{len(fi)}", "detail": evals}


CAMPAIGN_MODEL = {"20V630000": "K", "21V127000": "K", "20V701000": "B", "21V560000": "B", "21V650000": "B", "24V481000": "B",
                  "24V812000": "B", "22V162000": "I", "23V040000": "I", "25V836000": "I", "26V028000": "I", "26V030000": "I",
                  "26V630000": "I", "23V434000": "3", "24V700000": "L", "25V655000": "L"}


# ------------------------------------------------------------------ orchestration
def run(paths: Paths | None = None) -> dict:
    paths = paths or Paths()
    params = load_params(paths.config)
    pc, pf = params["cells"], params["field"]
    paths.outputs.mkdir(exist_ok=True)
    (paths.outputs / "tables").mkdir(exist_ok=True)
    started = datetime.now(timezone.utc)

    log.info("ingest: cells")
    cells = build_cells(paths.raw)
    log.info("warehouse: build + quality gates")
    con, dq = warehouse.build(paths.raw, paths.warehouse, cells, pf["min_incident_year"], pf["age_origin_month"])

    log.info("cells: weibull / aft / spc / doe / screening")
    rng = np.random.default_rng(params["seed"])
    m = {"cells": {"weibull_by_batch": cell_weibull(cells, pc["bootstrap_draws"], rng), "aft_policy_adjusted": cell_aft(cells)}}
    spc_tbl, m["cells"]["spc"] = cell_spc(cells, pc["spc"])
    m["cells"]["doe"] = cell_doe(cells, pc["doe"])
    m["cells"]["screening"] = screening.run(cells, pc["early_failure_cycles"], pc["conformal_level"], params["seed"])

    log.info("field: summary / weibull / affected population / corrective action / alerting")
    c = con.execute("SELECT * FROM stg_complaints").df()
    units = con.execute("SELECT * FROM raw_recall_units").df()
    bolt = c[(c.model == "B") & (c.my <= 2022)]
    fleet_units = int(units.set_index("campaign").loc[["21V560000", "21V650000"], "units_affected"].sum())
    did, did_panel = corrective_action_did(c, pf["corrective_action"])
    pchart_tbl, alerts = alerting(con, units, CAMPAIGN_MODEL, pf["alerting"])
    m["field"] = {
        "n_complaints": len(c), "quarantined_incident_dates": int(c.incident.isna().sum()),
        "nameplates": con.execute("SELECT * FROM mart_nameplate_summary").df().to_dict("records"),
        "age_weibull": field_age_weibull(c, pf["weibull_horizon_months"], pd.Timestamp(pf["snapshot_date"]), warehouse.MODEL_NAMES),
        "bolt_fleet": {"units": fleet_units, "batt_complaints": int(bolt.comp_batt.sum()),
                       "per_1000": 1000 * bolt.comp_batt.sum() / fleet_units},
        "corrective_action_did": did,
        "population_model": population_model(c, pf["population_model"], np.random.default_rng(params["seed"])),
        "alerting_pchart": alerts,
    }

    log.info("write outputs")
    spc_tbl.to_csv(paths.outputs / "tables" / "spc_cells.csv", index=False)
    did_panel.to_csv(paths.outputs / "tables" / "corrective_action_panel.csv", index=False)
    pchart_tbl.to_csv(paths.outputs / "tables" / "pchart_monthly.csv", index=False)
    cells.to_csv(paths.outputs / "tables" / "cells.csv", index=False)
    for t in ("stg_complaints", "mart_battery_monthly_incident", "mart_battery_monthly_filed", "dq_results", "quarantine_incident_dates"):
        con.execute(f"COPY {t} TO '{paths.outputs / 'tables' / (t + '.csv')}' (HEADER)")
    with open(paths.outputs / "metrics.json", "w") as fh:
        json.dump(m, fh, indent=1, default=float)
    raw_files = sorted(p for p in paths.raw.glob("*") if p.is_file())
    manifest = {"cellrel_version": __version__, "python": platform.python_version(), "started_utc": started.isoformat(),
                "finished_utc": datetime.now(timezone.utc).isoformat(), "params_sha256": file_sha256(paths.config),
                "raw_sha256": {p.name: file_sha256(p) for p in raw_files}, "data_quality": as_records(dq)}
    with open(paths.outputs / "run_manifest.json", "w") as fh:
        json.dump(manifest, fh, indent=1)
    con.close()
    return m
