"""Pricing building blocks: bond maths and the Bachelier (normal) option model."""
import math


def norm_cdf(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def norm_pdf(x):
    return math.exp(-0.5 * x * x) / math.sqrt(2 * math.pi)


def bachelier(forward, strike, vol_bp, expiry, annuity, kind):
    """Swaption value as a fraction of notional under the normal model.

    vol_bp : normal vol in basis points per year (rates options are quoted this way)
    annuity: PV of 1 per year over the underlying swap's life
    kind   : "payer" (right to pay fixed) or "receiver" (right to receive fixed)
    """
    stdev = vol_bp / 10000 * math.sqrt(expiry)
    if stdev == 0:
        intrinsic = forward - strike if kind == "payer" else strike - forward
        return annuity * max(intrinsic, 0.0)
    d = (forward - strike) / stdev
    if kind == "payer":
        return annuity * ((forward - strike) * norm_cdf(d) + stdev * norm_pdf(d))
    return annuity * ((strike - forward) * norm_cdf(-d) + stdev * norm_pdf(d))


def prob_in_range(forward, lower, upper, vol_bp, time):
    """Probability that a normally distributed rate ends inside [lower, upper]."""
    stdev = vol_bp / 10000 * math.sqrt(time)
    return norm_cdf((upper - forward) / stdev) - norm_cdf((lower - forward) / stdev)


def bond_price(coupon, ytm, years, freq=2):
    """Clean price per 100 face on a coupon date."""
    n = int(round(years * freq))
    c, y = coupon / freq * 100, ytm / freq
    return sum(c / (1 + y) ** k for k in range(1, n + 1)) + 100 / (1 + y) ** n


def bond_dv01(coupon, ytm, years, freq=2):
    """Price change per 100 face for a 1bp move in yield (central difference)."""
    up = bond_price(coupon, ytm + 0.0001, years, freq)
    down = bond_price(coupon, ytm - 0.0001, years, freq)
    return (down - up) / 2
