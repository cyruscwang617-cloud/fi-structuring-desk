"""Fixed Income Structuring Desk -- run with:  streamlit run app.py"""
import hmac
from datetime import date

import numpy as np
import pandas as pd
import streamlit as st

from fisd.curve import GRID, bootstrap, interpolate_par
from fisd.data import load_move, load_sofr, load_treasury_curve
from fisd.products import (callable_vs_bullet, fixed_to_floating, floating_to_fixed,
                           range_accrual, steepener_coupon)
from fisd.store import load_calibration, save_calibration

st.set_page_config(page_title="FI Structuring Desk", layout="wide")

FALLBACK_VOL_BP = 95          # used only if the MOVE index cannot be downloaded


def pct(x, digits=3):
    return f"{x * 100:.{digits}f}%"


@st.cache_data(ttl=3600)          # re-download at most once an hour
def get_market_data():
    history, source = load_treasury_curve()
    sofr, sofr_date = load_sofr()
    return history, source, sofr, sofr_date, load_move()


history, source, sofr, sofr_date, move = get_market_data()
latest = history.iloc[-1].dropna()
curve_date = history.index[-1].date()
known_tenors = [t for t in latest.index if t <= 10]

# ------------------------------------------------------------------- sidebar
calibration = load_calibration()      # swap spreads saved in data/calibration.json
st.sidebar.header("Swap curve calibration")
st.sidebar.caption(
    "SOFR swap quotes are licensed data, so swap spreads are calibrated by hand. "
    f"Saved calibration: {calibration['as_of']}. Edit the rates to test your own."
)
swap_inputs, start_values = {}, {}
for tenor in (2, 5, 10):
    saved_spread = calibration["spreads_bp"][str(tenor)]
    start_values[tenor] = round((float(latest[float(tenor)]) + saved_spread / 10000) * 100, 3)
    swap_inputs[tenor] = st.sidebar.number_input(
        f"{tenor}Y SOFR swap rate (%)", value=start_values[tenor], step=0.01, format="%.3f")
spread_2y, spread_5y, spread_10y = [
    (swap_inputs[t] / 100 - float(latest[float(t)])) * 10000 for t in (2, 5, 10)]
st.sidebar.caption(
    f"Implied swap spreads: 2Y {spread_2y:+.1f} bp, 5Y {spread_5y:+.1f} bp, 10Y {spread_10y:+.1f} bp")
edited = any(abs(swap_inputs[t] - start_values[t]) > 1e-9 for t in (2, 5, 10))
spreads_as_of = "edited in this session" if edited else f"calibrated {calibration['as_of']}"

with st.sidebar.expander("Owner: save for all visitors"):
    password = st.text_input("Password", type="password")
    if st.button("Save calibration"):
        try:
            admin_password = st.secrets["ADMIN_PASSWORD"]
            token, repo = st.secrets["GITHUB_TOKEN"], st.secrets["GITHUB_REPO"]
        except Exception:
            st.error("Saving is not set up yet (secrets missing).")
        else:
            if not hmac.compare_digest(str(password), str(admin_password)):
                st.error("Wrong password.")
            else:
                new_calibration = {
                    "as_of": curve_date.strftime("%d %b %Y"),
                    "spreads_bp": {"2": round(spread_2y, 1), "5": round(spread_5y, 1), "10": round(spread_10y, 1)},
                }
                ok, message = save_calibration(token, repo, new_calibration)
                (st.success if ok else st.error)(message)

st.sidebar.header("Scenario")
shift_bp = st.sidebar.slider("Scenario: parallel shift (bp)", -200, 200, 0, step=25)

if move is not None:
    default_vol = int(min(180, max(40, round(move / 5) * 5)))     # snap to the slider grid
    vol_note = f"Default follows the MOVE index ({move:.1f}, Yahoo Finance, delayed) as a proxy."
else:
    default_vol = FALLBACK_VOL_BP
    vol_note = "MOVE index download failed; default is a manual assumption."
vol_bp = st.sidebar.slider("Normal vol (bp / year)", 40, 180, default_vol, step=5)
st.sidebar.caption(vol_note)

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
    c1, c2, c3, c4, c5 = st.columns(5)
    c5.metric("MOVE index (rates vol)", f"{move:.1f}" if move is not None else "n/a",
              help="ICE BofA MOVE: implied vol of Treasury options in bp per year")
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
| Swap curve | Treasury par + swap spread ({spreads_as_of}), shift {shift_bp} bp |
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
| MOVE index | Yahoo Finance (delayed) -- sets the default vol |
| Swap spreads | **Calibrated by hand** and saved in `data/calibration.json`; the date is shown in the sidebar. SOFR swap quotes are licensed data |
| Normal vol | One flat number, defaulting to MOVE. MOVE is a **proxy**: it measures short-dated Treasury options, not the swaption expiry/tenor each structure needs |
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
