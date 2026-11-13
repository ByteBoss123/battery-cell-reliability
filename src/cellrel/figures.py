"""Render report figures from pipeline outputs."""
from __future__ import annotations

import json

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from .config import Paths  # noqa: E402

COLORS = ["#2a6f97", "#c44536", "#5b8c5a"]


def render(paths: Paths | None = None) -> None:
    paths = paths or Paths()
    out, t = paths.outputs / "figures", paths.outputs / "tables"
    out.mkdir(exist_ok=True)
    m = json.load(open(paths.outputs / "metrics.json"))
    cells = pd.read_csv(t / "cells.csv")
    plt.rcParams.update({"figure.dpi": 130, "axes.spines.top": False, "axes.spines.right": False, "font.size": 9})

    wb = {w["lot"]: w for w in m["cells"]["weibull_by_batch"]}
    fig, ax = plt.subplots(figsize=(6, 4))
    for (lot, g), col in zip(cells.groupby("lot"), COLORS, strict=True):
        x = np.sort(g.cycle_life.to_numpy())
        F = (np.arange(1, len(x) + 1) - 0.3) / (len(x) + 0.4)          # Bernard median ranks
        ax.scatter(np.log(x), np.log(-np.log(1 - F)), s=12, color=col, label=f"Test batch {lot} (n={len(x)})")
        xx = np.linspace(x.min(), x.max(), 50)
        ax.plot(np.log(xx), wb[lot]["shape_beta"] * (np.log(xx) - np.log(wb[lot]["scale_eta"])), color=col, lw=1)
    ax.axhline(np.log(-np.log(0.9)), ls=":", c="grey")
    ax.set(xlabel="ln(cycles to 80% capacity)", ylabel="ln(-ln(1-F))", title="Weibull probability plot by test batch")
    ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(out / "weibull_by_batch.png")

    s = pd.read_csv(t / "spc_cells.csv").query("metric == 'q2'")
    fig, ax = plt.subplots(figsize=(7, 3.2))
    ax.plot(s.seq, s.value, ".", c="#555", ms=4)
    ax.plot(s.seq, s.ewma, c=COLORS[0], lw=1.2, label="EWMA (λ=0.2)")
    for k in ("UCL", "CL", "LCL"):
        ax.plot(s.seq, s[k], c=COLORS[1], ls="-" if k == "CL" else "--", lw=.8)
    ax.plot(s.seq, s.ewma_LCL, c=COLORS[0], ls=":", lw=.8)
    a = s[s.ewma_alarm == 1]
    ax.scatter(a.seq, a.ewma, c=COLORS[1], s=10, zorder=3, label="EWMA alarm")
    for lot, g in s.groupby("lot"):
        ax.axvline(g.seq.min() - .5, c="grey", lw=.5)
        ax.text(g.seq.min(), s.value.max(), lot, fontsize=7)
    ax.set(ylabel="Initial discharge capacity (Ah)", xlabel="Cell (ordered by test batch)",
           title="SPC: Phase I limits from first test batch, Phase II monitoring")
    ax.legend(frameon=False, fontsize=7, loc="lower left")
    fig.tight_layout()
    fig.savefig(out / "spc_initial_capacity.png")

    fig, ax = plt.subplots(figsize=(6, 4))
    cells["band"] = pd.cut(cells.C1, [0, 4.5, 5.5, 9], labels=["C1 ≤ 4.5C", "4.5–5.5C", "> 5.5C"])
    for (b, g), col in zip(cells.groupby("band", observed=True), [COLORS[2], COLORS[0], COLORS[1]], strict=True):
        ax.scatter(g.Q1, g.cycle_life, s=14, color=col, label=b)
        z = np.polyfit(g.Q1, np.log10(g.cycle_life), 1)
        xx = np.linspace(g.Q1.min(), g.Q1.max(), 20)
        ax.plot(xx, 10 ** np.polyval(z, xx), color=col, lw=1)
    ax.set(yscale="log", xlabel="Q1: SOC % at which step-1 current switches", ylabel="Cycle life", title="DOE: C1 × Q1 interaction")
    ax.legend(frameon=False, title="Step-1 rate")
    fig.tight_layout()
    fig.savefig(out / "doe_interaction.png")

    p = pd.read_csv(t / "corrective_action_panel.csv", parse_dates=["month"])
    fig, ax = plt.subplots(figsize=(7, 3.2))
    for tr, lab, col in ((1, "Bolt MY2017-19 (remedied)", COLORS[1]), (0, "Leaf MY2011-19 (control)", COLORS[0])):
        g = p[p.treated == tr].set_index("month").n.rolling(3, min_periods=1).mean()
        ax.plot(g.index, g.values, c=col, label=lab)
    ax.axvspan(pd.Timestamp("2020-11-01"), pd.Timestamp("2022-06-30"), color="grey", alpha=.15)
    ax.axvline(pd.Timestamp("2024-07-31"), c="grey", ls=":", lw=.8)
    ax.text(pd.Timestamp("2020-12-01"), ax.get_ylim()[1] * .88, "recall + module\nreplacement rollout", fontsize=7)
    ax.text(pd.Timestamp("2024-08-15"), ax.get_ylim()[1] * .88, "primary window ends\n(control's own recall next)", fontsize=7)
    ax.set(ylabel="Battery complaints / month (3-mo avg)", title="Corrective-action check: NHTSA battery complaints")
    ax.legend(frameon=False, fontsize=7, loc="center right")
    fig.tight_layout()
    fig.savefig(out / "corrective_action.png")
    plt.close("all")
