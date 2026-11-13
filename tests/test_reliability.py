"""The estimators must recover known parameters from simulated data before they are trusted on real data."""
import numpy as np
import pytest
from scipy import stats

from cellrel.reliability import fit_weibull, log_param_cov


@pytest.mark.parametrize("k,eta", [(0.8, 100.0), (2.0, 900.0), (6.5, 500.0)])
def test_uncensored_mle_recovers_parameters(k, eta):
    x = stats.weibull_min.rvs(k, scale=eta, size=20000, random_state=1)
    f = fit_weibull(x)
    assert f.shape == pytest.approx(k, rel=0.03) and f.scale == pytest.approx(eta, rel=0.02)


def test_matches_scipy_on_same_sample():
    x = stats.weibull_min.rvs(2.2, scale=900, size=124, random_state=7)
    k, _, eta = stats.weibull_min.fit(x, floc=0)
    f = fit_weibull(x)
    assert f.shape == pytest.approx(k, rel=1e-5) and f.scale == pytest.approx(eta, rel=1e-5)


def test_censored_weighted_mle_recovers_rare_failure_regime():
    """Mirrors the population model: tens of failures among tens of thousands of censored units."""
    rng = np.random.default_rng(3)
    k, eta, n, tau = 1.3, 15000.0, 60000, 46.0
    t = stats.weibull_min.rvs(k, scale=eta, size=n, random_state=rng)
    fails = t[t <= tau]
    fit = fit_weibull(fails, [tau], [n - len(fails)])         # all survivors collapsed into one weighted row
    se = np.sqrt(np.diag(log_param_cov(fit, fails, [tau], [n - len(fails)])))
    assert abs(np.log(fit.shape) - np.log(k)) < 3 * se[0]
    assert fit.cdf(96) == pytest.approx(stats.weibull_min.cdf(96, k, scale=eta), rel=0.5)


def test_b_life_definition():
    f = fit_weibull(stats.weibull_min.rvs(3, scale=1000, size=5000, random_state=0))
    assert f.cdf(f.b_life(0.10)) == pytest.approx(0.10, abs=1e-9)


def test_rejects_nonpositive_times():
    with pytest.raises(ValueError):
        fit_weibull([1.0, 0.0, 2.0])
