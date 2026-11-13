# Tableau dashboard build spec — Battery Cell Reliability & Field Failure Monitoring

Connect Tableau Desktop / Tableau Public to the CSVs in this folder (Text file connector). One data source per file; no joins needed.

## Sheet 1 — Weibull life by lot  (`cells.csv`, `weibull_by_lot.csv`)
- Calculated fields: `ln_life = LN([cycle_life])`; median-rank `F = (INDEX()-0.3)/(SIZE()+0.4)` computed along cells sorted by cycle_life, partitioned by lot; `weibull_y = LN(-LN(1-[F]))`
- Columns `ln_life`, Rows `weibull_y`, Color `lot`. Add a reference line at y = LN(-LN(0.9)) labelled B10.
- Tooltip: barcode, policy, cycle_life.

## Sheet 2 — SPC: initial capacity  (`spc_cells.csv`, filter `metric = "q2"`)
- Columns `seq`, Rows dual axis: `value` (circle) and `ewma` (line); synchronize axes.
- Reference lines from fields `UCL`, `CL`, `LCL` (average per pane), `ewma_UCL`, `ewma_LCL`.
- Color `ewma_alarm` (1 = red). Detail `lot`; add `lot` as a filter and as a vertical reference band per lot.

## Sheet 3 — DOE interaction  (`cells.csv`)
- Columns `Q1`, Rows `cycle_life` (log axis), Color = bin of `C1` (≤4.5, 4.5–5.5, >5.5), trend lines per color (exponential/log model).

## Sheet 4 — Field battery complaints & alerts  (`field_alerts_monthly.csv`)
- Columns `month` (continuous month), Rows `count` (bar) + `ucl` (line, dual axis). Color `alert`. Filter `model`.
- Add recall report dates as reference lines (from `affected_population.csv` / README table).

## Sheet 5 — Corrective-action check  (`bolt_did_panel.csv`)
- Columns `mo`, Rows `n` with 3-month moving average table calc, Color `bolt` (1 = Bolt MY2017-19, 0 = Leaf MY2011-19). Shade `period = "rollout"`.

## Sheet 6 — Affected population  (`affected_population.csv`)
- Text table: campaign, model, model_years, recall_report, units_affected, batt_complaints_before_recall, batt_complaints_total.

## Dashboard
Top row: KPI text (fleet B10 = 331 cycles; Bolt complaints −56% post-remedy; 3 of 16 recalls preceded by an alert, all follow-on recalls).
Row 2: Sheet 1 | Sheet 2. Row 3: Sheet 4 (with `model` filter applied to sheet 4 only) | Sheet 5. Row 4: Sheet 3 | Sheet 6.
