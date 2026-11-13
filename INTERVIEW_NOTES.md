# Defending this project in an interview

## 30-second version
I took two public datasets: 124 Li-ion cells cycled to failure, and 11,000 NHTSA EV complaints and recalls. On them I answered the four questions a field-reliability team gets asked. How many will fail? Did the fix work? Can we catch bad cells early? Can we see problems coming? The fix result held up under two independent methods. The early-warning result was negative, and I report it that way.

## Likely challenges and honest answers

**"Complaints aren't failures."**
Correct, they're a proxy. They undercount, and they spike around recalls. So:
- I fit the failure model only on data from before the recall.
- I excluded the recall rollout window from the comparison.
- I used a closed control cohort.
With warranty or teardown data I would rerun the same code on that instead.

**"Why trust the 0.33?"**
Two methods with different assumptions agree:
- The failure model fit before the recall predicted 27 complaints in Jul 2022–Jul 2024. 9 were observed, O/E 0.33 (CI 0.15–0.63).
- The difference-in-differences test against the same-era Leaf gives 0.33 (p = 0.07).
The weak point is the model-year split of the 57,414 vehicles. I used GM's reported sales and showed the extreme splits as bounds.

**"Your first answer was 0.11. Why change it?"**
The Leaf control had its own battery recall in Sept 2024, which inflated its complaints and made the Bolt look better than it was. I cut the window before that recall. I report the smaller number because the larger one was an artifact.

**"Why is β so different between cells (2–7) and the field (1.2)?"**
- **Cells:** the cell β is cycle-aging under a fixed protocol, which is pure wear-out.
- **Field:** the field β mixes failure modes (manufacturing defects, BMS faults, wear-out) across mixed usage, which pulls β toward 1.
That gap is why you separate failure modes before fitting, with Weibull mixtures or a fit per failure mode.

**"Your DOE optimum: would you ship that charge profile?"**
No. It's the best within the tested region (4.9C to 75%, then 3C, about 1,030 cycles), and it matches the best observed policies. I first got a corner solution the data never tested and rejected it as extrapolation. Next step: a confirmation run of 3–5 cells at that setting.

**"Why did the SPC alarm on a batch that lived longest?"**
Incoming capacity shifted down 1.3%, but capacity isn't the failure mechanism. Degradation rate is. That's why I chart the early-degradation residual, adjusted for charging policy, not just a spec-sheet metric.

**"What would you do with Tesla data?"**
- Replace complaints with service records and returned-pack teardown failure modes.
- Replace sales-based model-year weights with VIN-level build and in-service dates (exact censoring).
- Replace complaint counts with telemetry: cell voltage spread, self-discharge, temperature, BMS fault codes as leading indicators.
- Then build the alert on those signals, because complaint data alone gave no reliable early warning.

## Numbers to know cold
- Fleet B10: 331 cycles. Per-batch B10: 407 / 358 / 585 cycles.
- Batch effect adjusted for charging policy: 0.55× and 1.20×.
- DOE: R² 0.83, lack-of-fit p 0.40, C1×Q1 p < 0.001.
- Early-failure screen: recall 0.86, precision 0.78, AUC 0.91.
- Conformal coverage on the unseen batch: 87.5% (target 90%).
- Bolt fleet: 109,828 units, 1.66 battery complaints per 1,000 vehicles.
- Population model: β 1.22, 1.6 per 1,000 by 8 years, O/E 0.33.
- Early warning: 1 of 7 first-in-family recalls caught (negative result).
