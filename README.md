# Battery Cell Reliability & Field Failure Analytics

Reliability engineering on two public, real-world data sources:

1. **Cell-level life data**: 124 commercial LFP/graphite cells (A123 APR18650M1A) cycled to failure under 68 fast-charging policies across 3 test batches (the dataset's `lot` column). Source: Severson et al., *Nature Energy* 2019. Per-cell capacity arrays, cycle lives and SI Table 9 (barcode, batch date, policy) come from the co-author's public repo [petermattia/revisit-severson-et-al](https://github.com/petermattia/revisit-severson-et-al) (commit `3a77c7d`). Those files were exported from the original [data.matr.io](https://data.matr.io/1/projects/5c48dd2bc625d700019f3204) release.
2. **Field data**: 11,051 NHTSA consumer complaints and 272 recall records for 6 EV nameplates (Chevrolet Bolt EV/EUV, Hyundai Kona Electric, Nissan Leaf, Tesla Model 3 and Model Y, VW ID.4), model years 2011–2023. Pulled from the official NHTSA API (`api.nhtsa.gov`) on Nov 13, 2026, with every model-name variant per year included and duplicates removed by ODI number. Official affected-unit counts come from NHTSA's recall campaign endpoint.

> **Field data caveat:** NHTSA complaints are a public **field-failure proxy**, not warranty returns or RMAs. They have no exposure denominator, they are self-reported, and they spike when a recall is announced. Primary battery definition: a complaint coded to a *propulsion system / traction battery* component. Sensitivity definition: the primary definition plus "battery"/"high voltage" in the narrative.

## Results

## Summary: the four questions a cell field-reliability team asks

| Question | Method | Answer (real data) |
|---|---|---|
| What is the expected failure rate of an affected population? | Right-censored Weibull fit on 57,414 recalled vehicles (2017–19 Chevrolet Bolt), using only data from before the recall | β = 1.22 (95% CI 0.86–1.71); projected **1.6 battery complaints per 1,000 vehicles by 8 years in service (≈92 vehicles)** without the remedy |
| Did the corrective action work? | Two independent checks: model-expected vs. observed failures, and a difference-in-differences test against a Nissan Leaf control | Observed / expected = **0.33** (95% CI 0.15–0.63); Leaf-controlled rate ratio = 0.33 (p = 0.07). Both point to about a two-thirds reduction |
| Can bad cells be caught early? | Features from the first 100 cycles; early-failure classifier and conformal prediction intervals | Cells failing before 550 cycles: **86% recall, 78% precision, AUC 0.91** on held-out cells. 90% intervals covered 87.5% of an unseen test batch |
| Can complaint data warn of a recall in advance? | Pre-specified fleet-size-normalized p-chart, scored against all 16 traction-battery recalls | **No.** 1 of 7 first-in-family recalls had an alert, and that hit looks coincidental. Early warning needs vehicle telemetry, not complaint counts |


### 1. Weibull life-data analysis by batch (cells)
| Batch | n | Shape β | Scale η (cycles) | B10 life (95% bootstrap CI) |
|---|---|---|---|---|
| All | 124 | 2.23 | 908 | 331 (294–377) |
| 2017-05-12 | 41 | 2.40 | 1,041 | 407 (365–500) |
| 2017-06-30 | 43 | 6.68 | 502 | 358 (322–430) |
| 2018-04-12 | 40 | 3.35 | 1,145 | 585 (533–678) |

- Batches share almost no charging policies, so raw batch comparisons are confounded. A **Weibull AFT model adjusted for the charging factors** gives:
  - Batch 2017-06-30: 0.55× the characteristic life of the first batch (95% CI 0.48–0.63)
  - Batch 2018-04-12: 1.20× (CI 1.08–1.34)
- Each step-1 C-rate increase of 1C cuts characteristic life to 0.86×.
- A batch is a test run, not a confirmed production lot, so batch differences can reflect test conditions as well as the cells themselves.
- β > 1 in every batch indicates wear-out failure.
- The pooled Weibull fit is rejected (KS p = 0.008) because it mixes batches and policies. Use the per-batch or covariate-adjusted model, not the pooled B10, for decisions.

### 2. Early-life failure prediction and screening (first 100 cycles)
- **Model:** elastic net on 8 early-life features (ΔQ₁₀₀₋₁₀(V) variance, minimum, skewness and kurtosis; capacity at cycles 2 and 100; max − initial capacity; late fade slope). Trained on the authors' train split (`src/06_cell_screening.py`).

| Split | RMSE (cycles) | MAPE |
|---|---|---|
| Test 1 | 87.0 | 13.0% |
| Test 2 (unseen batch) | 191.4 | 9.6% |
| Variance-only baseline, Test 1 / Test 2 | 137.9 / 195.9 | 14.7% / 11.4% |

- **Pipeline check:** the variance-only baseline reproduces the published Severson et al. values (138 / 196).
- **Generalization:** the gain on the unseen batch is small (191 vs 196 cycles). The model doesn't transfer well across batches.
- **Prediction intervals:** split-conformal 90% intervals were calibrated on Test 1 and evaluated on Test 2. They covered **87.5%** of unseen-batch cells, with a median width of 435 cycles.
- **Early-failure screen (cycle life < 550):**
  - Test 1: 21 of 43 cells failed early. The classifier flagged 23, for accuracy 0.81, precision 0.78, recall 0.86 and AUC 0.91.
  - Test 2: only 1 early failure. It was caught, along with 4 false flags. That set is too small to judge precision.
- **Superseded version:** the earlier 6-feature model in `src/02_cell_reliability.py` scored 124.9 / 229.2 RMSE and is kept for transparency.

### 3. SPC and batch traceability (cells)
- **Setup:** Phase I limits (I-MR and EWMA λ = 0.2, plus Western Electric rules 1, 2 and 4) come from the first batch. Phase II monitors the next two batches.
- **Initial capacity:** the 2018 batch is shifted down about 1.3% (1.048 vs 1.062 Ah). All 40 of its cells trigger EWMA alarms.
- **Shift vs. life:** that batch nonetheless has the **longest** life. Across all batches, cells flagged on either metric do not have shorter life (median 825 vs 651 cycles, Mann-Whitney p = 0.14).
- **Takeaway:** an incoming capacity shift is detectable but did not predict life here. The policy-adjusted early-degradation residual is the life-relevant metric.

### 4. DOE / response surface on charging factors
- **Design:** 68 two-step policies, C1(Q1%)-C2, with 27 replicated. Batch is treated as a blocking factor.
- **Fit:** a quadratic response surface on log₁₀(cycle life) gives R² = 0.83 (adjusted 0.81). The lack-of-fit test passes against pure error from the replicates (F = 1.07, p = 0.40).
- **Significant terms:** the **C1×Q1** interaction (p < 0.001), C1×C2 (p = 0.02), Q1×C2 (p = 0.01), plus the C1 and C2 main effects.
- **Best 10-minute policy:** searching only near tested policies, the model's best 0–80% fast charge is about 4.9C to 75% SOC, then 3C, with predicted life ≈ 1,030 cycles. The best observed 10-minute policies average 1,016–1,116 cycles.

### 5. Field reliability (NHTSA)
- **Battery complaint share:** Bolt 18.4%, Leaf 12.8%, ID.4 5.9%, Kona Electric 5.5%, Model 3 1.6%, Model Y 1.0%.
- **Age at battery complaint** (first 48 months in service, model years with ≥48 months observed): Weibull β = 1.8–2.7 across nameplates, so failures increase with age. This is conditional on a complaint being filed, so treat it as descriptive.
- **Affected population (observed):** every 2017–2022 Bolt was recalled, 109,828 units (21V560 + 21V650). That fleet has 182 component-coded battery complaints, or **1.66 per 1,000 vehicles**. Official units for 6 recall cohorts are in `outputs/affected_population.csv`.
- **Failure-rate prediction for an affected population** (`src/05_population_failure_model.py`):
  - Cohort and censoring: 57,414 Bolt MY2017–19 vehicles (recall 21V560). The 30 component-coded battery complaints before the first recall (Nov 2020) count as failures. Every other vehicle is right-censored at its age on Oct 31, 2020.
  - Model-year split: units are split across model years by GM-reported US sales (2016–17: 23,876; 2018: 18,019; 2019: 16,418; total 58,313, within 1.6% of the recall population).
  - Fit: β = 1.22 (95% CI 0.86–1.71), so wear-out can't be ruled in or out. Projected cumulative complaint rate by 96 months in service: 1.59 per 1,000 (95% CI 1.15–4.58), or about 92 vehicles.
  - Observed vs. expected: without the remedy, the model expects 27.1 complaints (95% CI 18.2–93.3) between Jul 2022 and Jul 2024. 9 were observed, an **O/E of 0.33** (Poisson 95% CI 0.15–0.63). This is consistent with the difference-in-differences result below.
  - Sensitivity: the model-year split matters. Putting all units in MY2017 gives O/E 0.60 (CI 0.27–1.13), and all in MY2019 gives 0.02. The sales-weighted split is the defensible one.
  - The projection to 96 months extrapolates beyond the ~46 months of pre-recall exposure.
- **Corrective-action effectiveness** (Bolt MY2017–19 battery-module replacement):
  - Design: Poisson difference-in-differences, Bolt MY2017–19 vs Leaf MY2011–19 (both closed cohorts). The recall/remedy rollout (Nov 2020–Jun 2022) is excluded.
  - Primary window, post period ending Jul 2024 (before the Leaf's own battery recall): Bolt battery complaints fell **56%** (0.82 to 0.36 a month), while the Leaf rose 0.36 to 0.48. Rate ratio 0.33 (95% CI 0.10–1.09, p = 0.07); broad definition 0.34 (CI 0.15–0.80, p = 0.01).
  - Bolt battery-fire complaints (all model years, broad definition): 12 in 2020–21, then 1 in 2022 and 1 in all of 2023–2025.
  - The full window to Dec 2025 gives 0.11, but that is inflated by the Leaf's own recall spike in the control group, so it is reported as a sensitivity check only.
- **Early-warning alerting** (scripts run on downloaded data, not a deployed monitoring system):
  - **v1, volume c-chart:** monthly battery complaints against a Poisson limit on a trailing 12-month baseline. It raised 14 alerts in 577 nameplate-months, and 3 of 16 recalls had an alert in the prior 12 months. All 3 were follow-on recalls after an earlier recall of the same nameplate, so they reflect recall-driven reporting, not early warning.
  - **v2, fleet-size-normalized p-chart, rule fixed before scoring** (`src/07_pchart_alerting.py`): it tracks the share of a nameplate's complaints that are battery-coded, so fleet growth doesn't trigger alerts. It raised 5 alerts in 605 nameplate-months, far more specific.
    - It caught only **1 of 7 first-in-family recalls**: Tesla Model 3, 5 months before 23V434. That alert rested on 3 complaints, and the recall covered 26 vehicles, so it is likely coincidence.
    - The VW ID.4 spike in Jan 2024 (11 of 22 complaints battery-coded) came 23 months before the next ID.4 battery recall. That's outside the pre-set 12-month window, so it isn't counted.
  - **Conclusion:** public complaint data can't give reliable early warning. That requires fleet telemetry (cell voltages, temperatures, BMS fault codes) linked to returned-pack teardown results.

## Figures
`outputs/figures/`: Weibull probability plot by batch, SPC chart, DOE interaction, corrective-action check.

## Tableau
`tableau/` holds tidy extracts and `DASHBOARD_SPEC.md` (sheet-by-sheet build).

## Reproduce
```
pip install -r requirements.txt
python src/01_build_cells.py         # join SI Table 9 + Q(V) arrays, extract features
python src/02_cell_reliability.py    # Weibull, AFT, prediction, SPC, DOE
python src/03_field_reliability.py   # NHTSA reliability, affected population, DiD, alerting
python src/04_figures_and_tableau.py
python src/05_population_failure_model.py   # censored Weibull, affected-population projection, O/E
python src/06_cell_screening.py             # improved early-life model, conformal intervals, early-failure classifier
python src/07_pchart_alerting.py            # fleet-normalized alerting, scored vs all recalls
```
The NHTSA pull (browser-side `fetch` against `api.nhtsa.gov`) is saved in `data/raw/`. Complaint fields kept: model, model year, ODI number, incident and filed month, component and narrative battery flags, fire, crash, injuries.

## Limitations
- Complaints are not returns, and complaints undercount true failures. Denominators exist only where a full-fleet recall gives one (Bolt), and the model-year split relies on calendar-year sales. The population model treats each complaint as one failed vehicle and ignores vehicles removed by buyback.
- Batches are the authors' test runs, not confirmed production lots, and all cells are one commercial cell type. This shows batch-level traceability methods, not supplier or production-lot traceability.
- The DOE analyzes the authors' designed policy set. I did not choose the design points.
