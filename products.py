"""Client solutions built from the curve and the pricing blocks.

Issuer side  : liability swaps, bullet vs callable
Investor side: range accrual note, CMS steepener payoff
"""
from .pricing import bachelier, prob_in_range


# ---------------------------------------------------------------- issuer side
def floating_to_fixed(curve, maturity, loan_margin, basis_bp=0.0):
    """Borrower with a floating loan pays fixed on a swap.
    All-in fixed cost = swap rate + Term SOFR/OIS basis + loan margin."""
    swap_rate = curve.swap_rate(0, maturity)
    return {"swap_rate": swap_rate, "all_in_fixed": swap_rate + basis_bp / 10000 + loan_margin}


def fixed_to_floating(curve, maturity, coupon):
    """Fixed-rate issuer receives fixed on a swap: cost becomes SOFR + spread."""
    swap_rate = curve.swap_rate(0, maturity)
    return {"swap_rate": swap_rate, "spread_over_sofr": coupon - swap_rate}


def callable_vs_bullet(curve, maturity, call_year, credit_spread, vol_bp):
    """Callable bond = bullet bond - receiver swaption (owned by the issuer).

    The issuer's right to call at par on `call_year` is a receiver swaption on
    the remaining life, struck at (coupon - credit spread). Investors are short
    it and get paid through a higher coupon. We solve for the coupon where
        PV of extra coupon  =  value of the option.
    Single (European) call date only.
    """
    bullet = curve.swap_rate(0, maturity) + credit_spread
    full_annuity = curve.annuity_at(maturity)
    fwd_annuity = curve.forward_annuity(call_year, maturity)
    fwd_rate = curve.swap_rate(call_year, maturity)

    def option_value(coupon):
        return bachelier(fwd_rate, coupon - credit_spread, vol_bp, call_year, fwd_annuity, "receiver")

    # bisection: the gap below rises steadily with the coupon, so halve the bracket
    low, high = bullet, bullet + 0.10
    for _ in range(60):
        mid = (low + high) / 2
        gap = (mid - bullet) * full_annuity - option_value(mid)
        if gap > 0:
            high = mid
        else:
            low = mid
    coupon = (low + high) / 2
    return {
        "bullet_coupon": bullet,
        "callable_coupon": coupon,
        "pickup_bp": (coupon - bullet) * 10000,
        "option_value": option_value(coupon),       # fraction of notional
        "forward_rate": fwd_rate,                   # forward swap rate at the call date
        "breakeven_refi": coupon - credit_spread,   # issuer calls if the swap rate is below this
    }


# -------------------------------------------------------------- investor side
def range_accrual(curve, maturity, lower, upper, vol_bp, funding_spread, fee):
    """Fair coupon of a note that pays only when the 1-year rate is in range.

    Simplification: one observation per year at mid-year (real notes observe
    daily, i.e. a strip of daily digital options).
    Budget = PV of floating leg + PV of issuer funding spread - structuring fee.
    """
    rows, sum_df, sum_df_prob = [], 0.0, 0.0
    for year in range(1, maturity + 1):
        forward = float(curve.fwd[year - 1])
        prob = prob_in_range(forward, lower, upper, vol_bp, year - 0.5)
        df = curve.df_at(year)
        sum_df += df
        sum_df_prob += df * prob
        rows.append({"Year": year, "Forward rate": forward, "Prob. in range": prob, "Discount factor": df})
    budget = 1 - curve.df_at(maturity) + funding_spread * sum_df - fee
    return {
        "coupon": budget / sum_df_prob,
        "plain_coupon": budget / sum_df,
        "avg_prob": sum(r["Prob. in range"] for r in rows) / maturity,
        "rows": rows,
    }


def steepener_coupon(slope, leverage, cap, floor):
    """CMS steepener payoff: leverage x (10y - 2y), floored and capped.
    Payoff only -- fair pricing needs a CMS convexity adjustment (not modelled)."""
    return min(cap, max(floor, leverage * slope))
