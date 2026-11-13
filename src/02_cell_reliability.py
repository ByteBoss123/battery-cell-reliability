"""Gaps 2-4 at cell level: Weibull life by lot, early-life failure prediction,
SPC on incoming-quality metrics with lot traceability, and DOE / response surface
on the charging-policy factors. Data: Severson et al. 2019 (124 LFP/graphite cells)."""
import json, numpy as np, pandas as pd, statsmodels.formula.api as smf
from scipy import stats
from sklearn.linear_model import ElasticNetCV
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline
from lifelines import WeibullAFTFitter
rng = np.random.default_rng(0)
d = pd.read_csv("data/processed/cells.csv")
out = {}

# ---------- 1. Weibull life-data analysis by lot ----------
def weib(x):
    k, _, lam = stats.weibull_min.fit(x, floc=0)
    return k, lam, lam*(-np.log(0.9))**(1/k)          # shape, scale, B10
rows=[]
for lot, g in [("ALL", d)] + list(d.groupby("lot")):
    x = g.cycle_life.values; k, lam, b10 = weib(x)
    bs = np.array([weib(rng.choice(x, len(x)))[2] for _ in range(1000)])
    ks = stats.kstest(x, "weibull_min", args=(k, 0, lam)).pvalue
    rows.append(dict(lot=lot, n=len(x), shape_beta=k, scale_eta=lam, B10=b10,
                     B10_lo=np.percentile(bs,2.5), B10_hi=np.percentile(bs,97.5), KS_p=ks))
wb = pd.DataFrame(rows).round(3); wb.to_csv("outputs/weibull_by_lot.csv", index=False); out["weibull"]=wb.to_dict("records")
print(wb.to_string(index=False))

# Lot effect adjusted for charging policy (lots share almost no policies -> confounded otherwise)
aft = WeibullAFTFitter()
X = d[["cycle_life","C1","Q1","C2"]].copy()
X["lot_2017_06_30"] = (d.lot=="2017-06-30").astype(int); X["lot_2018_04_12"]=(d.lot=="2018-04-12").astype(int)
aft.fit(X, "cycle_life")
s = aft.summary.loc["lambda_"][["exp(coef)","exp(coef) lower 95%","exp(coef) upper 95%","p"]].round(4)
s.to_csv("outputs/weibull_aft_lot_adjusted.csv"); out["aft"]=s.reset_index().to_dict("records"); print(s)

# ---------- 2. Early-life failure prediction (first 100 cycles) ----------
F = ["log_var_dq","log_abs_min_dq","q2","qmax_minus_q2","fade_slope_2_100","fade_slope_91_100"]
tr, t1, t2 = (d[d.split==s] for s in ["train","test1","test2"])
m = make_pipeline(StandardScaler(), ElasticNetCV(l1_ratio=[.1,.5,.9,1], cv=5, random_state=0, max_iter=50000))
m.fit(tr[F], np.log10(tr.cycle_life))
def ev(df, name):
    p = 10**m.predict(df[F]); e=p-df.cycle_life
    return dict(set=name, n=len(df), RMSE=float(np.sqrt((e**2).mean())), MAPE=float((abs(e)/df.cycle_life).mean()*100))
# univariate baseline: log variance of dQ only
u = np.polyfit(tr.log_var_dq, np.log10(tr.cycle_life), 1)
def evu(df,name):
    p=10**np.polyval(u, df.log_var_dq); e=p-df.cycle_life
    return dict(set=name+" (variance-only)", n=len(df), RMSE=float(np.sqrt((e**2).mean())), MAPE=float((abs(e)/df.cycle_life).mean()*100))
pr = pd.DataFrame([ev(tr,"train"),ev(t1,"test1"),ev(t2,"test2 (new lot)"),evu(t1,"test1"),evu(t2,"test2 (new lot)")]).round(1)
pr.to_csv("outputs/early_life_prediction.csv", index=False); out["prediction"]=pr.to_dict("records"); print(pr.to_string(index=False))
d["pred_life"] = 10**m.predict(d[F])
# early-failure screening: flag cells predicted below fleet B10, evaluate on held-out sets
b10_all = wb.loc[wb.lot=="ALL","B10"].item()
for s_ in ["test1","test2"]:
    g=d[d.split==s_]; tp=((g.pred_life<b10_all)&(g.cycle_life<b10_all)).sum()
    out.setdefault("screen",[]).append(dict(set=s_, actual_early=int((g.cycle_life<b10_all).sum()), flagged=int((g.pred_life<b10_all).sum()), true_flags=int(tp)))
print(out["screen"])

# ---------- 3. SPC with lot traceability ----------
# Phase I limits from lot 2017-05-12; Phase II monitoring of later lots.
# Metric A: q2 (initial discharge capacity, an incoming-quality metric unaffected by policy yet)
# Metric B: policy-adjusted early-degradation residual (log_var_dq minus policy-factor fit)
pol = smf.ols("log_var_dq ~ C1 + Q1 + C2", d).fit(); d["dq_resid"]=pol.resid
d = d.sort_values(["lot","barcode"]).reset_index(drop=True); d["seq"]=np.arange(1,len(d)+1)
spc=[]
for metric in ["q2","dq_resid"]:
    ph1 = d[d.lot=="2017-05-12"][metric].values
    mr = np.abs(np.diff(ph1)).mean(); sigma = mr/1.128; cl = ph1.mean()
    ucl, lcl = cl+3*sigma, cl-3*sigma
    x = d[metric].values; z = (x-cl)/sigma
    r1 = (np.abs(z)>3)
    r2 = np.zeros(len(x),bool)   # WE rule 2: 2 of 3 beyond 2 sigma same side
    r4 = np.zeros(len(x),bool)   # WE rule 4: 8 consecutive same side
    for i in range(len(x)):
        w=z[max(0,i-2):i+1]
        if (w>2).sum()>=2 or (w<-2).sum()>=2: r2[i]=True
        w=z[max(0,i-7):i+1]
        if len(w)==8 and ((w>0).all() or (w<0).all()): r4[i]=True
    lam=0.2; e=np.zeros(len(x)); prev=cl
    for i,v in enumerate(x): prev=lam*v+(1-lam)*prev; e[i]=prev
    ew_lim = 3*sigma*np.sqrt(lam/(2-lam))
    for i in range(len(x)):
        spc.append(dict(seq=d.seq[i], barcode=d.barcode[i], lot=d.lot[i], metric=metric, value=x[i], CL=cl, UCL=ucl, LCL=lcl,
                        ewma=e[i], ewma_UCL=cl+ew_lim, ewma_LCL=cl-ew_lim, rule1=int(r1[i]), rule2=int(r2[i]), rule4=int(r4[i]),
                        ewma_alarm=int(abs(e[i]-cl)>ew_lim), cycle_life=d.cycle_life[i]))
spc=pd.DataFrame(spc); spc.to_csv("outputs/spc_cells.csv", index=False)
spc["any"]=spc[["rule1","rule2","rule4","ewma_alarm"]].max(axis=1)
sp = spc.groupby(["metric","lot"]).agg(n=("seq","size"), rule1=("rule1","sum"), rule2=("rule2","sum"), rule4=("rule4","sum"), ewma=("ewma_alarm","sum"), mean=("value","mean")).round(4)
spc["dq_upper_alarm"]=((spc.metric=="dq_resid")&(spc.ewma>spc.ewma_UCL)).astype(int)
sp["ewma_upper_dq"]=spc.groupby(["metric","lot"]).dq_upper_alarm.sum()
print(sp); out["spc"]=sp.reset_index().to_dict("records")
# Do out-of-control cells (q2 or residual) have shorter life? (traceability check)
fl = spc.groupby("barcode")["any"].max(); dd=d.set_index("barcode").join(fl)
mw = stats.mannwhitneyu(dd[dd["any"]==1].cycle_life, dd[dd["any"]==0].cycle_life)
out["spc_life"]=dict(flagged_n=int((dd["any"]==1).sum()), flagged_median=float(dd[dd["any"]==1].cycle_life.median()),
                     unflagged_median=float(dd[dd["any"]==0].cycle_life.median()), mannwhitney_p=float(mw.pvalue))
print(out["spc_life"])

# ---------- 4. DOE / response surface on charging factors ----------
d["ly"]=np.log10(d.cycle_life)
full = smf.ols("ly ~ C(lot) + C1 + Q1 + C2 + C1:Q1 + C1:C2 + Q1:C2 + I(C1**2) + I(C2**2) + I(Q1**2)", d).fit()  # lot = blocking factor
main = smf.ols("ly ~ C(lot) + C1 + Q1 + C2", d).fit()
import statsmodels.api as sm
an = sm.stats.anova_lm(full, typ=2).round(4); an.to_csv("outputs/doe_anova.csv"); print(an)
# lack-of-fit using replicated policies (pure error)
g = d.groupby("policy")["ly"]; sse_pe = ((d.ly - g.transform("mean"))**2).sum(); df_pe = len(d)-d.policy.nunique()
sse_lof = full.ssr - sse_pe; df_lof = full.df_resid - df_pe
F_lof = (sse_lof/df_lof)/(sse_pe/df_pe); p_lof = 1-stats.f.cdf(F_lof, df_lof, df_pe)
out["doe"]=dict(r2_main=main.rsquared, r2_full=full.rsquared, adj_r2_full=full.rsquared_adj, n_policies=int(d.policy.nunique()),
                replicated_policies=int((d.policy.value_counts()>1).sum()), lack_of_fit_F=F_lof, lack_of_fit_p=p_lof,
                params=full.params.round(5).to_dict(), pvalues=full.pvalues.round(4).to_dict())
print(json.dumps({k:v for k,v in out["doe"].items() if k not in("params","pvalues")}, indent=1))
# predicted best policy within observed factor ranges at ~10-min 0-80% charge (grid search)
G = pd.DataFrame([(c1,q1,c2) for c1 in np.arange(3,8.01,.1) for q1 in range(5,76,1) for c2 in np.arange(3,6.01,.1)], columns=["C1","Q1","C2"])
G["t80_min"]=60*(G.Q1/100/G.C1+(80-G.Q1)/100/G.C2); G=G[(G.t80_min>=9.8)&(G.t80_min<=10.2)]
from scipy.spatial import cKDTree
obs = d[["C1","Q1","C2"]].drop_duplicates().values; sc = obs.std(axis=0)
dist,_ = cKDTree(obs/sc).query(G[["C1","Q1","C2"]].values/sc); G=G[dist<0.5].copy()   # stay near tested policies
G["lot"]="2017-05-12"; G["pred_life"]=10**full.predict(G); best=G.sort_values("pred_life").tail(1)
out["doe"]["best_10min"]=best.round(2).to_dict("records")[0]
obs10 = d[(d.t80_min.round(1).between(9.8,10.2))]
out["doe"]["observed_best_10min"]=obs10.groupby("policy").cycle_life.mean().sort_values().tail(3).to_dict()
print(out["doe"]["best_10min"], out["doe"]["observed_best_10min"])
d.to_csv("data/processed/cells_scored.csv", index=False)
json.dump(out, open("outputs/cell_results.json","w"), indent=1, default=float)
