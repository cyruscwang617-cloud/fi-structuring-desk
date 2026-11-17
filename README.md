# Fixed Income Structuring Desk

A small web app that goes from **a live US rates curve to client solutions**, the way a
debt / fixed income structuring desk frames a conversation:

- **Issuer side** – bullet vs callable (e.g. 5NC2): what coupon pickup pays for the call option? What does the bond cost swapped to floating, or a floating loan swapped to fixed?
- **Investor side** – range accrual note: where does the enhanced coupon come from? CMS steepener payoff profile against today's 2s10s slope.

**Live app:** _add your Streamlit link here_

## Why I built it

I studied Siddhartha Jha's *Interest Rate Markets* (Wiley, 2011) and worked every chapter
through an Excel workbook, updating the LIBOR-era material to SOFR. This project turns that
workbook into code and connects it to live data, so the same client scenarios can be
re-priced on today's curve and stress-tested in a few clicks.

## What it does

| Tab | Content |
|---|---|
| 1 Market | Live Treasury par curve, overnight SOFR and MOVE index; bootstrapped discount factors, zeros and forwards; 2s10s slope history |
| 2 Issuer solutions | Callable = bullet − receiver swaption, solved for the fair callable coupon; pickup vs vol; liability swaps; downloadable indicative term sheet |
| 3 Investor notes | Range accrual fair coupon from in-range probabilities; CMS steepener payoff |
| 4 Methodology & limits | Every assumption and simplification, stated explicitly |

The sidebar applies a parallel curve shift and a vol level to every product at once.

## Data

| Input | Source |
|---|---|
| Treasury par yields | [US Treasury daily par yield curve](https://home.treasury.gov/resource-center/data-chart-center/interest-rates) – live |
| Overnight SOFR | [Federal Reserve Bank of New York](https://www.newyorkfed.org/markets/reference-rates/sofr) – live |
| Rates vol | ICE BofA MOVE index via Yahoo Finance (delayed) – live. Used as a **proxy** for swaption normal vol: it measures short-dated Treasury options, not the exact expiry/tenor of each structure. |
| Swap spreads | **Calibrated by hand.** SOFR swap quotes are licensed data, so the swap curve is Treasury par yield + a swap spread I calibrate by hand. The calibration is stored in `data/calibration.json`; its commit history is a log of every update. |

If a download fails the app falls back to an illustrative sample file and shows a warning.

## Run it

```bash
pip install -r requirements.txt
streamlit run app.py
pytest            # 9 sanity checks: par swaps reprice to zero, put/call parity, ...
```

## Code map

```
app.py              Streamlit front end
fisd/data.py        Treasury + NY Fed downloads
fisd/curve.py       par rates -> discount factors, zeros, forwards, forward swap rates
fisd/pricing.py     bond maths, Bachelier (normal) swaption model
fisd/products.py    callable, liability swaps, range accrual, steepener
fisd/store.py       saved swap spread calibration
tests/test_core.py  sanity checks
```

## Simplifications I am aware of

- Annual periods, accrual factor 1 (real SOFR OIS: Act/360, payment lag).
- Treasury yields are semi-annual bond-equivalent; the proxy swap rate is treated as annual.
- A single European call date. Bermudan callables need a tree or Monte Carlo.
- One flat normal vol: no surface, no skew (digitals in a range accrual are skew-sensitive).
- Range observed once per year rather than daily.
- No CMS convexity adjustment – the steepener tab shows payoff, not price.
- Credit spread is a constant add-on; no default risk, CVA or funding adjustments.

## Next steps

- Bermudan callable on a short-rate tree (Hull-White)
- Proper day counts and a dated schedule
- CMS convexity adjustment for the steepener
- Curve DV01 / bucketed risk for each structure

## Notes

Educational project; nothing here is an offer or investment advice. Developed with AI
coding assistance; the modelling choices, checks and documentation are my own responsibility.

Reference: Jha, S. (2011). *Interest Rate Markets: A Practical Approach to Fixed Income*. Wiley.
