# BondPortfolio input files

The model reads its inputs from CSV files in `Data.input_dir` (default: the
directory containing the model, i.e. this directory). Every file is read with
`pd.read_csv(path, dtype=str, keep_default_na=False)`: all values are text,
surrounding whitespace is ignored and an empty cell is **blank**. Column order
does not matter and extra columns are ignored. Run `Data.check_inputs()` to
validate a set of files; it lists every problem it finds.

| File | Required | Keyed by |
|---|---|---|
| `bonds.csv` | yes | row order (the bond index `b` is the 0-based row) |
| `coupon_rates.csv` | no | `bond_key`, `k` |
| `valuation_dates.csv` | yes | `t` |
| `curve_params.csv` | yes | `scen_id`, `t` |
| `curve_nodes.csv` | no (needed for ZeroCurve) | `scen_id`, `t`, `node` |
| `spreads.csv` | no (needed if a bond has a `spread_id`) | `scen_id`, `t`, `spread_id` |
| `prices.csv` | no | `scen_id`, `t`, `bond_key` |
| `yields.csv` | no | `scen_id`, `t`, `bond_key` |

`scen_id` runs 1..S and `t` runs 0..T-1. In the model's arrays the row of a
scenario is `scen_id - 1`.

## Value formats

| Kind | Format | Notes |
|---|---|---|
| date | ISO `YYYY-MM-DD` | blank is the null date (serial 0). The serial is `(date - 1899-12-30).days`, QuantLib's serial number; the valid range is 1901-01-01..2199-12-31 (367..109574). |
| tenor | `<n><D\|W\|M\|Y>` | e.g. `1M`, `3M`, `6M`, `1Y`, `2W`, `0D`. A zero tenor (`0D`) gives a one-period schedule (the Zero rule). |
| flag | `0`, `1`, `true`, `false` | blank is 0. |
| number | decimal, e.g. `0.04`, `100` | rates are decimals (`0.04` is 4%); prices and redemptions are per 100 of face. |
| calendar | `NullCalendar`, `TARGET`, `UnitedStates.Settlement`, `UnitedStates.GovernmentBond` | codes `CAL_NULL`..`CAL_US_GOVBOND` (0..3). |
| day counter | `Actual360`, `Actual365Fixed`, `Thirty360.USA`, `Thirty360.BondBasis`, `Thirty360.ISMA`, `Thirty360.European`, `Thirty360.EurobondBasis` | codes `DC_ACT360`=1, `DC_ACT365F`=2, `DC_30360_USA`=10, `DC_30360_BB`=11 (BondBasis and ISMA), `DC_30360_EU`=12 (European and EurobondBasis). |
| business-day convention | `Following`, `ModifiedFollowing`, `Preceding`, `ModifiedPreceding`, `Unadjusted`, `HalfMonthModifiedFollowing`, `Nearest` | pureql `BusinessDayConvention` values 0..6. |
| compounding | `Simple`, `Compounded`, `Continuous`, `SimpleThenCompounded`, `CompoundedThenSimple` | pureql `Compounding` values 0..4. |
| frequency | `NoFrequency`, `Once`, `Annual`, `Semiannual`, `EveryFourthMonth`, `Quarterly`, `Bimonthly`, `Monthly`, `EveryFourthWeek`, `Biweekly`, `Weekly`, `Daily`, `OtherFrequency` | pureql `Frequency` values. `Compounded`, `SimpleThenCompounded` and `CompoundedThenSimple` need a frequency other than `NoFrequency` or `Once` (the InterestRate guard). |
| rule | `Backward` | v1 supports `Backward` only; the other pureql `DateGeneration` names are recognised and rejected by `check_inputs`. |
| bond type | `FixedRate`, `ZeroCoupon` | `BOND_FIXED`=0, `BOND_ZERO`=1. |
| curve type | `ZeroCurve`, `FlatForward` | `CURVE_ZERO`=0, `CURVE_FLAT`=1. |

Any other name is an error.

## `bonds.csv`

One row per bond. FixedRate bonds are pureql `FixedRateBond(settlementDays,
faceAmount, Schedule(...), coupons, accrualDayCounter, paymentConvention,
redemption, issueDate, paymentCalendar, firstPeriodDayCounter=...)`;
ZeroCoupon bonds are `ZeroCouponBond(settlementDays, calendar, faceAmount,
maturityDate, paymentConvention, redemption, issueDate)`.

| Column | Bonds | Required | Blank means |
|---|---|---|---|
| `bond_key` | all | yes, unique | - |
| `bond_type` | all | yes | - |
| `face_amount` | all | yes | - |
| `settlement_days` | all | yes, 0..`MAX_SETTLE_DAYS` (7) | - |
| `calendar` | all | yes | - (the schedule calendar of a FixedRate bond) |
| `issue_date` | all | no | no issue date |
| `redemption` | all | no | 100 |
| `spread_id` | all | no | no spread: the bond is valued on the plain curve |
| `effective_date` | FixedRate | yes | - |
| `termination_date` | FixedRate | yes, after `effective_date` | - |
| `tenor` | FixedRate | yes | - |
| `convention` | FixedRate | no | `Following` (MakeSchedule's default with a calendar) |
| `termination_convention` | FixedRate | no | `convention` |
| `rule` | FixedRate | no | `Backward` |
| `end_of_month` | FixedRate | no | 0 |
| `first_date` | FixedRate | no | none |
| `next_to_last_date` | FixedRate | no | none |
| `coupon_rate` | FixedRate | one of `coupon_rate` or rows in `coupon_rates.csv` | - |
| `accrual_day_counter` | FixedRate | yes | - |
| `first_period_day_counter` | FixedRate | no | none (the accrual day counter applies) |
| `payment_convention` | all | no | `Following` |
| `payment_calendar` | FixedRate | no | the schedule calendar |
| `maturity_date` | ZeroCoupon | yes | - (ignored for FixedRate bonds, which mature at the schedule's end) |
| `yield_day_counter` | all | no | FixedRate: `accrual_day_counter`; ZeroCoupon: `Actual365Fixed` |
| `yield_compounding` | all | no | `Compounded` |
| `yield_frequency` | all | no | FixedRate: the frequency of `tenor` (`Period.frequency()`) when it is a regular frequency (`Annual`..`Daily`), else `Annual` (e.g. for `0D`); ZeroCoupon: `Annual` |

The `yield_*` columns are the conventions of the bond's yield quote, used
for yields, durations, convexity and prices from yields. Columns of the other
bond type are ignored.

## `coupon_rates.csv` (optional)

Step-up coupons: the coupon-rate vector of a FixedRate bond, as pureql's
`FixedRateLeg.withCouponRates` takes it (rate `k` applies to coupon `k`; the
last rate applies to every later coupon).

| Column | Notes |
|---|---|
| `bond_key` | a FixedRate bond of `bonds.csv` whose `coupon_rate` is blank |
| `k` | 0, 1, ..., n-1 for each bond, without gaps |
| `rate` | number |

## `valuation_dates.csv`

| Column | Notes |
|---|---|
| `t` | 0..T-1, once each |
| `val_date` | the valuation (evaluation) date of `t`; strictly increasing in `t`; shared by all scenarios |

## `curve_params.csv`

One row per (scenario, valuation date); the rows must cover the dense grid
`scen_id` 1..S x `t` 0..T-1. The curve's reference date is `val_date(t)`.

| Column | Required | Blank means |
|---|---|---|
| `scen_id` | yes | - |
| `t` | yes | - |
| `curve_type` | yes | - |
| `day_counter` | yes | - |
| `compounding` | no | `Continuous` (pureql's ZeroCurve / FlatForward default) |
| `frequency` | no | `Annual` |
| `extrapolate` | no | 0 (as pureql: no extrapolation beyond the last node) |
| `flat_rate` | FlatForward only | - |
| `spread_compounding` | no | `Continuous` (ZeroSpreadedTermStructure's default) |
| `spread_frequency` | no | `NoFrequency` |

A ZeroCurve's nodes are in `curve_nodes.csv`; `flat_rate` is ignored for it.

## `curve_nodes.csv` (optional; needed for ZeroCurve)

The nodes of the ZeroCurve at (scen_id, t): linear interpolation on the zero
rates, quoted with the curve's `day_counter`, `compounding` and `frequency`.

| Column | Notes |
|---|---|
| `scen_id`, `t` | a (scen_id, t) of `curve_params.csv` |
| `node` | 0, 1, ..., k-1 within the (scen_id, t), without gaps |
| `date` | the node date, or blank if `tenor` is given |
| `tenor` | the node date as `val_date(t) + tenor` (no calendar, as `Date + Period`), or blank if `date` is given |
| `rate` | the zero rate |

A ZeroCurve needs 2..`MAX_NODES` (64) nodes; node 0 must fall on `val_date(t)`
(write `0D` or the date itself) and the node dates must be strictly
increasing. Nodes given for a FlatForward (scen_id, t) are not used (they
must still be well-formed).

## `spreads.csv` (optional; needed if any bond has a `spread_id`)

| Column | Notes |
|---|---|
| `scen_id`, `t` | a (scen_id, t) of `curve_params.csv` |
| `spread_id` | an id named by bonds in `bonds.csv` |
| `spread` | the zero spread added to the curve (ZeroSpreadedTermStructure, with the `spread_compounding` and `spread_frequency` of `curve_params.csv`) |

Every `spread_id` used by a bond needs a spread at every (scen_id, t).

## `prices.csv` and `yields.csv` (optional, sparse)

Quotes used by the z-spread and yield solvers (Phase 4).

| File | Columns |
|---|---|
| `prices.csv` | `scen_id`, `t`, `bond_key`, `price` (per 100 of notional), `price_type` (`Clean` or `Dirty`; blank is `Clean`) |
| `yields.csv` | `scen_id`, `t`, `bond_key`, `yield` (with the bond's `yield_*` conventions) |

Each (scen_id, t, bond_key) at most once.

## Generating inputs

`generate_inputs.py` writes this schema for a random portfolio
(`--n-bonds --n-scen --n-times --seed --out`, plus `--base-date` and `--step`
for the valuation dates) or, with `--coverage`, the small deterministic set
in `tools/cy/sample_inputs/` that exercises every supported convention.
`--validate` builds every bond with pureql (from `PUREQL_SRC`).

The files in this directory are a small demo portfolio: the quantlib-migration
README headline bond (`HEADLINE_10Y`), the three bonds of QuantLib's
`testCachedZero` (`ZCB_2006`..`ZCB_2008`, all expired by 2015), the tracer
`zcb-10y` bond (`ZCB_10Y`) and eight more FixedRate bonds covering the other
calendars, day counters, stubs, end of month, a step-up and a one-period
(`0D`) bond; two scenarios over four valuation dates from 2015-09-16, with the
headline's flat 3% Actual365Fixed curve at (1, 0), the tracer zero curve at
(2, 0) and ZeroCurves by date and by tenor elsewhere. `prices.csv` and
`yields.csv` carry the tracer `zcb-10y` quotes (clean price 80, yield 2.5%) at
(1, 0) and (2, 0), where the spread conventions are the tracer's z-spread
conventions (Compounded, Annual).
