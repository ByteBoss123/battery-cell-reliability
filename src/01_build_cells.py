"""Build per-cell table from Severson et al. (2019) / Attia et al. (2021) public data.
Joins SI Table 9 (barcode, lot/batch date, charging policy, cycle life) to the
per-cell Q(V) arrays (cycles 2-100) and extracts early-life features."""
import re, numpy as np, pandas as pd
from pathlib import Path
R = Path("data/raw")
t9 = pd.read_csv(R/"severson_et_al_SI_table9.csv", encoding="utf-8-sig")
t9.columns = ["barcode","dataset","batch_date","cycle_life","policy"]
split = {"Train":"train","Prim. Test":"test1","Sec. test":"test2","Sec. Test":"test2"}
t9["split"] = t9["dataset"].map(split)
assert t9["split"].notna().all(), t9["dataset"].unique()
t9["idx"] = t9.groupby("split").cumcount()+1
# check ordering against author-exported cycle lives
for s in ["train","test1","test2"]:
    cl = pd.read_csv(R/f"severson_arrays/cycle_lives/{s}_cycle_lives.csv", header=None)[0].values
    assert (t9.loc[t9.split==s,"cycle_life"].values == cl).all(), s
t9["lot"] = pd.to_datetime(t9["batch_date"], format="%m/%d/%y").dt.strftime("%Y-%m-%d")
# parse charging policy: C1(Q1%)-C2  (some 3-step / other formats kept as NaN)
def parse(p):
    m = re.fullmatch(r"([\d.]+)C\(([\d.]+)%\)-([\d.]+)C", p.strip())
    return (float(m[1]), float(m[2]), float(m[3])) if m else (np.nan,)*3
t9[["C1","Q1","C2"]] = t9["policy"].apply(lambda p: pd.Series(parse(p)))
# time to charge 0-80% SOC (minutes): Q1% at C1, remaining (80-Q1)% at C2
t9["t80_min"] = 60*(t9.Q1/100/t9.C1 + (80-t9.Q1)/100/t9.C2)
feats=[]
for _,r in t9.iterrows():
    a = np.loadtxt(R/f"severson_arrays/{r.split}/cell{r.idx}.csv", delimiter=",")  # 1000 V points x cycles 2..100
    q10, q100 = a[:,8], a[:,98]          # columns: cycle n at index n-2
    dq = q100 - q10
    qd = a.max(axis=0)                   # discharge capacity per cycle (Ah)
    feats.append(dict(barcode=r.barcode,
        log_var_dq=np.log10(np.var(dq)), log_abs_min_dq=np.log10(abs(dq.min())),
        mean_dq=dq.mean(), q2=qd[0], q100=qd[98], qmax_minus_q2=qd.max()-qd[0],
        fade_slope_2_100=np.polyfit(np.arange(2,101), qd, 1)[0],
        fade_slope_91_100=np.polyfit(np.arange(91,101), qd[89:], 1)[0]))
df = t9.merge(pd.DataFrame(feats), on="barcode")
df.drop(columns="idx").to_csv("data/processed/cells.csv", index=False)
print(df.shape); print(df.groupby("lot").agg(n=("barcode","size"), median_life=("cycle_life","median"), min_life=("cycle_life","min"), max_life=("cycle_life","max")))
print("policies:", df.policy.nunique(), "| unparsed:", df.C1.isna().sum(), df.loc[df.C1.isna(),"policy"].unique()[:10])
print(df[["cycle_life","log_var_dq"]].corr())
