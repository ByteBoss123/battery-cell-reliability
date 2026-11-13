"""Weibull life-data analysis: exact MLE with right censoring and weights, B-lives, bootstrap CIs.

The shape parameter k is the root of the profile-likelihood score equation
    sum_i w_i t_i^k ln t_i / sum_i w_i t_i^k - 1/k - (1/r) sum_{failures} ln t_j = 0,
where the sums over i run over failures and censored units (weight = unit count) and r is the
number of failures; the scale then has the closed form  eta^k = sum_i w_i t_i^k / r.
This is exact (no optimizer tolerance) and handles 57,000 censored units as 3 weighted rows.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import optimize, stats


@dataclass(frozen=True)
class WeibullFit:
    shape: float
    scale: float
    n_failures: int
    n_censored: float

    def cdf(self, t):
        return stats.weibull_min.cdf(t, self.shape, scale=self.scale)

    def b_life(self, p: float = 0.10) -> float:
        """Time by which a fraction p of the population has failed (B10 for p=0.10)."""
        return float(self.scale * (-np.log(1 - p)) ** (1 / self.shape))


def fit_weibull(failures, censored_times=(), censored_weights=()) -> WeibullFit:
    t_f = np.asarray(failures, float)
    t_c = np.asarray(censored_times, float)
    w_c = np.asarray(censored_weights, float) if len(censored_weights) else np.ones_like(t_c)
    if (t_f <= 0).any() or (t_c <= 0).any():
        raise ValueError("times must be positive")
    t = np.concatenate([t_f, t_c])
    w = np.concatenate([np.ones_like(t_f), w_c])
    r, mean_log_f = len(t_f), np.log(t_f).mean()
    lt = np.log(t)
    shift = lt.max()                                   # numerical stability for large k

    def score(k):
        a = w * np.exp(k * (lt - shift))
        return (a * lt).sum() / a.sum() - 1 / k - mean_log_f

    k = optimize.brentq(score, 1e-3, 100.0, xtol=1e-12)
    eta = float(np.exp(shift) * ((w * np.exp(k * (lt - shift))).sum() / r) ** (1 / k))
    return WeibullFit(float(k), eta, r, float(w_c.sum()))


def loglik(log_params, failures, censored_times=(), censored_weights=()) -> float:
    k, eta = np.exp(log_params)
    ll = stats.weibull_min.logpdf(np.asarray(failures, float), k, scale=eta).sum()
    if len(censored_times):
        ll += (np.asarray(censored_weights, float) * stats.weibull_min.logsf(np.asarray(censored_times, float), k, scale=eta)).sum()
    return float(ll)


def log_param_cov(fit: WeibullFit, failures, censored_times=(), censored_weights=(), eps: float = 1e-4) -> np.ndarray:
    """Inverse observed information for (log k, log eta), by central finite differences."""
    x0 = np.log([fit.shape, fit.scale])
    def f(x):
        return -loglik(x, failures, censored_times, censored_weights)
    H = np.zeros((2, 2))
    for i in range(2):
        for j in range(2):
            ei, ej = np.eye(2)[i] * eps, np.eye(2)[j] * eps
            H[i, j] = (f(x0 + ei + ej) - f(x0 + ei - ej) - f(x0 - ei + ej) + f(x0 - ei - ej)) / (4 * eps ** 2)
    return np.linalg.inv(H)


def bootstrap_b_life(x, p: float, draws: int, rng: np.random.Generator) -> tuple[float, float]:
    bs = [fit_weibull(rng.choice(x, len(x))).b_life(p) for _ in range(draws)]
    return float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))


def ks_pvalue(x, fit: WeibullFit) -> float:
    return float(stats.kstest(x, "weibull_min", args=(fit.shape, 0, fit.scale)).pvalue)
