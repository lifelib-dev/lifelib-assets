# The BondPortfolio model

`bond_portfolio/BondPortfolio` is a [modelx](https://modelx.io) model of a
portfolio of fixed-rate and zero-coupon bonds. It

1. **generates the cash flows** of every bond (schedule, coupons, redemption),
2. **values the bonds** on a discount curve plus an optional zero spread:
   NPV, settlement value, dirty and clean price, accrued interest, market
   value, and prices from a given z-spread,
3. does (2) **at future valuation dates under scenarios**: one valuation per
   `(scen_id, t)`, with the curve, spreads and conventions of each
   `(scen_id, t)` as inputs,
4. at every `(scen_id, t)`, **solves yields and z-spreads** and computes the
   **risk measures** (simple, modified and Macaulay duration, convexity, BPV,
   YVBP) and prices from a yield.

The formulas are transcribed statement for statement from `pureql`, a
pure-Python port of QuantLib v1.43, and reproduce its results bit for bit. The
model does not import QuantLib or pureql. What a valuation at a future date
means, flow by flow, is in [technical-notes.md](technical-notes.md); the input
files are specified in [inputs.md](inputs.md).

v1 covers FixedRateBond and ZeroCouponBond; the Backward schedule rule (and
the Zero rule a `0D` tenor gives); the NullCalendar, TARGET and
UnitedStates (Settlement, GovernmentBond) calendars; the Actual360,
Actual365Fixed and Thirty360 (USA, BondBasis/ISMA, European/EurobondBasis)
day counters; ZeroCurve, FlatForward and ZeroSpreadedTermStructure curves.

## Spaces

| Space | What it holds |
|---|---|
| `Data` | Reads the input CSV files of `Data.input_dir` and parses them into numpy arrays; the run settings (References); `check_inputs()`. |
| `Lib` | Numerics shared by all Spaces: IEEE helpers, `close`, InterestRate (`compound_factor`, `discount_factor`, `implied_rate`, `equivalent_rate`), `has_occurred`, `coupon_accrued_amount`, `stepwise_time` (the stepwise discounting time of the yield functions), `sign`. |
| `Dates` | Date algebra on integer serial numbers, the four calendars, business-day adjustment, day counters. |
| `Bond[b]` | One item per row `b` of `bonds.csv`: `schedule()`, `coupons()`, `leg()`, `notional_schedule()`, `cashflow_table()`. |
| `Legs` | The legs of all bonds as flat (CSR) arrays (`leg_columns()`), the cash-flow table `cashflow_frame()`, and `check_limits()`. |
| `Proj` | The flows bucketed into the projection periods between valuation dates: `bucket_arr()`, `coupon_cf(per)`, `total_cf(per)`, `bond_cf_table()`, `period_table()`. |
| `Valuation[scen_id, t]` | One item per scenario and valuation date: the curve of `(scen_id, t)` and every bond valued at `val_date[t]`: `npv(b)`, `settlement_value(b)`, `dirty_price(b)`, `clean_price(b)`, `accrued_amount(b)`, `market_value(b)`, `dirty_from_z(b, z)`; the analytics `ytm(b)`, `zspread(b)`, `risk_yield(b)`, `duration_simple(b)`, `duration_modified(b)`, `duration_macaulay(b)`, `convexity(b)`, `bpv(b)`, `yvbp(b)`, `dirty_from_yield(b, y)`, `clean_from_yield(b, y)`; the totals `npv_total()`, `mv_total()`, `sv_total()`, `accrued_total()`, `n_tradable()`, `n_expired()`, and `result_frame()`. |

Bond quantities in `Valuation` are Cells over the bond index `b` (the row of
`bonds.csv`, from 0); `scen_id` runs 1..S and `t` 0..T-1. The binding
interface of every Cells is [docs/model-contract.md](../docs/model-contract.md).

## Inputs

CSV files in one directory ([inputs.md](inputs.md) has every column and
default):

| File | Content |
|---|---|
| `bonds.csv` | one row per bond: type, face, settlement days, calendar, issue date, schedule, coupon, yield-quote conventions, `spread_id` |
| `coupon_rates.csv` (optional) | step-up coupon vectors |
| `valuation_dates.csv` | the valuation date of each `t`, strictly increasing, shared by all scenarios |
| `curve_params.csv` | per `(scen_id, t)`: curve type, day counter, compounding, frequency, extrapolation, flat rate, spread conventions |
| `curve_nodes.csv` | ZeroCurve nodes per `(scen_id, t)`, by date or by tenor from `val_date[t]` |
| `spreads.csv` | the zero spread of each `spread_id` at each `(scen_id, t)` |
| `prices.csv`, `yields.csv` (optional) | sparse quotes per `(scen_id, t, bond_key)`: a price solves the yield (instead of the engine's clean price) and the z-spread; a yield is where the risk measures are taken (instead of the solved yield) |

This directory holds a small demo set (13 bonds, 2 scenarios x 4 dates,
including the headline bond of quantlib-migration's documentation and
QuantLib's cached zero-coupon cases).
`generate_inputs.py` writes seeded random portfolios of any size, and the
coverage set of `tools/cy/sample_inputs`:

```
python bond_portfolio/generate_inputs.py --n-bonds 10000 --n-scen 2 --n-times 121 --seed 1 --out <dir>
```

### Settings

`Data` References, set before calculating (in modelx mode changing one clears
the values that depend on it):

| Reference | Default | Meaning |
|---|---|---|
| `input_dir` | `""` (the model's parent directory) | the input directory |
| `include_reference_date_events` | 0 | QuantLib `Settings::includeReferenceDateEvents` (R) |
| `include_todays_cashflows` | -1 (none) | `Settings::includeTodaysCashFlows` (T) |
| `engine_include_settlement_flows` | -1 (none) | the engine's `includeSettlementDateFlows` (F) |
| `nontradable_policy` | 0 (`NT_ENGINE`) | bonds with no notional at settlement: prices 0.0, yield, z-spread and risk NaN; 1 (`NT_RAISE`) raises like pureql |
| `solver_error_policy` | 0 (`ERR_RAISE`) | a yield or z-spread solve that cannot bracket its root or runs out of evaluations, a sign-check failure, and the Macaulay duration of a yield that is not Compounded raise pureql's message; 1 (`ERR_NAN`) gives NaN instead |
| `output_level` | 1 | the columns of `result_frame()`: 1 prices; 2 also the yield and risk measures; 3 also the z-spread |
| `yield_solver` | 0 | 0 NewtonSafe (`BondFunctions.bondYield`'s solver), 1 Brent |
| `yield_accuracy`, `yield_max_evaluations`, `yield_guess` | 1e-10, 100, 0.05 | `BondFunctions.bondYield`'s defaults; `Bond.bondYield` uses accuracy 1e-8 |
| `zspread_accuracy`, `zspread_max_evaluations`, `zspread_guess` | 1e-10, 100, 0.0 | `BondFunctions.zSpread`'s defaults (Brent) |
| `zspread_price_source` | 0 | 0: a z-spread only where `prices.csv` has a price; 1: else from the engine's clean price |

## Outputs

Interactively, any Cells. `bond_portfolio/run.py` writes, into its output
directory:

| File | Rows | Columns |
|---|---|---|
| `cashflows.csv` | one per flow, bond then leg order | `bond_key`, `flow`, `kind`, `date`, `amount`, `nominal`, `rate`, `accrual_start`, `accrual_end`, `ref_start`, `ref_end`, `accrual_period` |
| `period_cashflows.csv` | one per (bond, period) with flows, then one per period 0..T for the portfolio | `level`, `bond_key`, `per`, `period_start`, `period_end`, `coupon`, `amortization`, `redemption`, `total` |
| `valuation_scen<k>.csv` | one per (t, bond) of scenario k | `scen_id`, `t`, `val_date`, `bond_key`, `settlement_date`, `notional`, `npv`, `settlement_value`, `dirty_price`, `clean_price`, `accrued_amount`, `market_value`, `tradable`, `expired`; with `--output-level 2` also `ytm`, `risk_yield`, `duration_simple`, `duration_modified`, `duration_macaulay`, `convexity`, `bpv`, `yvbp`, and with 3 also `zspread` |
| `valuation_totals.csv` | one per (scen_id, t) | `scen_id`, `t`, `val_date`, `npv_total`, `mv_total`, `sv_total`, `accrued_total`, `n_tradable`, `n_expired` |
| `run_summary.json` | | counts, wall time per stage, microseconds per bond-point, peak RSS |

Dates are ISO; floats are written in Python's shortest round-trip form, so
the files reproduce the model's values exactly. Period 0 holds the flows
already paid at the first valuation date, period `per` those paid after
`val_date[per-1]` up to `val_date[per]`, and period T those after the last
valuation date. Prices and accrued are per 100 of the notional at
settlement; `npv`, `settlement_value`, `market_value` and the totals are in
currency. Yields and z-spreads are decimals in the bond's yield conventions
and in the `(scen_id, t)` spread conventions; durations and convexity are in
years of the yield's day counter; BPV and YVBP are, as in QuantLib, not
rescaled (BPV is the change of the bond's npv, in currency, for +1bp).

## Running

The same model runs in three modes, with bit-identical results:

| Mode | What runs | Use |
|---|---|---|
| `modelx` | `mx.read_model("bond_portfolio/BondPortfolio")` | development, inspection, small runs |
| `export` | the pure-Python package `BondPortfolio_nomx` from `mx.export_model` | no modelx at run time; faster |
| `compiled` | `BondPortfolio_nomx_cy`, the export compiled by modelx-cython | production speed |

### Interactively (modelx)

```python
import modelx as mx

m = mx.read_model("bond_portfolio/BondPortfolio")
m.Data.input_dir = "bond_portfolio"          # the demo inputs
m.Data.check_inputs(); m.Legs.check_limits()
m.Legs.cashflow_frame()                       # the cash flows
m.Proj.period_table()                         # cash per projection period
v = m.Valuation[1, 0]                         # scenario 1 at val_date[0]
v.result_frame()                              # every bond
v.npv(0), v.dirty_price(0), v.npv_total()
v.ytm(0), v.duration_modified(0), v.zspread(4)  # yield, risk, z-spread (needs a price)
```

### With the driver

```
python bond_portfolio/run.py --inputs DIR --out DIR [--mode modelx|export|compiled]
                             [--scen LIST] [--times LIST]
                             [--output-level 1|2|3] [--solver-errors raise|nan]
```

`--output-level` adds the analytics columns (above). The default solver
error policy is the model's, `raise`: the run stops at the first failed solve,
and at the first Macaulay duration of a yield that is not Compounded (the
demo set has one); `--solver-errors nan` writes NaN there instead.

`--scen 2` or `--times 0-12,24` value a subset of the `(scen_id, t)` grid
(the cash-flow files are always complete). The driver validates the inputs,
checks them against the model limits and, in export and compiled mode,
against the sizes the build was compiled with (`<build>/sizes.json`);
pre-flights every curve; then values scenario by scenario with one
`Valuation` item alive at a time. Invalid inputs stop it with exit status 1
and a list of every problem, before any valuation output is written.

### Building the export and compiled packages

```
python tools/build_cy.py
```

exports the model, generates the modelx-cython spec from the `MAX_*`
References, compiles, audits the C types and writes `sizes.json`. On Windows
run it from PowerShell (from Git Bash the MSVC `cl.exe` step fails). The build
lives in `~/.cache/lifelib-assets/build` when the project is in a OneDrive
folder, else in `build/`; `BONDPORTFOLIO_BUILD` overrides it
(`tools/buildpaths.py`). Rebuild after every change to the model.

An exported or compiled instance never invalidates its caches: set
`Data.input_dir` (and any setting) on a fresh instance before calculating.

```python
import sys; sys.path.insert(0, "<build dir>")
import BondPortfolio_nomx_cy as pkg            # or BondPortfolio_nomx
m = pkg._mx_model._c_BondPortfolio()
m.Data.input_dir = "bond_portfolio"
m.Valuation[1, 0].result_frame()
```

### Calibrating spreads

```
python tools/calibrate_spreads.py --inputs DIR --out DIR [--mode modelx|export|compiled] [--scen K]
```

solves, with the model, the z-spread of every bond priced at `t = 0` in
`prices.csv`, and writes a copy of the input set in which those bonds have
`spread_id = bond_key` and `spreads.csv` carries their spread at every
`(scen_id, t)` (DECISIONS.md D-4). It checks the result: at `t = 0` the
engine price of each calibrated bond equals its price from the solved spread
bit for bit, and differs from the quote by the solver accuracy only.

## Limits

The compiled model stores the Cells of a `Valuation` item in C arrays sized by
model-level References (`BondPortfolio/__init__.py`); an index beyond a size
fails. `Legs.check_limits()` and the driver refuse inputs beyond them:

| Reference | Default | Bounds |
|---|---|---|
| `MAX_BONDS` | 12,000 | bonds N |
| `MAX_FLOWS` | 480,000 | flows P of the portfolio |
| `MAX_SCHED` | 1,200 | flows of one bond |
| `MAX_T` | 1,201 | valuation dates T |
| `MAX_SCEN` | 1,000 | scenarios S |
| `MAX_NODES` | 64 | nodes of one ZeroCurve |
| `MAX_SETTLE_DAYS` | 7 | settlement days |
| `MAX_KD` | 40,000 | day offsets from a valuation date: the latest flow or issue date minus the earliest valuation date must be below it (about 109 years) |
| `CAL_MAX` | 4 | calendar codes |

To raise one, edit the Reference in `BondPortfolio/__init__.py` and rebuild.
Larger sizes cost mainly memory per `Valuation` item.

## Memory

Each `Valuation` item holds the values of every bond at one `(scen_id, t)`.
`run.py` creates an item, writes its results, then deletes it and calls
`gc.collect()`: exported and compiled Spaces refer to themselves, so `del`
alone frees nothing until the cyclic collector runs
([docs/mx2cy-issues.md](../docs/mx2cy-issues.md) #4). In export and compiled
mode the driver also deletes the `Bond[b]` items once `Legs` is built (Legs
holds everything later stages read) and calls `gc.freeze()`. In modelx mode
the Bond items stay (deleting them would clear `Legs`), so modelx mode is for
development-size portfolios. Measured times and memory are in
[docs/performance.md](../docs/performance.md).

## Tests

```
python -m pytest                      # all but the slow, perf and compiled markers
python -m pytest -m slow              # full sweeps: fuzz, flag matrices, every mode case
python tools/build_cy.py              # (from PowerShell on Windows) then:
python -m pytest -m compiled          # compiled == export == modelx
python -m pytest -m oracle            # only the QuantLib 1.41 comparisons (T2 tolerance)
python -m pytest -m perf              # memory streaming on a generated portfolio
```

The tests compare the model with pureql bit for bit, and expect a
quantlib-migration checkout next to this project (or `PUREQL_SRC`).
