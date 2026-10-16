"""Shared forecasting functions for the Norway liquids forecast notebooks."""

import numpy as np
import pandas as pd
from scipy.optimize import curve_fit

MODELLED_INDIVIDUALLY = ["JOHAN SVERDRUP", "JOHAN CASTBERG"]


def months_between(start, dates):
    """Whole months from `start` to each date in `dates` (0 for the start month itself)."""
    start = pd.Timestamp(start)
    return (dates.year - start.year) * 12 + (dates.month - start.month)


def arps_rate(t_months, qi, di, b):
    """Arps hyperbolic decline: rate after t months.
    qi = rate at t = 0 (kb/d), di = initial nominal decline (per month), b = hyperbolic exponent."""
    return qi / (1 + b * di * t_months) ** (1 / b)


def fit_arps(rates, decline_start, b=None):
    """Fit Arps to monthly rates (index = month) from decline_start on. Returns a dict of results.
    If b is given it is held fixed and only qi and di are fitted; otherwise b is fitted too."""
    t = months_between(decline_start, rates.index).to_numpy()
    q = rates.to_numpy()
    if b is None:
        (qi, di, b), _ = curve_fit(
            arps_rate, t, q,
            p0=[q[0], 0.01, 0.5],                     # starting guess for the solver
            bounds=([0, 0, 0.01], [np.inf, 1, 1]),    # b between 0.01 (~exponential) and 1 (harmonic)
        )
    else:
        (qi, di), _ = curve_fit(
            lambda t, qi, di: arps_rate(t, qi, di, b), t, q,
            p0=[q[0], 0.01],
            bounds=([0, 0], [np.inf, 1]),
        )
    fitted = arps_rate(t, qi, di, b)
    r_squared = 1 - ((q - fitted) ** 2).sum() / ((q - q.mean()) ** 2).sum()
    return {
        "decline_start": decline_start,
        "qi": qi,
        "di": di,
        "b": b,
        "r_squared": r_squared,
        "n_months": len(q),
        "annual_decline_pct": (1 - arps_rate(12, qi, di, b) / qi) * 100,
    }


def arps_forecast(fit, months):
    """Rates from a fit_arps result for the given months (DatetimeIndex)."""
    t = months_between(fit["decline_start"], months).to_numpy()
    return pd.Series(arps_rate(t, fit["qi"], fit["di"], fit["b"]), index=months)


def plateau_then_decline(months, rate, plateau_end, annual_decline_pct):
    """Flat rate until plateau_end, then exponential decline at annual_decline_pct (effective, %/yr)."""
    t = np.clip(months_between(plateau_end, months).to_numpy(), 0, None)   # 0 for every plateau month
    di = -np.log(1 - annual_decline_pct / 100) / 12                        # effective %/yr -> nominal per month
    return pd.Series(rate * np.exp(-di * t), index=months)


def mature_fields_as_of(liquids_by_field, cutoff):
    """Fields that would have been in the 'mature' forecast group, using only data up to `cutoff`.
    Same rules as steps 4 and 5: below 85% of the peak 12-month average, still producing,
    not rising again (redeveloped), and not one of the fields modelled individually."""
    rolling_12m = liquids_by_field[:cutoff].rolling(12).mean()
    current = rolling_12m.iloc[-1]
    previous = rolling_12m.iloc[-13]
    growth_kbd = current - previous
    growth_pct = growth_kbd / previous * 100

    is_declining = (current > 0) & (current / rolling_12m.max() * 100 < 85)
    is_redeveloped = is_declining & (growth_pct >= 20) & (growth_kbd >= 5)
    is_mature = is_declining & ~is_redeveloped & ~current.index.isin(MODELLED_INDIVIDUALLY)
    return current.index[is_mature]
