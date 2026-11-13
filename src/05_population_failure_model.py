"""Population-level failure-rate prediction for an affected population, and a second
corrective-action check (observed vs model-expected failures).

Cohort: every 2017-2019 Chevrolet Bolt EV recalled under 21V560 (57,414 units, NHTSA).
Failure proxy: component-coded traction-battery/propulsion complaint (incident date).
Fit window: before the first Bolt battery recall (incident < 2020-11-01), so the fit
is not distorted by recall-driven reporting. Units without a complaint are right-censored
at their age on 2020-10-31. Age = months since Oct 1 of (MY-1).
MY split: US calendar-year sales (GM-reported: 2016 579 + 2017 23,297; 2018 18,019; 2019 16,418;
total 58,313, within 1.6% of the 57,414 recall population) used as MY shares. Calendar year is a
proxy for model year; the extreme splits (all oldest / all newest) are reported as bounds."""
import json, numpy as np, pandas as pd
from scipy import optimize, stats
c=pd.read_csv("data/processed/complaints_clean.csv",parse_dates=["inc","filed"],dtype={"model":str})
N=57414; MYS=[2017,2018,2019]
def age(ts,my): return (ts.year-(my-1))*12+ts.month-10
f=c[(c.model=="B")&(c.my.isin(MYS))&(c.batt==1)&c.inc.notna()].copy()
f["age"]=[age(t,m) for t,m in zip(f.inc,f.my)]
pre=f[f.inc<"2020-11-01"]
cens_t=pd.Timestamp("2020-10-31")
def fit(weights):
    # failures: exact ages (+0.5 month midpoint); survivors censored at their MY's age on cens_t
    fa=pre.age.values+0.5
    cens=[(age(cens_t,m)+0.5, N*w - (pre.my==m).sum()) for m,w in zip(MYS,weights)]
    def nll(p):
        k,lam=np.exp(p)
        ll=np.sum(stats.weibull_min.logpdf(fa,k,scale=lam))
        ll+=sum(n*stats.weibull_min.logsf(t,k,scale=lam) for t,n in cens)
        return -ll
    r=optimize.minimize(nll,[np.log(1.5),np.log(5000)],method="Nelder-Mead",options={"xatol":1e-8,"fatol":1e-8,"maxiter":5000})
    k,lam=np.exp(r.x)
    H=optimize.approx_fprime(r.x,nll,1e-5); 
    # numerical Hessian for CIs on log params
    eps=1e-4; Hm=np.zeros((2,2))
    for i in range(2):
        e=np.zeros(2); e[i]=eps
        Hm[i]=(optimize.approx_fprime(r.x+e,nll,1e-6)-optimize.approx_fprime(r.x-e,nll,1e-6))/(2*eps)
    cov=np.linalg.inv(Hm)
    return k,lam,cov,r.x
sales=np.array([579+23297,18019,16418]); scen={"sales_weighted":list(sales/sales.sum()),"equal_split":[1/3,1/3,1/3],"all_MY2017":[1,0,0],"all_MY2019":[0,0,1]}
win0,win1=pd.Timestamp("2022-07-01"),pd.Timestamp("2024-07-31")   # post-remedy window (same as DiD primary)
obs=int(((f.inc>=win0)&(f.inc<=win1)).sum())
res={"cohort_units":N,"pre_recall_failures":int(len(pre)),"observed_post_remedy_2022-07_to_2024-07":obs,"scenarios":{}}
rng=np.random.default_rng(0)
for name,w in scen.items():
    k,lam,cov,x=fit(w)
    def expected(kk,ll):
        e=0.0
        for m,wt in zip(MYS,w):
            a0,a1=age(win0,m),age(win1,m)+1
            F=lambda a: stats.weibull_min.cdf(a,kk,scale=ll)
            e+=N*wt*(F(a1)-F(a0))       # expected failures in window if no remedy (ignores removals)
        return e
    E=expected(k,lam)
    draws=rng.multivariate_normal(x,cov,2000); Es=np.array([expected(*np.exp(d)) for d in draws])
    F96=stats.weibull_min.cdf(96,k,scale=lam)
    F96s=np.array([stats.weibull_min.cdf(96,*np.exp(d)[[0]],scale=np.exp(d[1])) for d in draws])
    oe=obs/E; lo,hi=stats.chi2.ppf(.025,2*obs)/2/E, stats.chi2.ppf(.975,2*obs+2)/2/E
    res["scenarios"][name]=dict(shape_beta=round(k,2),beta_95=np.exp(x[0]+np.array([-1.96,1.96])*np.sqrt(cov[0,0])).round(2).tolist(),
        scale_months=round(lam,0),
        projected_complaint_rate_per_1000_by_96mo=round(1000*F96,2),proj_96_95=(1000*np.percentile(F96s,[2.5,97.5])).round(2).tolist(),
        projected_units_affected_by_96mo=int(round(N*F96)),
        expected_no_remedy_in_window=round(E,1),expected_95=np.percentile(Es,[2.5,97.5]).round(1).tolist(),
        observed_over_expected=round(oe,2),OE_95_poisson=[round(lo,2),round(hi,2)])
print(json.dumps(res,indent=1))
json.dump(res,open("outputs/population_failure_model.json","w"),indent=1)
