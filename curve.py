"""Curve construction: par swap rates -> discount factors, zeros, forwards.

Conventions (deliberately simple, same as my Excel workbook):
  * annual fixed payments, accrual factor = 1 for every year
  * one curve for both discounting and projecting (SOFR OIS logic)
  * integer tenors 1..10 years, par rates linearly interpolated in between
"""
from dataclasses import dataclass

import numpy as np

GRID = np.arange(1, 11)          # 1, 2, ..., 10 years


def interpolate_par(known_tenors, known_rates, grid=GRID):
    """Linear interpolation of par rates onto every whole year."""
    return np.interp(grid, known_tenors, known_rates)


@dataclass
class Curve:
    par: np.ndarray        # par swap rate for each year 1..N
    df: np.ndarray         # discount factor to each year
    zero: np.ndarray       # annually compounded zero rate
    fwd: np.ndarray        # 1-year forward rate for the year ENDING at each tenor
    annuity: np.ndarray    # sum of discount factors up to each year

    # helpers take a whole number of years; year 0 means "today"
    def df_at(self, year):
        return 1.0 if year == 0 else float(self.df[year - 1])

    def annuity_at(self, year):
        return 0.0 if year == 0 else float(self.annuity[year - 1])

    def forward_annuity(self, start, end):
        return self.annuity_at(end) - self.annuity_at(start)

    def swap_rate(self, start, end):
        """Par rate of a swap running from `start` to `end` (start=0 is spot).
        Floating leg PV = DF(start) - DF(end); fixed leg PV = rate x annuity."""
        return (self.df_at(start) - self.df_at(end)) / self.forward_annuity(start, end)


def bootstrap(par):
    """Solve discount factors one year at a time.

    A par swap is worth zero, so for maturity n:
        par_n * (DF_1 + ... + DF_n) + DF_n = 1
    Everything except DF_n is already known, so
        DF_n = (1 - par_n * sum(DF_1..DF_{n-1})) / (1 + par_n)
    """
    par = np.asarray(par, dtype=float)
    df = np.zeros(len(par))
    for i in range(len(par)):
        df[i] = (1 - par[i] * df[:i].sum()) / (1 + par[i])
    years = np.arange(1, len(par) + 1)
    zero = df ** (-1 / years) - 1
    previous_df = np.concatenate(([1.0], df[:-1]))
    fwd = previous_df / df - 1
    return Curve(par=par, df=df, zero=zero, fwd=fwd, annuity=np.cumsum(df))
