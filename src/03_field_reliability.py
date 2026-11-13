"""Gaps 2 & 5 on field data: NHTSA consumer complaints + recalls (public API, pulled Nov 13 2026)
for 6 EV nameplates. Complaints are a field-failure PROXY, not warranty returns.
Primary battery definition: complaint coded to a PROPULSION SYSTEM / TRACTION BATTERY component.
Sensitivity definition: component-coded OR 'battery/high-voltage' in the narrative (catches some 12V issues)."""
import json, numpy as np, pandas as pd, statsmodels.api as sm, statsmodels.formula.api as smf
from scipy import stats
NAMES={"B":"Chevrolet Bolt EV/EUV","K":"Hyundai Kona Electric","L":"Nissan Leaf","3":"Tesla Model 3","Y":"Tesla Model Y","I":"VW ID.4"}
c=pd.read_csv("data/raw/nhtsa_complaints_compact.csv",dtype={"flags":str,"incident_ym":str,"filed_ym":str,"model":str})
f=c["flags"].astype(str).str.zfill(4)
c["comp"],c["text"],c["fire"],c["crash"]=(f.str[i].astype(int) for i in range(4))
c["batt"]=c.comp; c["batt_broad"]=(c.comp|c.text)
c["my"]=2000+c.my
c["inc"]=pd.to_datetime(c.incident_ym,format="%Y%m",errors="coerce"); c["filed"]=pd.to_datetime(c.filed_ym,format="%Y%m",errors="coerce")
bad = c.inc.isna() | (c.inc<pd.Timestamp(year=2009,month=1,day=1)) | (c.inc>c.filed)
c.loc[bad,"inc"]=pd.NaT
# vehicle age at incident: months since Oct 1 of (MY-1) (approximate start of model-year sales)
c["age_mo"]=((c.inc.dt.year-(c.my-1))*12 + c.inc.dt.month-10)
c.loc[c.age_mo<0,"age_mo"]=np.nan
c.to_csv("data/processed/complaints_clean.csv",index=False)
rec=pd.read_csv("data/raw/nhtsa_recalls.csv"); units=pd.read_csv("data/raw/nhtsa_battery_recall_units.csv",parse_dates=["report_date"])
out={"n_complaints":len(c),"bad_incident_dates":int(bad.sum())}

# ---- summary by nameplate ----
s=c.groupby("model").agg(complaints=("odi","size"),batt=("batt","sum"),batt_broad=("batt_broad","sum"),batt_fire=("fire",lambda x:int((x&c.loc[x.index,"batt"]).sum())),
                         my_min=("my","min"),my_max=("my","max"))
s["batt_share_%"]=(100*s.batt/s.complaints).round(1); s.index=s.index.map(NAMES)
s.to_csv("outputs/field_summary.csv"); out["summary"]=s.reset_index().to_dict("records"); print(s)

# ---- Weibull on age-at-failure, MYs with >=48 months observed, failures within 48 months ----
rows=[]
obs_end=c.filed.max()
for m,g in c[c.batt==1].groupby("model"):
    g=g[(g.age_mo.notna())]
    g=g[((obs_end.year-(g.my-1))*12+obs_end.month-10>=48)&(g.age_mo<=48)]
    if len(g)<20: continue
    x=g.age_mo.values+0.5
    k,_,lam=stats.weibull_min.fit(x,floc=0)
    bk=[stats.weibull_min.fit(np.random.default_rng(i).choice(x,len(x)),floc=0)[0] for i in range(300)]
    rows.append(dict(model=NAMES[m],n=len(x),shape_beta=round(k,2),beta_lo=round(np.percentile(bk,2.5),2),beta_hi=round(np.percentile(bk,97.5),2),scale_months=round(lam,1),median_age_mo=float(np.median(x))))
wf=pd.DataFrame(rows); wf.to_csv("outputs/field_weibull_age.csv",index=False); out["field_weibull"]=wf.to_dict("records"); print(wf)

# ---- affected population: official recall populations + complaint rate per 1,000 units ----
coh={"20V701000":("B",[2017,2018,2019]),"21V650000":("B",[2020,2021,2022]),"20V630000":("K",[2019,2020]),"23V040000":("I",[2021]),"24V700000":("L",[2019,2020]),"26V030000":("I",[2023])}
ap=[]
for camp,(m,mys) in coh.items():
    u=units.set_index("campaign").loc[camp]
    g=c[(c.model==m)&(c.my.isin(mys))]
    ap.append(dict(campaign=camp,model=NAMES[m],model_years="-".join(map(str,[min(mys),max(mys)])),recall_report=str(u.report_date.date()),units_affected=int(u.units_affected),
        batt_complaints_before_recall=int(((g.batt==1)&(g.filed<u.report_date)).sum()),batt_complaints_total=int(g.batt.sum())))
# Full Bolt fleet: 21V560 (MY2017-19) + 21V650 (MY2020-22 EV + 2022 EUV) together cover every Bolt -> valid denominator
bolt_units=int(units.set_index("campaign").loc[["21V560000","21V650000"],"units_affected"].sum())
gb=c[(c.model=="B")&(c.my<=2022)]
out["bolt_fleet_rate"]=dict(units=bolt_units,batt_complaints=int(gb.batt.sum()),per_1000=round(1000*gb.batt.sum()/bolt_units,2),
   batt_fire_complaints=int(((gb.batt_broad==1)&(gb.fire==1)).sum()))
print(out["bolt_fleet_rate"])
ap=pd.DataFrame(ap); ap.to_csv("outputs/affected_population.csv",index=False); out["affected"]=ap.to_dict("records"); print(ap.to_string(index=False))

# ---- corrective-action effectiveness: Bolt MY2017-2019 battery-module replacement (20V701 -> 21V560) ----
# Closed cohorts (no vehicles added after 2019): treated = Bolt MY2017-19, comparison = Nissan Leaf MY2011-19.
# Monthly component-coded battery complaints by incident month; recall/remedy rollout window excluded.
months=pd.date_range("2019-01-01","2025-12-01",freq="MS")
def series(sel,col="batt"):
    m=c[(c[col]==1)].dropna(subset=["inc"]); m=m[sel(m)]
    return m.inc.dt.to_period("M").dt.to_timestamp().value_counts().reindex(months,fill_value=0).values
res={}
for col in ["batt","batt_broad"]:
    panel=pd.concat([pd.DataFrame({"mo":months,"n":series(lambda m:(m.model=="B")&(m.my<=2019),col),"bolt":1}),
                     pd.DataFrame({"mo":months,"n":series(lambda m:(m.model=="L")&(m.my<=2019),col),"bolt":0})])
    panel["period"]=np.where(panel.mo<"2020-11-01","pre",np.where(panel.mo<"2022-07-01","rollout","post"))
    # primary post window ends 2024-07, before the Leaf's own battery recall (24V700, Sep 2024) spikes the control
    for end,tag in [("2024-07-01","primary_post_to_2024-07"),("2025-12-01","sensitivity_post_to_2025-12")]:
     p2=panel[(panel.period!="rollout")&(panel.mo<=end)].copy(); p2["post"]=(p2.period=="post").astype(int)
     did=smf.glm("n ~ bolt*post",p2,family=sm.families.Poisson()).fit(cov_type="HC0")
     rates=p2.groupby(["bolt","period"]).n.mean().unstack().round(2)
     res[col+"|"+tag]=dict(bolt_monthly_pre=float(rates.loc[1,"pre"]),bolt_monthly_post=float(rates.loc[1,"post"]),
        leaf_monthly_pre=float(rates.loc[0,"pre"]),leaf_monthly_post=float(rates.loc[0,"post"]),
        bolt_change_pct=round(100*(rates.loc[1,"post"]/rates.loc[1,"pre"]-1),1),
        did_rate_ratio=round(float(np.exp(did.params["bolt:post"])),3),ci95=np.exp(did.conf_int().loc["bolt:post"]).round(3).tolist(),p=float(did.pvalues["bolt:post"]))
    if col=="batt": panel.to_csv("outputs/bolt_did_panel.csv",index=False)
out["corrective_action"]=dict(design="Poisson difference-in-differences; treated Bolt MY2017-19, control Leaf MY2011-19; pre 2019-01..2020-10, rollout 2020-11..2022-06 excluded; post 2022-07..2024-07 (primary) or ..2025-12 (sensitivity)",**res)
print(json.dumps(out["corrective_action"],indent=1))
# Bolt battery-fire complaints by year (harder outcome, less sensitive to recall-driven reporting)
bf=c[(c.model=="B")&(c.batt_broad==1)&(c.fire==1)].dropna(subset=["inc"]); out["bolt_fire_by_year"]=bf.groupby(bf.inc.dt.year).size().to_dict()

# ---- automated field alerting: monthly battery complaints by FILED month (data as it arrives) ----
# Rule: alert when count > Poisson 99.865% upper limit of trailing 12-month mean (c-chart, min baseline 0.5/mo),
# or EWMA(0.3) exceeds its 3-sigma limit. Then measure lead time vs the nameplate's battery recalls.
m2=c[c.batt==1].dropna(subset=["filed"]).copy(); m2["mo"]=m2.filed.dt.to_period("M").dt.to_timestamp()
al=[]; lead=[]
camp_model={"20V630000":"K","21V127000":"K","20V701000":"B","21V560000":"B","21V650000":"B","24V481000":"B","24V812000":"B","22V162000":"I","23V040000":"I","25V836000":"I","26V028000":"I","26V030000":"I","26V630000":"I","23V434000":"3","24V700000":"L","25V655000":"L"}
for mod in NAMES:
    ser=m2[m2.model==mod].groupby("mo").size().reindex(pd.date_range("2011-01-01",c.filed.max(),freq="MS"),fill_value=0)
    first=ser[ser>0].index.min(); ser=ser[ser.index>=first]
    base=ser.shift(1).rolling(12,min_periods=6).mean().clip(lower=0.5)
    ucl=pd.Series(stats.poisson.ppf(0.99865,base),index=base.index)
    ew=ser.ewm(alpha=0.3,adjust=False).mean().shift(1); ew_ucl=base+3*np.sqrt(base*0.3/(2-0.3))
    flag=((ser>ucl)|(ser.ewm(alpha=0.3,adjust=False).mean()>ew_ucl)) & base.notna()
    for t in ser.index: al.append(dict(model=NAMES[mod],month=t.date(),count=int(ser[t]),baseline=None if pd.isna(base[t]) else round(base[t],2),ucl=None if pd.isna(ucl[t]) else float(ucl[t]),alert=int(flag[t])))
    for camp,mm in camp_model.items():
        if mm!=mod: continue
        rd=units.set_index("campaign").loc[camp,"report_date"]
        prior=flag[(flag.index<rd)&(flag.index>=rd-pd.DateOffset(months=12))]
        fa=prior[prior].index.min()
        lead.append(dict(campaign=camp,model=NAMES[mod],recall_report=str(rd.date()),alert_within_12mo_before=bool(prior.any()),
                         first_alert=None if pd.isna(fa) else str(fa.date()),lead_months=None if pd.isna(fa) else int((rd.year-fa.year)*12+rd.month-fa.month)))
al=pd.DataFrame(al); al.to_csv("outputs/field_alerts_monthly.csv",index=False)
ld=pd.DataFrame(lead); ld.to_csv("outputs/alert_lead_time.csv",index=False); out["alert_lead"]=ld.to_dict("records")
out["alert_rate"]=dict(alert_months=int(al.alert.sum()),months=len(al))
print(ld.to_string(index=False)); print(out["alert_rate"])
json.dump(out,open("outputs/field_results.json","w"),indent=1,default=str)
