"""Fleet-size-normalized alerting. Rule fixed BEFORE looking at results:
monthly share of complaints that are battery-coded (filed month), per nameplate;
alert if share > p_bar + 3*sqrt(p_bar(1-p_bar)/n_t), where p_bar = pooled share over the
trailing 12 months (current month excluded), and the month has n_t >= 10 complaints and
>= 3 battery complaints. Evaluated against all 16 traction-battery recalls (alert in the
12 months before the recall report date). Follow-on = an earlier battery recall of the same
nameplate was reported within the prior 24 months."""
import json, numpy as np, pandas as pd
c=pd.read_csv("data/processed/complaints_clean.csv",parse_dates=["filed"],dtype={"model":str})
units=pd.read_csv("data/raw/nhtsa_battery_recall_units.csv",parse_dates=["report_date"])
NAMES={"B":"Chevrolet Bolt EV/EUV","K":"Hyundai Kona Electric","L":"Nissan Leaf","3":"Tesla Model 3","Y":"Tesla Model Y","I":"VW ID.4"}
camp_model={"20V630000":"K","21V127000":"K","20V701000":"B","21V560000":"B","21V650000":"B","24V481000":"B","24V812000":"B","22V162000":"I","23V040000":"I","25V836000":"I","26V028000":"I","26V030000":"I","26V630000":"I","23V434000":"3","24V700000":"L","25V655000":"L"}
c["mo"]=c.filed.dt.to_period("M").dt.to_timestamp()
rows=[]; flags={}
for m in NAMES:
    g=c[c.model==m].groupby("mo").agg(n=("odi","size"),b=("batt","sum"))
    g=g.reindex(pd.date_range(g.index.min(),c.mo.max(),freq="MS"),fill_value=0)
    pb=(g.b.shift(1).rolling(12,min_periods=6).sum()/g.n.shift(1).rolling(12,min_periods=6).sum())
    ucl=pb+3*np.sqrt(pb*(1-pb)/g.n.replace(0,np.nan))
    p=g.b/g.n.replace(0,np.nan)
    a=(p>ucl)&(g.n>=10)&(g.b>=3)
    flags[m]=a
    for t in g.index: rows.append(dict(model=NAMES[m],month=t.date(),complaints=int(g.n[t]),battery=int(g.b[t]),share=None if pd.isna(p[t]) else round(p[t],4),
                                        p_bar=None if pd.isna(pb[t]) else round(pb[t],4),ucl=None if pd.isna(ucl[t]) else round(ucl[t],4),alert=int(a[t])))
al=pd.DataFrame(rows); al.to_csv("outputs/pchart_alerts_monthly.csv",index=False)
u=units.set_index("campaign")
ev=[]
for camp,m in camp_model.items():
    rd=u.loc[camp,"report_date"]
    earlier=[k for k,mm in camp_model.items() if mm==m and u.loc[k,"report_date"]<rd and u.loc[k,"report_date"]>=rd-pd.DateOffset(months=24)]
    f=flags[m]; w=f[(f.index<rd)&(f.index>=rd-pd.DateOffset(months=12))]
    fa=w[w].index.min()
    ev.append(dict(campaign=camp,model=NAMES[m],report=str(rd.date()),follow_on=bool(earlier),alert_12mo_before=bool(w.any()),
                   lead_months=None if pd.isna(fa) else int((rd.year-fa.year)*12+rd.month-fa.month)))
ev=pd.DataFrame(ev); ev.to_csv("outputs/pchart_recall_eval.csv",index=False)
first=ev[~ev.follow_on]
res=dict(alert_months=int(al.alert.sum()),nameplate_months=int(al.share.notna().sum()),
         recalls_with_alert=f"{int(ev.alert_12mo_before.sum())}/{len(ev)}",
         first_in_family_with_alert=f"{int(first.alert_12mo_before.sum())}/{len(first)}",
         detail=ev.to_dict("records"))
print(ev.to_string(index=False)); print({k:v for k,v in res.items() if k!="detail"})
json.dump(res,open("outputs/pchart_results.json","w"),indent=1,default=str)
