# Battery Cell Reliability & Field Failure Analytics

A reproducible reliability pipeline for battery cells and EV field data. It answers the four questions a cell quality and field-reliability team gets asked, using public, real data only:

| Question | Method | Answer |
|---|---|---|
| What failure rate should we expect in an affected population? | Exact right-censored Weibull MLE on 57,414 recalled vehicles (2017–19 Chevrolet Bolt), fit only on data from before the recall | β = 1.22 (95% CI 0.86–1.71); **1.6 battery complaints per 1,000 vehicles by 8 years** in service (CI 1.15–4.58), ≈ 92 vehicles, without the remedy |
| Did the corrective action work? | Two independent checks: model-expected vs. observed failures, and a Poisson difference-in-differences test against a Nissan Leaf control | Observed / expected = **0.33** (exact Poisson CI 0.15–0.63); Leaf-controlled rate ratio 0.33 (p = 0.07). Both point to about a two-thirds reduction |
| Can bad cells be caught from early cycling? | First-100-cycle features; early-failure classifier; split-conformal intervals; robustness over 20 cross-validation fold assignments | Cells failing before 550 cycles: **recall 0.86–0.90, precision 0.76–0.82, AUC 0.90–0.91** across all 20 fold splits |
| Can field complaints warn of a recall in advance? | Pre-registered, fleet-size-normalized p-chart scored against all 16 traction-battery recalls | **No.** 1 of 7 first-in-family recalls had an alert, and that hit looks coincidental. Early warning needs vehicle telemetry |

## Data

| Source | What | Provenance |
|---|---|---|
| Severson et al., *Nature Energy* 2019 | 124 commercial LFP/graphite cells (A123 APR18650M1A) cycled to 80% capacity under 68 fast-charging policies in 3 test batches. Per-cell Q(V) curves for cycles 2–100 and SI Table 9 (barcode, batch date, policy, cycle life) | Co-author's public repo [petermattia/revisit-severson-et-al](https://github.com/petermattia/revisit-severson-et-al) @ `3a77c7d`, exported from the [data.matr.io](https://data.matr.io/1/projects/5c48dd2bc625d700019f3204) release |
| NHTSA (api.nhtsa.gov) | 11,051 consumer complaints and 272 recall records for 6 EV nameplates (Bolt EV/EUV, Kona Electric, Leaf, Model 3, Model Y, ID.4), MY2011–2023, plus official affected-unit counts for 16 traction-battery recalls | Snapshot of Nov 13, 2026. Free text is not stored: complaints are reduced to battery/fire/crash flags at ingestion |
| GM-reported US sales 2016–2019 | Used only to split the 57,414 recalled Bolts across model years | 23,876 / 18,019 / 16,418, totaling within 1.6% of the recall population |

**Field data caveat:** complaints are a field-failure proxy, not warranty returns. They undercount, have no exposure denominator except where a full-fleet recall supplies one, and spike around recall announcements. The analyses are designed around this: models are fit on pre-recall data, recall rollout windows are excluded, and closed control cohorts are used.

## Architecture

```
data/raw/*.csv ──► ingest ──► DuckDB warehouse ───────────────────────────► analyses ──► outputs/
                 (NhtsaClient,  raw_*       (as delivered, all text)        reliability    metrics.json
                  Severson     stg_*        (typed, decoded, validated)     spc            run_manifest.json
                  loader)      quarantine_* (rows failing validation)       doe            tables/*.csv  (Tableau)
                               dq_results   (12 checks, 11 critical)        causal         figures/*.png
                               mart_*       (monthly battery counts, etc.)  screening
```

| Module | Responsibility |
|---|---|
| `ingest/nhtsa.py` | API client. Discovers each nameplate's per-year name variants ("BOLT" vs "BOLT EV", "MODEL Y 5-SEAT") instead of hard-coding them; exponential-backoff retries; distinguishes NHTSA's "400 + empty body = no data" from real errors; dedupes on (ODI number, model year) |
| `ingest/severson.py` | Joins SI Table 9 to the per-cell arrays, enforcing an ordering contract against the authors' exported cycle lives (fails loudly on mismatch); extracts early-life features |
| `warehouse.py`, `quality.py` | DuckDB raw → staging → marts. Declarative checks: uniqueness, flag domain, known models, parsable dates, model-year range, recall-unit integrity, cell count. Critical failures stop the run; bad incident dates are quarantined, not dropped |
| `reliability.py` | Exact Weibull MLE via the profile-likelihood score equation (root-finding, no optimizer tolerance). Handles right-censoring with unit weights, so 57,000 censored vehicles are 3 weighted rows. B-lives, bootstrap CIs, observed-information covariance |
| `spc.py` | I-MR limits from Phase I, EWMA with asymptotic limits, Western Electric rules 1/2/4, rolling-baseline p-chart (current period excluded from its own baseline) |
| `doe.py` | Quadratic response surface with batch blocking, pure-error lack-of-fit, optimum restricted to the tested region |
| `causal.py` | Poisson DiD with HC0-robust errors; observed/expected with exact Garwood intervals |
| `screening.py` | Early-life regression, split-conformal intervals, early-failure classifier, cross-validation fold robustness |
| `pipeline.py`, `cli.py` | Orchestration; writes metrics, tables, figures and a run manifest (package version, SHA-256 of the config and every raw file, data-quality results) |

**Pre-registration:** every threshold and window is fixed in `config/params.yaml`, including alert rules, the DiD windows and the early-failure cutoff. The run manifest records the config hash, so a changed threshold is visible.

## Run

```bash
make install        # pip install -e ".[dev]"
make all            # lint -> cellrel run -> cellrel figures -> pytest
make ingest         # optional: refresh the NHTSA snapshot from the live API (needs internet)
```

`cellrel run` takes about 12 seconds on a laptop.

## Tests (21, all passing)

- **Estimators recover known truth from simulated data before touching real data:**
  - Weibull MLE at shapes 0.8, 2.0 and 6.5.
  - Agreement with SciPy to 1e-5.
  - Censored, weighted MLE in the same rare-failure regime as the population model (39 failures among 60,000 units; the real cohort has 30 among 57,414).
  - Poisson DiD recovers a planted 0.4 rate ratio.
  - EWMA false-alarm rate stays under 1% in control.
  - Western Electric rules fire on constructed patterns.
- **Ingestion client** tested against a fake transport: retry on 429, "400 = no data", name-variant discovery and deduplication.
- **Golden regression:** a full pipeline run must reproduce every published number in this README (`tests/golden_v1.json`). It caught a real issue during the refactor, described below.
- CI: `.github/workflows/ci.yml` runs lint and tests on push. The workflow file is included, but it has not yet run on GitHub.

## Results

### 1. Weibull life data by test batch (cells)
| Batch | n | Shape β | Scale η (cycles) | B10 life (95% bootstrap CI) |
|---|---|---|---|---|
| All | 124 | 2.23 | 908 | 331 (294–377) |
| 2017-05-12 | 41 | 2.40 | 1,041 | 407 (365–500) |
| 2017-06-30 | 43 | 6.68 | 502 | 358 (322–430) |
| 2018-04-12 | 40 | 3.35 | 1,145 | 585 (533–678) |

- **Confounding:** batches share almost no charging policies, so a Weibull AFT model adjusts for C1, Q1 and C2.
  - Batch 2017-06-30 lives 0.55× as long as the first batch (CI 0.48–0.63).
  - Batch 2018-04-12 lives 1.20× as long (CI 1.08–1.34).
- **Charging rate:** each +1C in step-1 rate multiplies characteristic life by 0.86.
- **Failure mode:** β > 1 in every batch means wear-out.
- **Pooled fit:** rejected (KS p = 0.008) because it mixes batches and policies, so decisions should use the per-batch or adjusted model.
- **Batches vs. lots:** a batch is a test run, not a confirmed production lot, so batch differences can reflect test conditions too.

### 2. Early-life screening (first 100 cycles)
| | Test 1 | Test 2 (unseen batch) |
|---|---|---|
| Lifetime RMSE, cycles: median over 20 fold splits (range) | 93.6 (86.9–131.0) | 195.6 (190.0–203.6) |
| Variance-only baseline (reproduces Severson et al.'s published 138 / 196) | 137.9 | 195.9 |

- **Lifetime regression:** the 8-feature model beats the variance-only baseline on Test 1 but adds nothing on the unseen batch. Its Test 1 error also depends heavily on which CV fold split is used.
  - The canonical fold split (rows sorted by batch, barcode) gives 87.0.
  - That split turned out to be the best of the 20, so the median is reported instead.
- **Early-failure classifier (< 550 cycles):** stable across all 20 splits on Test 1 (21 of 43 cells fail early). Recall 0.86–0.90, precision 0.76–0.82, AUC 0.90–0.91.
  - Test 2 has only 1 early failure: it was caught, along with 4 false flags.
- **Split-conformal 90% intervals:** calibrated on Test 1, they covered 87.5% of the unseen batch, with a median width of 435 cycles.

### 3. SPC and batch traceability (cells)
- **Setup:** Phase I limits come from the first batch: I-MR and EWMA (λ = 0.2), plus Western Electric rules 1/2/4.
- **Capacity shift:** the 2018 batch's initial capacity is 1.3% lower (1.048 vs 1.062 Ah), and all 40 of its cells raise EWMA alarms.
- **Shift vs. life:** that batch nonetheless lives longest. Across all batches, flagged cells do not have shorter life (median 825 vs 651 cycles, Mann-Whitney p = 0.14).
- **Takeaway:** incoming capacity is detectable but is not the failure mechanism here. The policy-adjusted early-degradation residual is the life-relevant chart.

### 4. DOE / response surface (cells)
- **Design:** 68 two-step policies C1(Q1%)-C2, 27 of them replicated, with batch as a block.
- **Fit:** quadratic RSM on log₁₀(cycle life) gives R² 0.83 (adjusted 0.81). The lack-of-fit test passes against pure error (F 1.07, p 0.40).
- **Significant terms:** C1×Q1 (p < 0.001), C1×C2 (p 0.02) and Q1×C2 (p 0.01), plus the C1 and C2 main effects.
- **Best 10-minute policy within the tested region:** 4.9C to 75%, then 3C, predicted at ≈ 1,030 cycles. That's in line with the best observed 10-minute policies (1,016–1,116 cycles).
  - An unrestricted search returns a corner policy that was never tested, which would be extrapolation.

### 5. Field reliability (NHTSA)
- **Battery share of complaints** (component-coded): Bolt 18.4%, Leaf 12.8%, ID.4 5.9%, Kona Electric 5.5%, Model 3 1.6%, Model Y 1.0%.
- **Full Bolt fleet:** every 2017–2022 Bolt was recalled, 109,828 units (21V560 + 21V650). That fleet has 182 battery complaints, or **1.66 per 1,000 vehicles**.
- **Population failure model:**
  - Cohort: Bolt MY2017–19, 57,414 units.
  - Failures: the 30 battery complaints before the first recall (Nov 2020). Every other vehicle is right-censored at its age on Oct 31, 2020.

| Model-year split | β (95% CI) | Rate per 1,000 by 96 mo | Expected Jul 2022–Jul 2024 without remedy | Observed / expected (9 observed) |
|---|---|---|---|---|
| **Sales-weighted (primary)** | **1.22 (0.86–1.71)** | **1.59 (1.15–4.58)** | **27.1 (18.2–93.4)** | **0.33 (0.15–0.63)** |
| Equal | 1.27 (0.90–1.78) | 1.76 | 30.5 | 0.30 (0.13–0.56) |
| All units oldest MY (bound) | 0.98 (0.69–1.41) | 1.02 | 15.1 | 0.60 (0.27–1.13) |
| All units newest MY (bound) | 2.99 (2.09–4.28) | 30.5 | 503.3 | 0.02 (0.01–0.03) |

  - The model-year split matters, which is why it is anchored to GM's reported sales and both extremes are shown.
  - Projections to 96 months extrapolate beyond ≈ 46 months of pre-recall exposure.
- **Corrective action, difference-in-differences:**
  - Design: Bolt MY2017–19 vs. Leaf MY2011–19 (closed cohorts), Poisson model with robust errors. The rollout window (Nov 2020–Jun 2022) is excluded.
  - Primary window, post period ending Jul 2024 (before the Leaf's own recall): Bolt complaints went from 0.82 to 0.36 a month, while the Leaf went from 0.36 to 0.48. Rate ratio **0.33** (CI 0.10–1.09, p 0.07); broad definition 0.34 (CI 0.15–0.80, p 0.01).
  - Extending to Dec 2025 gives 0.11, but the control's own recall spike inflates that number, so it is a sensitivity check only.
- **Early-warning alerting (scripts run on a snapshot, not a deployed monitor):**
  - Rule: a p-chart on the battery share of each nameplate's monthly complaints, so fleet growth doesn't trigger alerts. Fixed before scoring: trailing 12-month baseline, 3σ, ≥ 10 complaints and ≥ 3 battery complaints per month.
  - It raised 5 alerts in 605 nameplate-months.
  - It caught 1 of 7 first-in-family recalls (Model 3, 5 months before 23V434). That alert rested on 3 complaints before a 26-vehicle recall, so it is likely coincidence.
  - An earlier volume-based c-chart did worse: its only hits came after an earlier recall of the same nameplate.
  - **Conclusion:** early warning needs telemetry (cell voltage spread, temperature, BMS fault codes) linked to teardown results.

## Engineering notes: what the tests caught
- **Row-order dependence:** unshuffled CV folds made the screening model depend on input row order. Loading cells in source order instead of batch order moved Test 1 RMSE from 87.0 to 89.3. The order is now fixed explicitly, and a 20-split robustness check shows the published 87.0 was the best split, so the median (93.6) is reported.
- **Control-group contamination:** the first difference-in-differences window ran through the control group's own recall, inflating the effect (0.11 vs 0.33). The primary window now ends before it.
- **Extrapolated optimum:** the first DOE optimum was a corner policy outside the tested region. The search is now restricted to the neighborhood of tested policies.

## Limitations
- Complaints are not returns and undercount failures. The population model treats each complaint as one failed vehicle and ignores buybacks.
- Batches are the authors' test runs, all of one commercial cell. This demonstrates batch-level methods, not supplier or production-lot traceability.
- The DOE analyzes the authors' designed policy set; I did not choose the design points.
- The NHTSA snapshot was captured through the API from a browser session because this build environment blocks outbound requests. `cellrel ingest-nhtsa` is the scripted equivalent. It is tested against a fake transport but has not been run against the live API from this environment.

## Tableau
`tableau/DASHBOARD_SPEC.md` gives a sheet-by-sheet build on `outputs/tables/` (generated by `cellrel run`).
