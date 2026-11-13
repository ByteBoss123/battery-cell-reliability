# Battery Cell Reliability & Field Failure Analytics

Reliability engineering on two public, real-world data sources:

1. **Cell-level life data**: 124 commercial LFP/graphite cells (A123 APR18650M1A) cycled to failure under 68 fast-charging policies across 3 production/test lots. Source: Severson et al., *Nature Energy* 2019. Per-cell capacity arrays, cycle lives and SI Table 9 (barcode, lot, policy) come from the co-author's public repo [petermattia/revisit-severson-et-al](https://github.com/petermattia/revisit-severson-et-al) (commit `3a77c7d`). Those files were exported from the original [data.matr.io](https://data.matr.io/1/projects/5c48dd2bc625d700019f3204) release.
2. **Field data**: 11,051 NHTSA consumer complaints and 272 recall records for 6 EV nameplates (Chevrolet Bolt EV/EUV, Hyundai Kona Electric, Nissan Leaf, Tesla Model 3 and Model Y, VW ID.4), model years 2011–2023. Pulled from the official NHTSA API (`api.nhtsa.gov`) on Nov 13, 2026, with every model-name variant per year included and duplicates removed by ODI number. Official affected-unit counts come from NHTSA's recall campaign endpoint.

> **Field data caveat:** NHTSA complaints are a public **field-failure proxy**, not warranty returns or RMAs. They have no exposure denominator, they are self-reported, and they spike when a recall is announced. Primary battery definition: a complaint coded to a *propulsion system / traction battery* component. Sensitivity definition: the primary definition plus "battery"/"high voltage" in the narrative.

## Results

### 1. Weibull life-data analysis by lot (cells)
| Lot | n | Shape β | Scale η (cycles) | B10 life (95% bootstrap CI) |
|---|---|---|---|---|
| All | 124 | 2.23 | 908 | 331 (294–377) |
| 2017-05-12 | 41 | 2.40 | 1,041 | 407 (365–500) |
| 2017-06-30 | 43 | 6.68 | 502 | 358 (322–430) |
| 2018-04-12 | 40 | 3.35 | 1,145 | 585 (533–678) |

- Lots share almost no charging policies, so raw lot comparisons are confounded. A **Weibull AFT model adjusted for the charging factors** gives:
  - Lot 2017-06-30: 0.55× the characteristic life of the first lot (95% CI 0.48–0.63)
  - Lot 2018-04-12: 1.20× (CI 1.08–1.34)
- Each step-1 C-rate increase of 1C cuts characteristic life to 0.86×.
- Lot here means test batch, so lot differences can reflect test conditions as well as cell production.
- β > 1 in every lot indicates wear-out failure.
- The pooled Weibull fit is rejected (KS p = 0.008) because it mixes lots and policies. Use the per-lot or covariate-adjusted model, not the pooled B10, for decisions.

### 2. Early-life failure prediction (first 100 cycles)
Elastic net on 6 early-life features (ΔQ₁₀₀₋₁₀(V) variance/min, capacity, fade slopes). The model is trained on the authors' train split and tested on their two held-out splits.

| Split | RMSE (cycles) | MAPE |
|---|---|---|
| Test 1 | 124.9 | 13.3% |
| Test 2 (unseen lot) | 229.2 | 12.7% |
| Variance-only baseline, Test 1 / Test 2 | 137.9 / 195.9 | 14.7% / 11.4% |

The variance-only baseline reproduces the published Severson et al. values (138 / 196), which validates the pipeline. The multivariate model is better on Test 1 but **worse on the unseen lot**. That generalization gap is the result to report.

### 3. SPC and lot traceability (cells)
- **Setup:** Phase I limits (I-MR and EWMA λ = 0.2, plus Western Electric rules 1, 2 and 4) come from the first lot. Phase II monitors the next two lots.
- **Initial capacity:** the 2018 lot is shifted down about 1.3% (1.048 vs 1.062 Ah). All 40 of its cells trigger EWMA alarms.
- **Shift vs. life:** that lot nonetheless has the **longest** life. Across all lots, cells flagged on either metric do not have shorter life (median 825 vs 651 cycles, Mann-Whitney p = 0.14).
- **Takeaway:** an incoming capacity shift is detectable but did not predict life here. The policy-adjusted early-degradation residual is the life-relevant metric.

### 4. DOE / response surface on charging factors
- **Design:** 68 two-step policies, C1(Q1%)-C2, with 27 replicated. Lot is treated as a blocking factor.
- **Fit:** a quadratic response surface on log₁₀(cycle life) gives R² = 0.83 (adjusted 0.81). The lack-of-fit test passes against pure error from the replicates (F = 1.07, p = 0.40).
- **Significant terms:** the **C1×Q1** interaction (p < 0.001), C1×C2 (p = 0.02), Q1×C2 (p = 0.01), plus the C1 and C2 main effects.
- **Best 10-minute policy:** searching only near tested policies, the model's best 0–80% fast charge is about 4.9C to 75% SOC, then 3C, with predicted life ≈ 1,030 cycles. The best observed 10-minute policies average 1,016–1,116 cycles.

### 5. Field reliability (NHTSA)
- **Battery complaint share:** Bolt 18.4%, Leaf 12.8%, ID.4 5.9%, Kona Electric 5.5%, Model 3 1.6%, Model Y 1.0%.
- **Age at battery complaint** (first 48 months in service, model years with ≥48 months observed): Weibull β = 1.8–2.7 across nameplates, so failures increase with age. This is conditional on a complaint being filed, so treat it as descriptive.
- **Affected population:** every 2017–2022 Bolt was recalled, 109,828 units (21V560 + 21V650). That fleet has 182 component-coded battery complaints, or **1.66 per 1,000 vehicles**. The README tables and `outputs/affected_population.csv` list the official units for 6 recall cohorts.
- **Corrective-action effectiveness** (Bolt MY2017–19 battery-module replacement):
  - Design: Poisson difference-in-differences, Bolt MY2017–19 vs Leaf MY2011–19 (both closed cohorts). The recall/remedy rollout (Nov 2020–Jun 2022) is excluded.
  - Primary window, post period ending Jul 2024 (before the Leaf's own battery recall): Bolt battery complaints fell **56%** (0.82 to 0.36 a month), while the Leaf rose 0.36 to 0.48. Rate ratio 0.33 (95% CI 0.10–1.09, p = 0.07); broad definition 0.34 (CI 0.15–0.80, p = 0.01).
  - Bolt battery-fire complaints (all model years, broad definition): 12 in 2020–21, then 1 in 2022 and 1 in all of 2023–2025.
  - The full window to Dec 2025 gives 0.11, but that is inflated by the Leaf's own recall spike in the control group, so it is reported as a sensitivity check only.
- **Automated alerting:**
  - Rule: monthly battery complaints by filed month against a c-chart (Poisson 99.865% limit on a trailing 12-month baseline) plus an EWMA. This raised 14 alerts in 577 nameplate-months.
  - Only **3 of 16** battery recalls had an alert in the 12 months before them, and all 3 were follow-on recalls after an earlier recall of the same vehicle family. Complaint volume alone gave **no independent early warning**. It is useful for post-recall monitoring, not for detecting a new issue.

## Figures
`outputs/figures/`: Weibull probability plot by lot, SPC chart, DOE interaction, corrective-action check.

## Tableau
`tableau/` holds tidy extracts and `DASHBOARD_SPEC.md` (sheet-by-sheet build).

## Reproduce
```
pip install -r requirements.txt
python src/01_build_cells.py         # join SI Table 9 + Q(V) arrays, extract features
python src/02_cell_reliability.py    # Weibull, AFT, prediction, SPC, DOE
python src/03_field_reliability.py   # NHTSA reliability, affected population, DiD, alerting
python src/04_figures_and_tableau.py
```
The NHTSA pull (browser-side `fetch` against `api.nhtsa.gov`) is saved in `data/raw/`. Complaint fields kept: model, model year, ODI number, incident and filed month, component and narrative battery flags, fire, crash, injuries.

## Limitations
- Complaints are not returns. There is no sales-volume denominator except where a full-fleet recall gives one (Bolt).
- "Lot" is the authors' test batch. The cells are one commercial cell type, so this is not supplier traceability across vendors.
- The DOE analyzes the authors' designed policy set. I did not choose the design points.
