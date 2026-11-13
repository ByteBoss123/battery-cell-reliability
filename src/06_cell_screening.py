"""Early-life cell screening from the first 100 cycles.
(a) Severson-style feature set incl. dQ skewness/kurtosis; (b) split-conformal 90% prediction
intervals (fit on train, calibrate on test1, evaluate coverage on test2 = unseen batch);
(c) early-failure classifier (cycle life < 550, the threshold used by Severson et al.)."""
import json, numpy as np, pandas as pd
from pathlib import Path
from scipy import stats
from sklearn.linear_model import ElasticNetCV, LogisticRegressionCV
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline
from sklearn.metrics import precision_score, recall_score, accuracy_score, roc_auc_score
d=pd.read_csv("data/processed/cells_scored.csv")
R=Path("data/raw/severson_arrays")
t9=pd.read_csv("data/raw/severson_et_al_SI_table9.csv",encoding="utf-8-sig"); t9.columns=["barcode","dataset","batch_date","cycle_life","policy"]
t9["split"]=t9.dataset.map({"Train":"train","Prim. Test":"test1","Sec. test":"test2","Sec. Test":"test2"}); t9["idx"]=t9.groupby("split").cumcount()+1
extra=[]
for _,r in t9.iterrows():
    a=np.loadtxt(R/f"{r.split}/cell{r.idx}.csv",delimiter=","); dq=a[:,98]-a[:,8]
    extra.append(dict(barcode=r.barcode, log_skew_dq=np.log10(abs(stats.skew(dq))), log_kurt_dq=np.log10(abs(stats.kurtosis(dq,fisher=False)))))
d=d.merge(pd.DataFrame(extra),on="barcode")
F=["log_var_dq","log_abs_min_dq","log_skew_dq","log_kurt_dq","q2","qmax_minus_q2","q100","fade_slope_91_100"]
tr,t1,t2=(d[d.split==s] for s in ["train","test1","test2"])
res={}
reg=make_pipeline(StandardScaler(),ElasticNetCV(l1_ratio=[.1,.5,.9,1],cv=5,random_state=0,max_iter=100000)).fit(tr[F],np.log10(tr.cycle_life))
def metr(g):
    p=10**reg.predict(g[F]); e=p-g.cycle_life; return dict(RMSE=round(float(np.sqrt((e**2).mean())),1),MAPE=round(float((abs(e)/g.cycle_life).mean()*100),1))
res["regression"]={"test1":metr(t1),"test2_unseen_batch":metr(t2)}
# split conformal on log10 scale: calibrate on test1, evaluate on test2
cal=np.abs(np.log10(t1.cycle_life)-reg.predict(t1[F])); n=len(cal)
q=np.sort(cal)[int(np.ceil((n+1)*0.9))-1]
p2=reg.predict(t2[F]); lo,hi=10**(p2-q),10**(p2+q)
res["conformal_90"]=dict(calibration="test1 (n=43)",evaluated_on="test2 unseen batch (n=40)",coverage=round(float(((t2.cycle_life>=lo)&(t2.cycle_life<=hi)).mean()),3),
    median_interval_width_cycles=round(float(np.median(hi-lo)),0),log10_halfwidth=round(float(q),3))
# early-failure classifier
for g in (tr,t1,t2): pass
y=lambda g:(g.cycle_life<550).astype(int)
clf=make_pipeline(StandardScaler(),LogisticRegressionCV(Cs=10,cv=5,penalty="l2",max_iter=10000)).fit(tr[F],y(tr))
for name,g in [("test1",t1),("test2_unseen_batch",t2)]:
    pr=clf.predict_proba(g[F])[:,1]; ph=(pr>=0.5).astype(int)
    res.setdefault("early_failure_lt550",{})[name]=dict(n=len(g),actual_early=int(y(g).sum()),flagged=int(ph.sum()),
        accuracy=round(accuracy_score(y(g),ph),3),precision=round(precision_score(y(g),ph,zero_division=0),3),recall=round(recall_score(y(g),ph,zero_division=0),3),
        roc_auc=None if y(g).nunique()<2 else round(roc_auc_score(y(g),pr),3))
print(json.dumps(res,indent=1)); json.dump(res,open("outputs/cell_screening.json","w"),indent=1)
