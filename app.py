"""Fixed Income Structuring Desk -- run with:  streamlit run app.py"""
from datetime import date

import numpy as np
import pandas as pd
import streamlit as st

from fisd.curve import GRID, bootstrap, interpolate_par
from fisd.data import load_sofr, load_treasury_curve
from fisd.products import (callable_vs_bullet, fixed_to_floating, floating_to_fixed,
                           range_accrual, steepener_coupon)

st.set_page_config(page_title="FI Structuring Desk", layout="wide")


def pct(x, digits=3):
    return f"{x * 100:.{digits}f}%"


@st.cache_data(ttl=3600)          # re-download at most once an hour
def get_market_data():
    history, source = load_treasury_curve()
    sofr, sofr_date = load_sofr()
    return history, source, sofr, sofr_date


history, source, sofr, sofr_date = get_market_data()
latest = history.iloc[-1].dropna()
curve_date = history.index[-1].date()
known_tenors = [t for t in latest.index if t <= 10]

# ------------------------------------------------------------------- sidebar
st.sidebar.header("Market assumptions")
st.sidebar.caption(
    "Live SOFR swap quotes are not freely available, so the swap curve is "
    "Treasury par yield + a swap spread you set here."
)
spread_2y = st.sidebar.number_input("2Y swap spread (bp)", value=-20.0, step=1.0)
spread_5y = st.sidebar.number_input("5Y swap spread (bp)", value=-30.0, step=1.0)
spread_10y = st.sidebar.number_input("10Y swap spread (bp)", value=-45.0, step=1.0)
shift_bp = st.sidebar.slider("Scenario: parallel shift (bp)", -200, 200, 0, step=25)
vol_bp = st.sidebar.slider("Normal vol (bp / year)", 40, 180, 95, step=5)

treasury_par = interpolate_par(known_tenors, latest[known_tenors].values)
swap_spread = np.interp(GRID, [2, 5, 10], [spread_2y, spread_5y, spread_10y]) / 10000
swap_par = treasury_par + swap_spread + shift_bp / 10000
curve = bootstrap(swap_par)

# -------------------------------------------------------------------- header
st.title("Fixed Income Structuring Desk")
st.caption("From a live curve to client solutions: issuer liability management and investor structured notes.")
if source.startswith("LIVE"):
    st.success(f"{source} -- curve date {curve_date}")
else:
    st.warning(source)

tab_market, tab_issuer, tab_investor, tab_method = st.tabs(
    ["1 Market", "2 Issuer solutions", "3 Investor notes", "4 Methodology & limits"]
)

# -------------------------------------------------------------------- market
with tab_market:
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("SOFR (overnight)", pct(sofr, 2) if sofr is not None else "n/a",
              help=f"NY Fed, effective {sofr_date}" if sofr_date else "NY Fed download failed")
    c2.metric("2Y Treasury", pct(latest[2.0], 2))
    c3.metric("10Y Treasury", pct(latest[10.0], 2))
    c4.metric("2s10s slope", f"{(latest[10.0] - latest[2.0]) * 10000:.0f} bp")

    left, right = st.columns(2)
    with left:
        st.subheader("Today's curves")
        chart = pd.DataFrame(
            {"Treasury par": treasury_par * 100, "SOFR swap par (proxy)": swap_par * 100,
             "Zero": curve.zero * 100, "1Y forward": curve.fwd * 100},
            index=pd.Index(GRID, name="Years"),
        )
        st.line_chart(chart)
    with right:
        st.subheader("2s10s Treasury slope, year to date (bp)")
        st.line_chart(((history[10.0] - history[2.0]) * 10000).rename("2s10s"))

    st.subheader("Bootstrapped curve")
    table = pd.DataFrame(
        {"Par swap": curve.par, "Discount factor": curve.df, "Zero": curve.zero,
         "1Y forward": curve.fwd, "Annuity": curve.annuity},
        index=pd.Index(GRID, name="Years"),
    )
    st.dataframe(table.style.format(
        {"Par swap": "{:.3%}", "Zero": "{:.3%}", "1Y forward": "{:.3%}",
         "Discount factor": "{:.5f}", "Annuity": "{:.4f}"}))

# -------------------------------------------------------------------- issuer
with tab_issuer:
    st.subheader("A. Bullet vs callable: what does the call option cost the issuer?")
    a1, a2, a3, a4 = st.columns(4)
    size_mm = a1.number_input("Issue size ($mm)", value=500, step=50)
    maturity = a2.selectbox("Maturity (years)", [3, 5, 7, 10], index=1)
    call_year = a3.selectbox("First call (years)", list(range(1, maturity)), index=min(1, maturity - 2))
    credit_bp = a4.number_input("Credit spread over swaps (bp)", value=100, step=5)

    res = callable_vs_bullet(curve, maturity, call_year, credit_bp / 10000, vol_bp)
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Bullet coupon", pct(res["bullet_coupon"]))
    m2.metric(f"{maturity}NC{call_year} coupon", pct(res["callable_coupon"]), f"+{res['pickup_bp']:.1f} bp")
    m3.metric("Option value", f"${res['option_value'] * size_mm:.2f}mm")
    m4.metric("Called if swap rate below", pct(res["breakeven_refi"]),
              help=f"Forward {maturity - call_year}Y swap rate at the call date: {pct(res['forward_rate'])}")
    st.caption(
        "Callable = bullet minus a receiver swaption the issuer owns. Investors are short "
        "the option and are paid for it through the coupon pickup."
    )

    vols = list(range(40, 185, 10))
    pickup = [callable_vs_bullet(curve, maturity, call_year, credit_bp / 10000, v)["pickup_bp"] for v in vols]
    st.line_chart(pd.DataFrame({"Coupon pickup (bp)": pickup}, index=pd.Index(vols, name="Normal vol (bp)")))

    st.subheader("B. Liability swaps")
    b1, b2 = st.columns(2)
    with b1:
        st.markdown("**Fixed bond swapped to floating**")
        f2f = fixed_to_floating(curve, maturity, res["bullet_coupon"])
        st.metric("Issuer pays", f"SOFR + {f2f['spread_over_sofr'] * 10000:.0f} bp")
        st.caption(f"Receive fixed {pct(f2f['swap_rate'])} on a {maturity}Y swap against the bullet coupon.")
    with b2:
        st.markdown("**Floating loan swapped to fixed**")
        margin_bp = st.number_input("Loan margin over Term SOFR (bp)", value=175, step=25)
        basis_bp = st.number_input("Term SOFR vs OIS basis (bp, assumed)", value=1.5, step=0.5)
        f2x = floating_to_fixed(curve, maturity, margin_bp / 10000, basis_bp)
        st.metric("All-in fixed cost", pct(f2x["all_in_fixed"]))
        st.caption(f"Pay fixed {pct(f2x['swap_rate'])} + basis + margin; Term SOFR legs cancel.")

    term_sheet = f"""# Indicative terms -- {maturity}NC{call_year} callable note
*Educational illustration only. Not an offer; not based on executable prices.*

| Term | Value |
|---|---|
| Pricing date | {date.today()} (curve date {curve_date}) |
| Size | ${size_mm}mm |
| Maturity | {maturity} years |
| Call | Issuer call at par, once, at year {call_year} |
| Coupon | {pct(res['callable_coupon'])} annual |
| Bullet alternative | {pct(res['bullet_coupon'])} |
| Coupon pickup | {res['pickup_bp']:.1f} bp |
| Embedded option value | ${res['option_value'] * size_mm:.2f}mm |
| Swap curve | Treasury par + swap spread, shift {shift_bp} bp |
| Normal vol | {vol_bp} bp |
| Data | {source} |
"""
    st.download_button("Download indicative term sheet (.md)", term_sheet, file_name="indicative_terms.md")

# ------------------------------------------------------------------ investor
with tab_investor:
    st.subheader("A. Range accrual note: where does the extra coupon come from?")
    r1, r2, r3, r4, r5 = st.columns(5)
    ra_maturity = r1.selectbox("Maturity (years)", [2, 3, 5, 7], index=2, key="ra_mat")
    lower = r2.number_input("Range low (%)", value=round(float(curve.fwd[:5].mean()) * 100 - 1.0, 1), step=0.25)
    upper = r3.number_input("Range high (%)", value=round(float(curve.fwd[:5].mean()) * 100 + 1.0, 1), step=0.25)
    funding_bp = r4.number_input("Issuer funding spread (bp)", value=50, step=5)
    fee_bp = r5.number_input("Structuring fee (bp upfront)", value=50, step=5)

    if upper <= lower:
        st.error("Range high must be above range low.")
    else:
        ra = range_accrual(curve, ra_maturity, lower / 100, upper / 100, vol_bp, funding_bp / 10000, fee_bp / 10000)
        n1, n2, n3 = st.columns(3)
        n1.metric("Range accrual coupon", pct(ra["coupon"]), f"+{(ra['coupon'] - ra['plain_coupon']) * 10000:.0f} bp vs plain")
        n2.metric("Plain fixed coupon, same terms", pct(ra["plain_coupon"]))
        n3.metric("Average prob. in range", f"{ra['avg_prob']:.0%}",
                  help="Expected coupon is roughly coupon x this probability")
        st.dataframe(pd.DataFrame(ra["rows"]).set_index("Year").style.format(
            {"Forward rate": "{:.3%}", "Prob. in range": "{:.1%}", "Discount factor": "{:.5f}"})
        )
        st.caption(
            "The investor sells a strip of digital options (short vol). Raise vol in the sidebar: "
            "the probability falls and the headline coupon rises."
        )

    st.subheader("B. CMS steepener: payoff profile")
    s1, s2, s3 = st.columns(3)
    leverage = s1.number_input("Leverage (x)", value=5.0, step=1.0)
    cap = s2.number_input("Coupon cap (%)", value=10.0, step=1.0)
    floor = s3.number_input("Coupon floor (%)", value=0.0, step=0.5)
    slope_now = curve.par[9] - curve.par[1]
    slopes = list(range(-100, 301, 25))
    payoff = [steepener_coupon(s / 10000, leverage, cap / 100, floor / 100) * 100 for s in slopes]
    st.metric("Coupon at today's 2s10s swap slope",
              pct(steepener_coupon(slope_now, leverage, cap / 100, floor / 100), 2),
              f"slope {slope_now * 10000:.0f} bp", delta_color="off")
    st.line_chart(pd.DataFrame({"Coupon (%)": payoff}, index=pd.Index(slopes, name="10Y - 2Y slope (bp)")))
    st.caption("Payoff only. A fair price needs a CMS convexity adjustment and a correlation view, which this tool does not model.")

# --------------------------------------------------------------- methodology
with tab_method:
    st.markdown("""
### What is live and what is assumed
| Input | Source |
|---|---|
| Treasury par yields, 1Y-10Y | US Treasury daily par yield curve (live) |
| Overnight SOFR | Federal Reserve Bank of New York (live) |
| Swap spreads | **My assumption** (sidebar) -- no free live SOFR swap feed |
| Normal vol | **My assumption** (sidebar) -- one flat number, no vol surface |
| Credit / funding spreads, fees | User inputs |

### Method
1. **Curve.** Par swap rate = Treasury par yield + swap spread, interpolated linearly to each whole year, then bootstrapped: `DF_n = (1 - par_n x sum DF) / (1 + par_n)`.
2. **Swaptions.** Bachelier (normal) model, because USD rate vol is quoted in bp.
3. **Callable.** Callable = bullet - receiver swaption struck at coupon minus credit spread. The coupon is solved so the PV of the extra coupon equals the option value.
4. **Range accrual.** Coupon budget = PV of floating leg + funding spread - fee, divided by the probability-weighted annuity.

### Known simplifications (what a real desk does differently)
- Annual periods with accrual factor 1; real SOFR OIS uses Act/360 and payment lags.
- Treasury yields are semi-annual bond-equivalent; I treat the proxy swap rate as annual.
- One European call date; real callables are often Bermudan and need a tree or Monte Carlo.
- Flat vol, no skew; digitals in the range accrual are sensitive to skew.
- Range observed once a year instead of daily.
- No CMS convexity adjustment, so the steepener shows payoff only.
- Credit spread is a constant add-on; no default modelling, no CVA/funding adjustments.
""")
