import json, numpy as np, pandas as pd, matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
from scipy import stats
d=pd.read_csv("data/processed/cells_scored.csv"); spc=pd.read_csv("outputs/spc_cells.csv")
wb=pd.read_csv("outputs/weibull_by_lot.csv"); panel=pd.read_csv("outputs/bolt_did_panel.csv",parse_dates=["mo"])
al=pd.read_csv("outputs/field_alerts_monthly.csv",parse_dates=["month"])
plt.rcParams.update({"figure.dpi":130,"axes.spines.top":False,"axes.spines.right":False,"font.size":9})
# 1 Weibull probability plot by lot
fig,ax=plt.subplots(figsize=(6,4))
for (lot,g),col in zip(d.groupby("lot"),["#2a6f97","#c44536","#5b8c5a"]):
    x=np.sort(g.cycle_life.values); n=len(x); F=(np.arange(1,n+1)-0.3)/(n+0.4)
    ax.scatter(np.log(x),np.log(-np.log(1-F)),s=12,color=col,label=f"Lot {lot} (n={n})")
    r=wb[wb.lot==lot].iloc[0]; xx=np.linspace(x.min(),x.max(),50)
    ax.plot(np.log(xx),r.shape_beta*(np.log(xx)-np.log(r.scale_eta)),color=col,lw=1)
ax.axhline(np.log(-np.log(0.9)),ls=":",c="grey"); ax.text(np.log(150),np.log(-np.log(0.9))+0.1,"B10",color="grey")
ax.set_xlabel("ln(cycles to 80% capacity)"); ax.set_ylabel("ln(-ln(1-F))"); ax.set_title("Weibull probability plot by production lot"); ax.legend(frameon=False)
fig.tight_layout(); fig.savefig("outputs/figures/weibull_by_lot.png")
# 2 SPC chart q2
fig,ax=plt.subplots(figsize=(7,3.2)); s=spc[spc.metric=="q2"]
ax.plot(s.seq,s.value,".",c="#555",ms=4); ax.plot(s.seq,s.ewma,c="#2a6f97",lw=1.2,label="EWMA (λ=0.2)")
for k,ls in [("UCL","--"),("LCL","--"),("CL","-")]: ax.plot(s.seq,s[k],c="#c44536",ls=ls,lw=.8)
ax.plot(s.seq,s.ewma_LCL,c="#2a6f97",ls=":",lw=.8)
al_=s[s.ewma_alarm==1]; ax.scatter(al_.seq,al_.ewma,c="#c44536",s=10,zorder=3,label="EWMA alarm")
for lot,g in s.groupby("lot"): ax.axvline(g.seq.min()-.5,c="grey",lw=.5); ax.text(g.seq.min(),s.value.max(),lot,fontsize=7)
ax.set_ylabel("Initial discharge capacity (Ah)"); ax.set_xlabel("Cell (ordered by lot)"); ax.set_title("SPC: Phase I limits from first lot, Phase II monitoring"); ax.legend(frameon=False,fontsize=7,loc="lower left")
fig.tight_layout(); fig.savefig("outputs/figures/spc_initial_capacity.png")
# 3 DOE interaction: cycle life vs Q1 by C1 band
fig,ax=plt.subplots(figsize=(6,4)); d["C1_band"]=pd.cut(d.C1,[0,4.5,5.5,9],labels=["C1 ≤ 4.5C","4.5–5.5C","> 5.5C"])
for (b,g),col in zip(d.groupby("C1_band",observed=True),["#5b8c5a","#2a6f97","#c44536"]):
    ax.scatter(g.Q1,g.cycle_life,s=14,color=col,label=b); z=np.polyfit(g.Q1,np.log10(g.cycle_life),1); xx=np.linspace(g.Q1.min(),g.Q1.max(),20); ax.plot(xx,10**np.polyval(z,xx),color=col,lw=1)
ax.set_yscale("log"); ax.set_xlabel("Q1: SOC % at which step-1 current switches"); ax.set_ylabel("Cycle life"); ax.set_title("DOE: C1 × Q1 interaction"); ax.legend(frameon=False,title="Step-1 rate")
fig.tight_layout(); fig.savefig("outputs/figures/doe_interaction.png")
# 4 Bolt corrective action
fig,ax=plt.subplots(figsize=(7,3.2))
for b,lab,col in [(1,"Bolt MY2017-19 (remedied)","#c44536"),(0,"Leaf MY2011-19 (control)","#2a6f97")]:
    g=panel[panel.bolt==b].set_index("mo").n.rolling(3,min_periods=1).mean(); ax.plot(g.index,g.values,c=col,label=lab)
ax.axvspan(pd.Timestamp("2020-11-01"),pd.Timestamp("2022-06-30"),color="grey",alpha=.15); ax.text(pd.Timestamp("2020-12-01"),ax.get_ylim()[1]*.9,"recall + module\nreplacement rollout",fontsize=7)
ax.set_ylabel("Battery complaints / month (3-mo avg)"); ax.set_title("Corrective-action check: NHTSA battery complaints"); ax.legend(frameon=False,fontsize=7)
fig.tight_layout(); fig.savefig("outputs/figures/bolt_corrective_action.png")
# ---- Tableau extracts (tidy) ----
d.drop(columns=["C1_band"]).to_csv("tableau/cells.csv",index=False)
spc.to_csv("tableau/spc_cells.csv",index=False)
pd.read_csv("data/processed/complaints_clean.csv").to_csv("tableau/field_complaints.csv",index=False)
al.to_csv("tableau/field_alerts_monthly.csv",index=False)
panel.to_csv("tableau/bolt_did_panel.csv",index=False)
pd.read_csv("outputs/affected_population.csv").to_csv("tableau/affected_population.csv",index=False)
wb.to_csv("tableau/weibull_by_lot.csv",index=False)
print("ok")
