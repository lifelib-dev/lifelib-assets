# BondPortfolio model contract (developer reference)

This is the binding interface between the Spaces of `bond_portfolio/BondPortfolio`. The design and its rationale are in the approved plan (copied to `docs/plan.md`). This file fixes the **names, signatures, return types, codes and coding rules** that every Space implementation and every test must use.

Abbreviations:
- `PQ` = `C:/Users/fumito/OneDrive/pyproj/quantlib-migration/src/pureql`
- `QLM` = `C:/Users/fumito/OneDrive/pyproj/quantlib-migration`

---

## 0. Authoring

- **Where the model lives.** The model is the serializer-8 tree under `bond_portfolio/BondPortfolio/`. `tools/new_model.py` created the skeleton once: the Spaces, the References and the model-level constants.
- **Editing.** Formulas are edited **in place** in `bond_portfolio/BondPortfolio/<Space>/__init__.py`. The file layout is:
  1. the header and docstring;
  2. `from modelx.serialize.jsonvalues import *`;
  3. `_formula`, `_bases`, `_allow_none` and `_spaces`;
  4. the line `# ---------------------------------------------------------------------------` followed by `# Cells`, then one `def` per Cells (for an uncached Cells, add the line `_is_cached = False` right after its `def` body);
  5. the same divider line followed by `# References`, then the References.
- **Loading.** The model is loaded with `mx.read_model(path)`.
- **Inputs.** Tests and drivers set `model.Data.input_dir = "<dir>"` before calculating.
- **No pureql in the model.** The model must never import `pureql` or `QuantLib` (QLM decision D-11). Tests may: `tests/helpers/pureql_ref.py` puts `PUREQL_SRC` (default `../quantlib-migration/src`) on `sys.path`.

## 1. Provenance and licence (enforced by `tests/lint`)

Every Cells transcribed from pureql carries both of the following.

**In its body**, as the first lines after the docstring:
```python
    # ported from pureql/<path relative to PQ> (ql/<file>:<first>-<last>), QuantLib v1.43, BSD-3-Clause
```
- The `ql/...:a-b` part is copied **verbatim** from the `# ql:` anchor line just above the pureql function you read, prefixed with `ql/`. Example: pureql `# ql: calendar.cpp:84-128` becomes `(ql/calendar.cpp:84-128)`.
- If the anchor names several files or ranges, copy its whole text.
- A Cells built from several pureql functions has one such line per function.
- Port-author rider files (`_cxx.py`) use `(port rider)` in place of the ql part.

**In its docstring**, a line reading exactly:
```
    Derived from QuantLib (BSD-3-Clause); see NOTICE.md.
```

Plumbing Cells that are not derived (CSV readers, aggregations) carry neither.

## 2. Model-level References (defined in `BondPortfolio/__init__.py`)

The values equal pureql's own enums wherever pureql has one.

```
# modules
math = ("Module", "math"); np = ("Module", "numpy"); pd = ("Module", "pandas"); datetime = ("Module", "datetime")
# BusinessDayConvention (PQ time/businessdayconvention.py:66-73)
BDC_FOLLOWING=0 BDC_MODIFIED_FOLLOWING=1 BDC_PRECEDING=2 BDC_MODIFIED_PRECEDING=3
BDC_UNADJUSTED=4 BDC_HALF_MONTH_MODIFIED_FOLLOWING=5 BDC_NEAREST=6
# TimeUnit (timeunit.py:95-98)
TU_DAYS=0 TU_WEEKS=1 TU_MONTHS=2 TU_YEARS=3
# Frequency (frequency.py:66-78)
FREQ_NO_FREQUENCY=-1 FREQ_ONCE=0 FREQ_ANNUAL=1 FREQ_SEMIANNUAL=2 FREQ_EVERY_FOURTH_MONTH=3
FREQ_QUARTERLY=4 FREQ_BIMONTHLY=6 FREQ_MONTHLY=12 FREQ_EVERY_FOURTH_WEEK=13 FREQ_BIWEEKLY=26
FREQ_WEEKLY=52 FREQ_DAILY=365 FREQ_OTHER_FREQUENCY=999
# Compounding (compounding.py:56-60)
COMP_SIMPLE=0 COMP_COMPOUNDED=1 COMP_CONTINUOUS=2 COMP_SIMPLE_THEN_COMPOUNDED=3 COMP_COMPOUNDED_THEN_SIMPLE=4
# DateGeneration.Rule (dategenerationrule.py:62-71); v1 implements BACKWARD and ZERO only
RULE_BACKWARD=0 RULE_FORWARD=1 RULE_ZERO=2
# Duration.Type (duration.py:54-56) and Bond.Price.Type (bond.py:185-186)
DUR_SIMPLE=0 DUR_MACAULAY=1 DUR_MODIFIED=2   PRICE_DIRTY=0 PRICE_CLEAN=1
# Weekday (weekday.py:83-89) and Month
SUNDAY=1 MONDAY=2 TUESDAY=3 WEDNESDAY=4 THURSDAY=5 FRIDAY=6 SATURDAY=7
JANUARY=1 ... DECEMBER=12
# model codes
CAL_NULL=0 CAL_TARGET=1 CAL_US_SETTLEMENT=2 CAL_US_GOVBOND=3          (4+ reserved)
DC_ACT360=1 DC_ACT365F=2 DC_30360_USA=10 DC_30360_BB=11 DC_30360_EU=12   (13-19 Thirty360, 20-29 ActualActual reserved)
BOND_FIXED=0 BOND_ZERO=1                                               (2 = amortizing, reserved)
CURVE_ZERO=0 CURVE_FLAT=1
CF_COUPON=0 CF_AMORTIZING=1 CF_REDEMPTION=2
ROLE_ENGINE=0 ROLE_SETTLE=1 ROLE_EXPIRY=2
SOLVE_YIELD=0 SOLVE_ZSPREAD=1
NT_ENGINE=0 NT_RAISE=1   ERR_RAISE=0 ERR_NAN=1
NULL_DATE=0 MIN_SERIAL=367 MAX_SERIAL=109574
QL_EPSILON=2.220446049250313e-16 CLOSE_N=42 ZERO_RATE_DT=0.0001 ZSPREAD_STEP=0.01 BASIS_POINT=0.0001
# compile-time limits (spec.py sizes come from these)
MAX_BONDS=12000 MAX_FLOWS=480000 MAX_KD=40000 MAX_NODES=64 MAX_T=1201 CAL_MAX=4 MAX_SETTLE_DAYS=7 MAX_SCHED=1200 MAX_SCEN=1000
```

**Code name mapping.** CSV inputs carry these names; the parsers turn them into the codes above.
- Calendar: `NullCalendar`, `TARGET`, `UnitedStates.Settlement`, `UnitedStates.GovernmentBond`.
- Day counter:
  - `Actual360`, `Actual365Fixed`;
  - `Thirty360.USA`;
  - `Thirty360.BondBasis` and `Thirty360.ISMA` → `DC_30360_BB`;
  - `Thirty360.European` and `Thirty360.EurobondBasis` → `DC_30360_EU`.
  - Check these pairs against `PQ time/daycounters/thirty360.py` `_implementation`.
- BDC / compounding / frequency / rule: the pureql enum member names (`Following`, `Compounded`, `Semiannual`, `Backward`, ...).
- Bond type: `FixedRate`, `ZeroCoupon`.
- Tenor: `<n><D|W|M|Y>`, e.g. `6M`, `1Y`, `0D`.
- Dates: ISO `YYYY-MM-DD`, or blank for the null date. The serial is `(date - 1899-12-30).days`.

## 3. Coding rules (enforced by `tests/lint` where mechanical)

1. **Integer representations.**
   - **Dates are `int` serials.** 0 is the null date `Date()`. The valid range is 367..109574.
   - **Enums are `int` codes**, and **flags are `int` 0/1**. Tri-states are -1 (None), 0 and 1.
2. **Return values.**
   - Never return `None`.
   - Never return `np.bool_` or `np.float64` from a scalar Cells. Use `bool(...)` / `float(...)` / `int(...)` at the return when a value comes from numpy.
   - Float Cells return float literals (`0.0`, not `0`).
3. **Wrap float reads.** Write every float64 array-element read as `float(X()[i])`. Write every float argument passed to a Cells that has a float parameter as `float(expr)`.
4. **Array Cells** (Cells returning numpy arrays) are used **only element-wise**, in the form `x_arr()[i]` or `x_arr()[i, j]` with a full index. Never assign them to a local, never `len()` them, never pass them anywhere. Code that needs whole columns reads the DataFrame or dict source Cells instead (`bond_table()`, `leg_columns()`).
5. **Forbidden constructs:**
   - **Arithmetic:** `**` (use `float(math.pow(a, b))` with `except (OverflowError, ValueError)` falling back to `lib.cxx_pow(a, b)`, and the same pattern for `math.exp` → `lib.cxx_exp`); `sum(`, `math.fsum`, `np.sum`, `.sum(` and `round(` (use sequential `+=` in upstream order).
   - **Control flow:** `match` statements; `yield`; closures, lambdas and comprehensions in Valuation hot Cells.
   - **Calls:** keyword-argument calls to Cells.
   - **Naming:** any name starting with `_` for a Cells or Reference; a Cells named like a Reference, a Space parameter (`b`, `scen_id`, `t`) or a Space.
   - **Space features:** Space formulas returning base/refs; `_bases`; child spaces under ItemSpaces; ModuleData or PandasData.
6. **Errors.** Raise `ValueError("<pureql message>")` where pureql raises `Error`, keeping the message text.
7. **No Cython-reserved names.** Never use a Cython keyword as a Cells, parameter or local name: `include`, `cimport`, `cdef`, `by`, `sizeof`, `NULL`, `struct`, `public`, `extern`, `inline`, `const`, `long`, `double`, `int`, `float`, `object`, and the rest of the list in `tests/lint/test_model_lint.py::CYTHON_RESERVED`. Such a name breaks the generated `.pxd`.
8. **Parameter names per domain.** Pick from: `d`, `d1`, `d2` (dates); `yr` (year); `m` (month); `leap`; `w` (weekday); `cal`; `conv`; `dc`; `n`; `unit`; `b` (bond index, Bond's Space parameter); `i` (coupon index within a bond); `p` (global flow index); `per` (projection period); `kd` (day offset); `nd` (curve node); `role`; `kind`; `nsd` (settlement days); `x`, `y`, `z` (floats).
9. **Fidelity.** Keep pureql's statement order, operand order and local names wherever practical. Sequential `+=` sums run in leg order. Keep the `_cxx` IEEE sites (pow, exp, div) as `lib.cxx_*` calls or the try/except idiom above.

## 4. Spaces and Cells

**Legend:**

| Mark | Meaning |
|---|---|
| [C] | cached, int-only parameters, scalar return |
| [S] | parameterless scalar |
| [D] | cached with a float parameter |
| [O] | returns an object or array |
| [U] | uncached (`_is_cached = False`) |

All transcribed Cells follow section 1.

### 4.1 `Lib` (singleton). Canonical numerics (all [U] unless marked)

References: `dates` (Interface → Dates).

| Cells | Returns | Transcribes |
|---|---|---|
| `nan_value()` [S], `inf_value()` [S] | float | `float("nan")`, `float("inf")` |
| `cxx_exp(x)`, `cxx_pow(x, y)`, `cxx_div(x, y)` | float | PQ `_cxx.py` exp/pow/div, including the inf/nan semantics |
| `cxx_lround(x)`, `cxx_idiv(a, c)` | int | PQ `_cxx.py` (only if a v1 transcription needs them) |
| `close(x, y)`, `close_enough(x, y)` | bool | PQ `math/comparison.py:78-118`, with n = `CLOSE_N` (42) |
| `check_rate(comp, freq)` | bool | the `InterestRate._init_rate` guard (`interestrate.py:189-209`); raises like pureql, else returns True |
| `compound_factor(r, comp, freq, tt)` | float | `InterestRate._compoundFactor_time` (`interestrate.py:334-376`), all 5 branches |
| `compound_factor_dates(r, comp, freq, dc, d1, d2, r1, r2)` | float | `interestrate.py:379-390`: `dates.year_fraction(dc, d1, d2, r1, r2)`, then `compound_factor` |
| `discount_factor(r, comp, freq, tt)` | float | `interestrate.py:279-292` |
| `implied_rate(compound, comp, freq, tt)` | float | `interestrate.py:432-486`, with the exact `compound == 1.0` short-circuit first |
| `equivalent_rate(r, comp, freq, tt, comp2, freq2)` | float | `interestrate.py:541-549` |
| `has_occurred(d, ref, include_flag, eval_date, todays, ref_events)` | bool | `CashFlow.hasOccurred` + `Event.hasOccurred` (`cashflow.py:123-155`, `event.py:92-128`). Settings become arguments: `include_flag` and `todays` are tri-states (-1 None, 0, 1); `ref_events` is 0/1; `eval_date` is the explicit evaluation date. (Not `include`: that is a Cython keyword.) |
| `trading_ex_coupon(ex_date, ref)` | bool | `cashflow.py:188-207`; False if `ex_date == NULL_DATE` |
| (Phase 4) `sign(x)`, `stepwise_time(...)` | | |
| (Phase 2) `coupon_accrued_amount(...)` | | |

### 4.2 `Dates` (singleton). Date algebra, calendars and day counters

References: `lib`. The serial domain is 0..109574 and the year domain is 1900..2200.

| Cells | Kind | Returns | Transcribes |
|---|---|---|---|
| `year_offset_table()`, `month_length_table()`, `month_leap_length_table()`, `month_offset_table()`, `month_leap_offset_table()`, `year_is_leap_table()`, `western_easter_table()` | [O] | int64 ndarray | PQ `time/date.py` tables, `calendar.py:167-206` |
| `is_leap(yr)` | [C] | bool | `Date.isLeap` (`date.py:726`) |
| `year_offset(yr)` | [C] | int | `date.py:758` |
| `month_length(m, leap)`, `month_offset(m, leap)` | [C] | int | `date.py:741-756`. `leap` is 0/1; `m` runs 1..13 for the offset |
| `year(d)`, `month(d)`, `day_of_month(d)`, `day_of_year(d)`, `weekday(d)` | [C] | int | `date.py:513-585`; DEV-01 null-date raises |
| `end_of_month(d)` | [C] | int | `date.py:861` |
| `is_end_of_month(d)` | [C] | bool | `date.py:873` |
| `make_date(dd, m, yr)` | [U] | int | `Date._init_dmy` (`date.py:498`), with its checks |
| `check_serial(d)` | [U] | bool | `date.py:791`; raises |
| `advance_date(d, n, unit)` | [U] | int | `Date._advance` (`date.py:671-722`) for Days/Weeks/Months/Years; the result is range-checked like `Date(...)` |
| `nth_weekday(nth, w, m, yr)` | [U] | int | `date.py:891` (if needed) |
| `easter_monday(yr)` | [C] | int (day of year) | `WesternImpl.easterMonday` (`calendar.py:286`) |
| `is_weekend_western(w)` | [C] | bool | `calendar.py:280` |
| `target_bd(d)`, `us_settlement_bd(d)`, `us_govbond_bd(d)` | [C] | bool | `calendars/target.py:72`; `calendars/unitedstates.py:264` (SettlementImpl) and `:467` (GovernmentBondImpl), with the `_is*Day` helpers as [U] Cells `us_washington_birthday(dd, m, yr, w)` etc. |
| `is_business_day(cal, d)` | [C] | bool | `Calendar.isBusinessDay` (`calendar.py:419`): dispatch on `cal`; NullCalendar is always True. No added/removed holidays in v1 |
| `is_holiday(cal, d)` | [U] | bool | `calendar.py:468` |
| `cal_is_end_of_month(cal, d)`, `cal_end_of_month(cal, d)` | [U] | bool / int | `calendar.py:458-466` |
| `adjust(cal, d, conv)` | [U] | int | `Calendar.adjust` (`calendar.py:548-601`), all 7 conventions |
| `advance(cal, d, n, unit, conv, eom)` | [U] | int | `Calendar._advance_units` (`calendar.py:643-700`); `eom` is 0/1 |
| `day_count(dc, d1, d2)` | [U] | int | `DayCounter.dayCount` per impl: `actual360.py:75`, `actual365fixed.py`, `thirty360.py:158/193/219` (USA / ISMA(=BondBasis) / European) |
| `year_fraction(dc, d1, d2, r1, r2)` | [U] | float | `DayCounter.yearFraction` (`daycounter.py:147`) per impl. `r1` and `r2` are reference dates (0 = null; unused by the v1 day counters, kept for ActualActual later) |
| `period_frequency(n, unit)` | [U] | int | `Period.frequency()` (`period.py`) |
| `allows_end_of_month(n, unit)` | [U] | bool | `schedule.py:1298` |

### 4.3 `Data` (singleton). Inputs and settings (plumbing, not derived)

References:
- `input_dir = ""`
- file names: `bond_file="bonds.csv"`, `coupon_rate_file="coupon_rates.csv"`, `val_date_file="valuation_dates.csv"`, `curve_param_file="curve_params.csv"`, `curve_node_file="curve_nodes.csv"`, `spread_file="spreads.csv"`, `price_file="prices.csv"`, `yield_file="yields.csv"`
- settings: `include_reference_date_events=0`, `include_todays_cashflows=-1`, `engine_include_settlement_flows=-1`, `nontradable_policy=0`, `solver_error_policy=0`, `output_level=1`, `yield_solver=0`, `yield_accuracy=1e-10`, `yield_max_evaluations=100`, `yield_guess=0.05`, `zspread_accuracy=1e-10`, `zspread_max_evaluations=100`, `zspread_guess=0.0`, `zspread_price_source=0`
- `dates` (Interface)

Cells:
- `input_path()` [S] → str: `input_dir` if set, else `str(_model.path.parent)`.
- Readers [O], each reading a CSV once with `pd.read_csv(path, dtype=str, keep_default_na=False)`. Optional files return an empty frame with the right columns when the file is absent: `bond_table()`, `coupon_rate_table()`, `val_date_table()`, `curve_param_table()`, `curve_node_table()`, `spread_table()`, `price_table()`, `yield_table()`.
- Parsers [U]:
  - `iso_serial(s)` → int, where '' gives 0;
  - code parsers `calendar_code(s)`, `daycounter_code(s)`, `bdc_code(s)`, `comp_code(s)`, `freq_code(s)`, `rule_code(s)`, `bond_type_code(s)`;
  - tenor parsers `tenor_n(s)` and `tenor_unit(s)`;
  - `flag(s)` → 0/1, where '' gives the default.
- Counts [S]: `n_bonds()`, `n_scen()`, `n_times()`, `n_spread_ids()`, `n_nodes_total()`.
- Bond arrays [O], 1-D over `b`, int64 unless noted:

  | Group | Arrays |
  |---|---|
  | All bonds | `b_type_arr`, `b_face_arr` (f), `b_settle_days_arr`, `b_calendar_arr`, `b_issue_arr`, `b_redemption_arr` (f), `b_spread_idx_arr` (-1 means none; else the index into `spread_ids()`) |
  | Schedule | `b_eff_arr`, `b_term_arr`, `b_tenor_n_arr`, `b_tenor_unit_arr`, `b_conv_arr`, `b_term_conv_arr`, `b_rule_arr`, `b_eom_arr`, `b_first_arr`, `b_ntl_arr` |
  | Coupons | `b_accrual_dc_arr`, `b_first_dc_arr` (0 = none), `b_pay_conv_arr`, `b_pay_cal_arr` (-1 = the schedule calendar), `cr_lo_arr` / `cr_cnt_arr` (CSR into `cr_rate_arr` (f), the coupon-rate vector per bond; a scalar `coupon_rate` gives 1 entry) |
  | ZCB | `b_maturity_arr` |
  | Yield quote | `b_ydc_arr`, `b_ycomp_arr`, `b_yfreq_arr` |

- Other per-bond [O]: `bond_keys()` → tuple of str; `spread_ids()` → tuple of str.
- Scenario × time arrays [O]:
  - `val_date_arr()` [T];
  - `c_type_arr`, `c_dc_arr`, `c_comp_arr`, `c_freq_arr`, `c_extrap_arr`, `c_sp_comp_arr`, `c_sp_freq_arr` [S, T] int64;
  - `c_flat_arr` [S, T] f;
  - `n_lo_arr`, `n_cnt_arr` [S, T] (CSR into `n_date_arr` / `n_rate_arr` (f));
  - `sp_arr` [S, T, NSID] f (absent entries are NaN).
  - `scen_id` is 1..S; the array row is `scen_id - 1`.
- Validation: `check_inputs()` [S] → bool (raises `ValueError` with a clear message).

### 4.4 `Bond[b]` (ItemSpace, `_formula = lambda b: None`; `b` = 0-based row of bonds.csv; reference `b = 0`)

References: `data`, `lib`, `dates`. Generated **once per bond**, at Python speed. Tuples are immutable cache values.

| Cells | Returns | Transcribes |
|---|---|---|
| Input accessors [S]: `bond_type()`, `face_amount()`, `settlement_days()`, `bond_calendar()`, `issue_date()`, `redemption()`, `spread_index()`, `effective_date()`, `termination_date()`, `tenor_n()`, `tenor_unit()`, `convention()`, `termination_convention()`, `rule()`, `end_of_month()`, `first_date()`, `next_to_last_date()`, `accrual_dc()`, `first_period_dc()`, `payment_convention()`, `payment_calendar_in()`, `maturity_in()`, `yield_dc()`, `yield_comp()`, `yield_freq()` | int / float | data arrays at `[b]` |
| `coupon_rates()` | [O] tuple of float | the CSR slice |
| `schedule()` | [O] tuple `(dates, is_regular, has_tenor, tenor_n, tenor_unit, calendar, convention, termination_convention, rule, end_of_month)`, where `dates` is a tuple of int serials and `is_regular` a tuple of bool (empty if none) | `Schedule._init_rule` (`time/schedule.py:340-716`). Statement for statement: Backward and the Zero arm; any other rule raises `ValueError("rule not supported in this model version")`; DEV-02 guard |
| `coupons()` | [O] tuple of records `(pay, acc_start, acc_end, ref_start, ref_end, ex_date, nominal, rate, comp, freq, dc)` | `FixedRateLeg.build` (`cashflows/fixedratecoupon.py:532-630`) with FixedRateBond's settings (`instruments/bonds/fixedratebond.py:111-205`): notionals `[face]`, rates `(r, Simple, Annual)`, `firstPeriodDC`, payment calendar, payment adjustment, no ex-coupon period (`ex_date = 0`) |
| `coupon_amounts()` | [O] tuple of float | `FixedRateCoupon.performCalculations` (`fixedratecoupon.py:245-259`): `nominal * (lib.compound_factor_dates(...) - 1.0)` |
| `accrual_periods()` | [O] tuple of float | `Coupon.accrualPeriod` (`coupon.py:183-194`) |
| `notional_schedule()` | [O] `(dates, notionals)` | FixedRateBond: `Bond.calculateNotionalsFromCashflows` (`bond.py:1385-1436`). ZCB: `setSingleRedemption` (`bond.py:1336-1382`) |
| `redemption_flows()` | [O] tuple of `(date, kind, amount)` | `Bond.addRedemptionsToCashflows` (`bond.py:1270-1323`); ZCB `setSingleRedemption` |
| `leg()` | [O] tuple of `(date, kind, amount, coupon_index)` | coupons followed by redemption flows, **stable**-sorted by date (`bond.py:1323`); `coupon_index` is -1 for non-coupons |
| `maturity_date()` | int | FixedRateBond: `schedule.endDate()` (`fixedratebond.py:167`). ZCB: the unadjusted input maturity (`zerocouponbond.py:95`) |
| `n_flows()` | int | `len(leg())` |
| `cashflow_table()` | [O] DataFrame | inspection: one row per leg flow with ISO dates |

ZeroCouponBond (`instruments/bonds/zerocouponbond.py:69-97`):
- calendar = `bond_calendar()`;
- redemption date = `dates.adjust(cal, maturity, payment_convention)`;
- one Redemption of `face*redemption/100.0`;
- no coupons;
- notional schedule `([0, pay], [face, 0.0])`.

### 4.5 `Legs` (singleton). The portfolio leg in CSR form

References: `data`, `lib`, `dates`, `bond` (Interface → Bond).

- `leg_columns()` [O] → dict of numpy arrays. It is built in one loop over `bond[b]` for `b` in `range(data.n_bonds())`. The global flow index is `p`. Columns:
  - `cf_lo` (int64 [N+1])
  - `cf_owner`, `cf_date`, `cf_kind`, `cf_coupon_idx`, `cf_acc_start`, `cf_acc_end`, `cf_ref_start`, `cf_ref_end`, `cf_dc` (int64 [P])
  - `cf_amount`, `cf_nominal`, `cf_rate` (float64 [P])
  - `ns_lo` (int64 [N+1]), `ns_date` (int64), `ns_notional` (float64)
  - `bk_cal`, `bk_settle_days`, `bk_issue`, `bk_maturity`, `bk_type`, `bk_spread_idx`, `bk_ydc`, `bk_ycomp`, `bk_yfreq` (int64 [N])
  - `bk_face` (float64 [N])
- One [O] array Cells per column, named `<column>_arr()`, e.g. `cf_date_arr()`, which returns `leg_columns()["cf_date"]`.
- `n_flows()` [S] → int.
- `cashflow_frame()` [O] DataFrame. This is the **Goal 1 output**: `bond_key`, `flow` (index within bond), `kind` ('coupon' / 'amortizing' / 'redemption'), `date` (ISO), `amount`, `nominal`, `rate`, `accrual_start`, `accrual_end`, `ref_start`, `ref_end`, `accrual_period`.
- `check_limits()` [S] → bool: N ≤ MAX_BONDS, P ≤ MAX_FLOWS, and so on.

### 4.6 `Proj` (singleton). Projection buckets

References: `data`, `lib`, `dates`, `legs`.

- `bucket_arr()` [O] int64 [P]. For each flow p, `per` = the first t in 0..T-1 at which `lib.has_occurred(cf_date, v_t, engine_inc, v_t, T, R)` is True, or T if it never is. `engine_inc` = F if F != -1 else R. Bucket 0 holds flows already occurred at v_0.
- `bucket_sums()` [O] float64 [T+1, 3]. Columns are coupon / amortizing / redemption. It is built in one pass over p in global order with `+=`.
- `coupon_cf(per)`, `amortization_cf(per)`, `redemption_cf(per)`, `total_cf(per)` [C] → float.
- `period_start(per)`, `period_end(per)` [C] → int.
- `bond_cf_table()` [O] DataFrame in long format: (bond_key, per, coupon, amortization, redemption).

### 4.7 `Valuation[scen_id, t]` (ItemSpace; Phase 2 core, Phase 4 analytics)

`_formula = lambda scen_id, t: None`. References: `scen_id = 1`, `t = 0`, `data`, `lib`, `dates`, `legs`, `proj`.

One item is **one valuation date `v = val_date[t]` under scenario `scen_id`**. It stands in for QuantLib's `Settings.evaluationDate = v` plus the curve, quotes and engines at that date. Every date is explicit, and there is no global state.

Every bond quantity is a Cells over the **bond index `b`**. It reads the portfolio leg from `legs.*_arr()` (CSR form: the flows of `b` are `p` in `[legs.cf_lo_arr()[b], legs.cf_lo_arr()[b+1])`, in leg order).

**Parameter domains** (they matter for mx2cy sizes):

| Parameter | Meaning |
|---|---|
| `b` | bond |
| `role` | 0..2 |
| `kind` | 0..1 |
| `kd` | day offset `d - vdate()` ≥ 0 |
| `nd` | curve node |
| `p` | global flow |
| `(cal, nsd)` | calendar, settlement days |
| `x`, `y`, `z` | floats |

Never pass a date serial as a Valuation parameter.

#### Context [S]

| Cells | Returns | Meaning |
|---|---|---|
| `vdate()` | int | `data.val_date_arr()[t]`. Replaces `Settings.evaluationDate`. It is also the curve's reference date. |
| `srow()` | int | `scen_id - 1` (the row of the [S, T] arrays) |
| `curve_type()`, `curve_dc()`, `curve_comp()`, `curve_freq()`, `spread_comp()`, `spread_freq()`, `node_lo()`, `n_nodes()` | int | the (scen, t) inputs |
| `curve_extrapolate()` | bool | the (scen, t) input |
| `flat_rate()` | float | the (scen, t) input |
| `engine_flag()` | int 0/1 | `F if F != -1 else R`, where F = `data.engine_include_settlement_flows` and R = `data.include_reference_date_events` (`discountingbondengine.py:144-148`) |
| `todays()` | int | T = `data.include_todays_cashflows` (tri-state) |
| `ref_events()` | int | R |
| `max_time()` | float | ZeroCurve: `node_time(n_nodes()-1)`. FlatForward: `dates.year_fraction(curve_dc(), vdate(), MAX_SERIAL, 0, 0)` |
| `curve_ok()` | bool | validation; raises unless the curve inputs are usable (≥ 2 nodes for ZeroCurve; node 0 == `vdate()`; strictly increasing node times; valid InterestRate conventions) |

#### Curve nodes (ZeroCurve) [C over `nd`]

| Cells | Returns | Transcribes |
|---|---|---|
| `node_date(nd)`, `node_rate_in(nd)` | int / float | the inputs |
| `node_time(nd)` | float | `setupTimes`: `year_fraction(curve_dc, vdate, node_date(nd))` |
| `node_zc(nd)` | float | the continuous zero rate after `ZeroCurve._initialize` (`termstructures/yield_/zerocurve.py:541-582`): converted **only if** `curve_comp() != COMP_CONTINUOUS`, node 0 over `dt = 1.0/365`, the others over `node_time(nd)`, with exactly the pureql call chain |
| `node_slope(nd)` | float | `LinearInterpolationImpl.update` (`math/interpolations/linearinterpolation.py:145-171`) for `nd` in 0..n-2 |

#### Curve by day offset [C over `kd`]; `kd = d - vdate()`, shared by all bonds of the item

| Cells | Returns | Transcribes |
|---|---|---|
| `curve_time(kd)` | float | `timeFromReference` |
| `range_ok(kd)` | bool | `checkRange(t, extrapolate)` (`termstructure.py:387-401`); raises pureql's messages |
| `zero_c(kd)` | float | ZeroCurve `zeroYieldImpl` (`zerocurve.py:519-539`): `locate`, linear value, flat-forward extrapolation |
| `discount_core(kd)` | float | ZeroYieldStructure `discountImpl` (`exp(-r t)`, `t == 0 → 1.0`) or FlatForward `discountImpl` (`lib.discount_factor`) |
| `discount(kd)` | float | `YieldTermStructure.discount(date)`: `range_ok` then `discount_core` |
| `zs_base(kd)` | float | `original.zeroRate(t, spread_comp, spread_freq, True).rate()` for `t = curve_time(kd) > 0` (`yieldtermstructure.py:520-535`) |
| `zs_discount_kd(kd, z)` [U] | float | the canonical ZeroSpreadedTermStructure discount (`zerospreadedtermstructure.py:238-261` + `zeroyieldstructure.py:139-153`): range check; `t == 0 → 1.0`; `zs_base(kd) + z` → `lib.equivalent_rate(..., COMP_CONTINUOUS, FREQ_NO_FREQUENCY)` → `exp(-rc*t)`. **No algebraic shortcut.** |
| `zdisc(p)` [C over `p`] | float | `zs_discount_kd(cf_date[p] - vdate(), spread(owner of p))` |

#### Per bond [C over `b` / `(b, role)` / `(cal, nsd)`]

| Cells | Returns | Transcribes |
|---|---|---|
| `settle_cal(cal, nsd)` | int | `dates.advance(cal, vdate(), nsd, TU_DAYS, BDC_FOLLOWING, 0)` |
| `settle(b)` | int | `Bond.settlementDate(v)` (`instruments/bond.py:755-786`): `settle_cal(bk_cal, bk_settle_days)`, then `max(..., issue)` when issue is set |
| `notional_s(b)` | float | `Bond.notional(settle(b))` (`bond.py:629-686`), with the `ns_*` CSR |
| `is_tradable(b)` | bool | `notional_s(b) != 0.0` |
| `first_live(b, role)` | int | the first `p` of bond `b` with `not lib.has_occurred(cf_date[p], ref, inc, vdate(), todays(), ref_events())`, or the end of the bond's range. ENGINE (0): `ref = vdate()`, `inc = engine_flag()`. SETTLE (1): `ref = settle(b)`, `inc = 0`. EXPIRY (2): `ref = vdate()`, `inc = -1`. The occurred flows form a prefix of the stable-sorted leg, so a binary search is allowed when it returns the same index |
| `is_expired(b)` | bool | `first_live(b, ROLE_EXPIRY)` is past the end (`Bond.isExpired`, `cashflows.py:751-781`) |
| `has_spread(b)` | bool | `bk_spread_idx[b] >= 0` |
| `spread(b)` | float | `float(data.sp_arr()[srow(), t, idx])` |
| `pv_base(b, role)` | float | `CashFlows._npv_curve` (`cashflows/cashflows.py:1234-1283`) on the plain curve with `(includeFlag, settlementDate, npvDate)` per role (ENGINE: `(engine_flag, vdate, vdate)`; SETTLE: `(False, settle, settle)`); sequential `+=` of `amount*discount(kd)` over the live flows (ex-coupon skip kept); final `lib.cxx_div(total, discount(kd_npv))` |
| `zdisc_npv(b, role)` | float | the ZeroSpreaded discount at the role's npvDate |
| `pv_sprd(b, role)` | float | the same loop on `zdisc(p)`, divided by `zdisc_npv(b, role)` |
| `npv(b)` | float | `0.0` if `is_expired(b)` (Instrument expiry short-circuit); else the DiscountingBondEngine NPV: `pv_sprd(b, ROLE_ENGINE)` if `has_spread(b)`, else `pv_base(b, ROLE_ENGINE)` (`discountingbondengine.py:113-171`) |
| `npv_base(b)` | float | the plain-curve engine NPV, even for spread bonds (diagnostic) |
| `settlement_value(b)` | float | 0.0 if expired; `npv(b)` if `engine_flag() == 0` and `vdate() == settle(b)`; else the SETTLE-role value on the same curve |
| `accrued_cash(b)` | float | `CashFlows.accruedAmount(leg, False, s)` (`cashflows.py:1099-1133`): every coupon paid on the payment date of `first_live(b, ROLE_SETTLE)` adds `lib.coupon_accrued_amount(..., s)`, by sequential `+=` |
| `accrued_amount(b)` | float | `Bond.accruedAmount(s)` (`bond.py:1115-1137`, `bondfunctions.py:494-518`): 0.0 if N == 0, else `accrued_cash(b)*100.0/notional_s(b)` |
| `dirty_price(b)` | float | `Bond.dirtyPrice()` (`bond.py:894-911`): 0.0 if N == 0, else `settlement_value(b)*100.0/N` |
| `clean_price(b)` | float | `dirty_price(b) - accrued_amount(b)` (`bond.py:822-833`) |
| `market_value(b)` | float | `npv(b)` (DECISIONS.md D-4) |

#### Prices from a z-spread [D] (BondFunctions, explicit settlement date `s = settle(b)`)

| Cells | Returns | Transcribes |
|---|---|---|
| `pv_z(b, z)` | float | `CashFlows.npv(leg, ZeroSpreaded(curve, z, spread_comp, spread_freq), False, s, s)` (`cashflows.py:1376-1453`), using `zs_discount_kd(kd, z)` |
| `dirty_from_z(b, z)` | float | `BondFunctions.dirtyPrice(bond, curve, z, ..., s)` (`bondfunctions.py:816-858`): `pv_z*100.0/N` |
| `clean_from_z(b, z)` | float | `BondFunctions.cleanPrice(bond, curve, z, ..., s)` (`bondfunctions.py:649-681`): `dirty_from_z - accrued_amount(b)` |

**NT policy.** When N == 0, under `NT_ENGINE` (the default) the `*_from_z` Cells return 0.0; under `NT_RAISE` they raise pureql's "non tradable" message.

#### Aggregates [S] and outputs

- `npv_total()`, `mv_total()`, `sv_total()`, `accrued_total()`: sequential sums in bond order.
- `n_expired()`, `n_tradable()`.
- `result_frame()` [O]: one row per bond, with `bond_key`, `settlement_date` (ISO), `notional`, `npv`, `settlement_value`, `dirty_price`, `clean_price`, `accrued_amount`, `market_value`, `tradable`, `expired`.

#### Lib addition (Phase 2)

`coupon_accrued_amount(nominal, rate, comp, freq, dc, acc_start, acc_end, ref_start, ref_end, pay, ex_date, d)` [U] transcribes `FixedRateCoupon.accruedAmount(d)` (`cashflows/fixedratecoupon.py:294-317`), including the ex-coupon branch. Legs may gain `cf_comp` and `cf_freq` columns to feed it.

#### Phase 4: see section 4.8.

### 4.8 Phase 4 analytics (Valuation, Data, Lib additions)

**Data: sparse quote inputs** [O]. The arrays are sparse because quotes usually exist only at a few (scen, t), and a dense [S, T, N] array would not fit.
- `px_slot_arr()` int64 [S, T]: the price slot of (scen, t), or -1 if there is none.
- `px_val_arr()` float64 [NPS, N]: NaN where there is no price.
- `px_type_arr()` int64 [NPS, N]: `PRICE_CLEAN`/`PRICE_DIRTY`, -1 where there is no price.
- `yl_slot_arr()` int64 [S, T] and `yl_val_arr()` float64 [NYS, N]: the same for yields.

These come from `prices.csv` (scen_id, t, bond_key, price, price_type) and `yields.csv` (scen_id, t, bond_key, yield).

**Lib** [U]:
- `stepwise_time(is_coupon, d, acc_start, ref_start, ref_end, dc, npv_date, last_date)` transcribes `_getStepwiseDiscountTime` (`cashflows/cashflows.py:327-378`), all three branches. A non-coupon with `last_date == npv_date` uses `dates.advance_date(d, -1, TU_YEARS)` as the reference start.
- `sign(x)` transcribes `cashflows.py` `_sign`.

**Valuation, per bond inputs** [C over `b`]:
- `price_in(b)` float, NaN if absent; `price_type_in(b)` int, -1 if absent; `yield_in(b)` float, NaN if absent.
- `ydc(b)`, `ycomp(b)`, `yfreq(b)` int: from `legs.bk_ydc/ycomp/yfreq`.

**Stepwise time** [C over `p`]: `ystep(p)`, the step time of a LIVE (SETTLE-role) flow `p`.
- It calls `lib.stepwise_time` with `npv_date = settle(owner)`.
- `last_date` is `settle(owner)` for the owner's first live flow, else `cf_date[p-1]`. This reproduces pureql's running `lastDate`, including when the previous live flow is dated on `npvDate`.
- The dc is `ydc(owner)`. The value does not depend on the yield.

**Yield family** [D over `(b, y)`]. `y` is a float. The rate is `InterestRate(y, ydc(b), ycomp(b), yfreq(b))`. Every Cells uses `(includeSettlementDateFlows = False, settlementDate = npvDate = settle(b))`.

| Cells | Transcribes |
|---|---|
| `npv_yield(b, y)` | `CashFlows._npv_interestRate` (`cashflows.py:1285-1353`): a running product of one-step factors; ex-coupon flows are zeroed but still step (QUIRK Q-09) |
| `simple_duration_y`, `modified_duration_y`, `macaulay_duration_y`, `convexity_y` | `cashflows.py:381-546` and convexity (`:2196-2285`), on ACCUMULATED time `tt += ystep(p)` (Q-09) |
| `bpv_y(b, y)`, `yvbp_y(b, y)` | `basisPointValue` / `yieldValueBasisPoint` (`cashflows.py:2343-2518`): the stepwise npv combined with the accumulated duration and convexity, in upstream order |
| `dirty_from_yield(b, y)`, `clean_from_yield(b, y)` | `BondFunctions` dirty/clean price at an InterestRate (`bondfunctions.py:613-632`, `:773-799`) |

**Targets and solvers** [C].

| Cells | Meaning |
|---|---|
| `y_price(b)`, `y_price_type(b)` | the input price if present, else `(clean_price(b), PRICE_CLEAN)`, as `Bond.bondYield` uses the engine clean price |
| `y_target(b)` | `BondFunctions.bondYield` target (`bondfunctions.py:1149-1162`): `A = price (+ accrued_amount(b) if Clean); A /= 100.0/N` |
| `sign_ok(b)` | `IrrFinder.checkSign` (`cashflows.py:675-701`) over the live, non-ex-coupon flows |
| `z_target(b)` | `bondfunctions.py:1518-1528` |
| `solve(b, kind)` | **one formula**. Solver1D bracketing (`math/solver1d.py:192-254`), then `Brent.solveImpl` (`math/solvers1d/brent.py:80-157`) or `NewtonSafe.solveImpl` (`newtonsafe.py:112-168`) as `kind` and `data.yield_solver` say. The objectives are inlined: YIELD is `IrrFinder` `npv_yield(b, x) - y_target(b)`, with derivative v1.43 `-modified_duration_y(b, x) * npv_yield(b, x)` (`cashflows.py:754-769`). ZSPREAD is `z_target(b) - pv_z(b, x)` (`cashflows.py:2581-2615`). Accuracy, max evaluations and guess come from the Data refs; the step is `guess/10` for yield and `ZSPREAD_STEP` for z. Locals are doubles and the evaluation counter is a double |
| `ytm(b)` | gates, then `sign_ok`, then `solve(b, SOLVE_YIELD)` (`bondfunctions.py:1083-1176`) |
| `zspread(b)` | an input price (or, with `zspread_price_source = 1`, the engine clean price) is required, else NaN; the NT gate; then `solve(b, SOLVE_ZSPREAD)` (`bondfunctions.py:1470-1542`) |
| `risk_yield(b)` | `yield_in(b)` if present, else `ytm(b)` |
| `duration_simple(b)`, `duration_modified(b)`, `duration_macaulay(b)`, `convexity(b)`, `bpv(b)`, `yvbp(b)` | at `risk_yield(b)`, not rescaled (`bondfunctions.py:1213-1467`) |
| `dirty_at_yield_in(b)`, `clean_at_yield_in(b)` | the prices at the input yield |

**Policies.**
- **NT (N == 0).** Under `NT_ENGINE`: ytm, zspread, risk_yield and the risk measures are NaN, and prices from a yield are 0.0. Under `NT_RAISE`: pureql's raise.
- **ERR (solver failure: no bracket, max evaluations, checkSign).** Under `ERR_RAISE`: pureql's message. Under `ERR_NAN`: NaN.
- **Macaulay duration with a non-Compounded yield.** NaN under `ERR_NAN`, raise under `ERR_RAISE`. It is gated before the [D] call.

**Outputs.** `result_frame()` gains columns by `data.output_level`:
- 2: `ytm`, `risk_yield`, `duration_simple/modified/macaulay`, `convexity`, `bpv`, `yvbp`;
- 3: adds `zspread`.

`run.py` passes them through.

**Tool.** `tools/calibrate_spreads.py` solves `zspread(b)` with the MODEL at t = 0 from `prices.csv`, then writes an input-set copy whose `spreads.csv` carries those spreads for every (scen, t), with `spread_id = bond_key`.

## 5. Tests (`tests/`)

- **pureql reference.** `tests/helpers/pureql_ref.py` imports pureql and provides:
  - code → object maps: `pq_calendar(code)`, `pq_daycounter(code)`, `pq_bdc(code)`, `pq_comp(code)`, `pq_freq(code)`;
  - `pq_date(serial)` and `serial(pq_date)`;
  - `pq_bond(row)`, which builds a FixedRateBond or ZeroCouponBond from a parsed bonds.csv row.
- **Model access.** `tests/helpers/model.py` provides:
  - `load_model()`, which reads `bond_portfolio/BondPortfolio` once per session;
  - `with_inputs(model, dir)`, which sets `Data.input_dir`.
- **Unit tests** compare Cells with pureql using `==`, with no tolerance.
- **Oracle tests** use QuantLib 1.41, are marked `oracle`, and restore Settings.


## 6. As built (Phase 1): additions and deviations

- **Lib.**
  - `long_date(d)` gives pureql's `str(Date)` text, used in error messages.
  - `implied_rate_dates` and `equivalent_rate_dates` are the date forms.
  - `compound_factor` runs `check_rate` first.
- **Dates.**
  - The tables cite the anchor of the C++ function that holds them.
  - `nth_weekday` is not implemented (no v1 calendar needs it).
  - Unsupported calendar and day-counter codes raise "... not supported in this model version".
- **Data.**
  - Plumbing Cells: `read_table`, `code_of(kind, s)` (integer kinds only), `float_of(s)`, `parse_error`, the `*_columns` dict sources and the `*_errors` validators.
  - Defaults are documented in `bond_portfolio/inputs.md`.
  - `prices.csv` and `yields.csv` are validated but have no array Cells yet (Phase 4).
- **Bond.**
  - `calendar()` gives the bond calendar.
  - A null effective date raises "null effective date".
  - A ZeroCouponBond's `schedule()` is the empty-schedule record.
  - The coupon record `freq` is the rate's `frequency()`, i.e. -1 for Simple rates.
- **Legs.**
  - The extra column is `cf_accrual_period`.
  - `iso_column(name)` returns a list.
  - Redemption rows carry NaN nominal, rate and accrual period.
- **Proj.**
  - `engine_include()` and `period_table()`.
  - `period_start(0) = 0` and `period_end(T) = MAX_SERIAL`.

### Phase 2 (Valuation core)

- **Legs.** Besides the permitted `cf_comp` and `cf_freq` (the coupon InterestRate's compounding and `frequency()`, -1 for a redemption), `cf_ex_date` (the coupon's ex-coupon date; 0 for every v1 flow) feeds the ex-coupon skip and `lib.coupon_accrued_amount`.
- **Valuation, extra Cells.**
  - `ref_date(b, role)` [C]: the settlement and npv date of a role: `settle(b)` for SETTLE, else `vdate()`.
  - `node_locate(x)` [D]: `Interpolation.locate` (`ql/interpolation.hpp:104-115`), used for the interpolated value and for the slope at the last node.
- **Valuation, behaviour the contract left open.**
  - `spread(b)` is 0.0 for a bond without a spread (the 4.7 formula would read index -1, the last spread column).
  - `zs_base(kd)` raises at `t == 0`. It is reached only after the `t == 0` guard of `zs_discount_kd`; upstream's `t = dt` branch has no day offset.
  - `curve_ok()` runs from `curve_time(kd)` and `max_time()`, so bad curve inputs raise on first use rather than at construction. It adds three model-only checks: at most `MAX_NODES` nodes, node 0 on `vdate()`, strictly increasing node times. Outputs that need no curve are still produced when the curve cannot be built: an expired bond's NPV and settlement value, and a non-tradable bond's dirty and clean prices (all 0.0). pureql gives the same 0.0 values when the engine's curve handle is empty.
  - ZeroSpreaded: the spreaded InterestRate is built with `spread_freq()` instead of `zeroRate.frequency()`. The two differ only for Simple and Continuous, which never read the frequency.
  - `accrued_total()` sums `accrued_cash(b)` (currency), like the other three totals. A non-tradable bond can add to it while its `accrued_amount` is 0.0.
  - `npv_base(b)` is 0.0 for an expired bond: `Instrument::NPV()` with the engine on the plain curve.
  - `engine_flag()` delegates to `proj.engine_include()`, so there is one copy.
  - `pv_base` and `pv_sprd` raise for `ROLE_EXPIRY`.
  - NT policy: under `NT_RAISE` only `dirty_from_z` and `clean_from_z` raise. `dirty_price`, `clean_price` and `accrued_amount` stay 0.0, as pureql's `Bond` methods do.
- **Limits.** (Superseded in Phase 3, below.) `Legs.check_limits()` did not bound the day offset `kd` by `MAX_KD` (40000 days). In compiled mode a flow more than `MAX_KD` days after a valuation date raises `IndexError`; the Phase 3 driver must refuse such inputs.
- **Tests.** `tests/helpers/pureql_val.py` is the pureql oracle of 4.7, in two forms (Settings moved; explicit dates) checked against each other. `tests/data/pv_demo.json` and `pv_coverage.json` are its frozen values; regenerate them with `pureql_val.write_golden(model, input_dir, path, label)` when the demo or coverage CSVs change.

### Phase 3 (future t, driver)

- **Valuation.** No new formulas, as planned: an item at any `t` is pureql with the evaluation date moved to `vdate()`. The one change: `curve_ok()` takes the day-counter name of its "same time" message from `dates.daycounter_name(dc)` instead of its own copy of the names.
- **Dates.** `daycounter_name(dc)` [U] → str: `DayCounter.name()` of a v1 day-counter code, i.e. pureql's `str(dayCounter)` (`actual360.hpp:45-49`, `actual365fixed.hpp:54`, `thirty360.hpp:99/104/109`; transcribed, with provenance). A code outside v1 gives `'day counter <dc>'`. It is the one copy of the names, used by the error messages of `Data.node_errors()` and `Valuation.curve_ok()`.
- **Data.**
  - New Reference `lib` (Interface → Lib), for `lib.close` and `lib.long_date` in `node_errors()`.
  - `node_errors()` now transcribes the two guards of `InterpolatedCurve.setupTimes` (`interpolatedcurve.hpp:100-115`) and carries the provenance comment and docstring line: a ZeroCurve whose node dates map to `close` or non-increasing times under the curve's day counter is rejected by `check_inputs()` with pureql's message ("two passed dates (...) correspond to the same time under this curve's day count convention (...)"). `check_inputs()` therefore refuses every ZeroCurve that `Valuation.curve_ok()` refuses, before any valuation. The guards exist in both places on purpose: `node_errors()` validates the whole input table up front, while `curve_ok()` guards an item used without `check_inputs()`.
  - Data is now a derived Space; NOTICE.md (`tools/make_notice.py`) lists it, and `tests/lint/test_notice.py` checks that every Space carrying the provenance comment is listed.
- **Legs.** `check_limits()` also checks T ≤ `MAX_T`, S ≤ `MAX_SCEN`, at most `MAX_NODES` nodes per ZeroCurve, and the day offset: the latest flow or issue date minus the earliest valuation date must be below `MAX_KD`. It lists every excess in one `ValueError` headed "the inputs exceed the model limits (n problem(s))". This replaces the Phase 2 "Limits" note: inputs that `check_limits()` accepts never index past a compiled size (`tests/future/test_driver.py` checks the `kd` bound against every offset the Valuation items use).
- **Driver** (`bond_portfolio/run.py`, plan Phase 3).
  - Modes `modelx | export | compiled`; `--scen` / `--times` select a subset of the (scen_id, t) grid.
  - It runs `check_inputs()` and `check_limits()`, then measures the inputs against `<build>/sizes.json` (written by `tools/build_cy.py`; required in compiled mode) and refuses any excess before writing anything.
  - Export and compiled mode: it deletes the `Bond` items once `Legs` is built, then calls `gc.collect()` and, after the cash-flow outputs, `gc.freeze()`.
  - **Addition to the plan: a curve pre-flight.** Before valuing anything it runs `curve_ok()` and `range_ok(kd)` at the portfolio's latest flow date for every (scen_id, t) of the run, and lists every item that would fail. It reports only certain failures; a range error at a settlement date past the last node is still raised during the valuation, with its (scen_id, t).
  - Valuation is scenario-major with one item alive: `del` plus `gc.collect()` after each item. Outputs: `cashflows.csv`, `period_cashflows.csv`, `valuation_scen<k>.csv`, `valuation_totals.csv`, `run_summary.json`.
  - `tools/bench.py` times the modes and writes `docs/performance.md`.
- **Tests.**
  - `tests/future`: the 2020 goldens, the edge grid, the fuzz, the identities, QuantLib 1.41 (`oracle`), and the driver.
  - `tests/perf/test_memory.py`: one live `Valuation` item at a time.
  - `tests/modes/test_modes_future.py`: the compile gate (`compiled == export == modelx`) on the Phase 3 corpus, i.e. the edge grid under several flag sets, the 2020 inputs and the fuzz portfolios.
- **Phase 3 exit, as met.**
  - **T-override.** The exploration's bond for "dirty 98.0607 → 100.3107" could not be recovered. The T-override jump is shown instead on a T+0 4.5% semiannual Thirty360 bond with a coupon on `v` (`T0_CPN_ON_V`, `tests/data/future_edges.json`). Its dirty price jumps by the 2.25 coupon and so does its accrued amount, so the clean price does not move; pureql and QuantLib 1.41 agree.
  - **2020 goldens.** The flat-curve literals (NPV `102.13530449214969`, dirty `102.18428521477128`, clean `102.11761854810462`) are reproduced exactly. The exploration's ZeroCurve conventions were not recoverable, so the zero-curve goldens use Actual365Fixed / Continuous, with values measured here. pureql in both forms, a README-style rebuild and QuantLib 1.41 agree on them (`tests/data/future_headline_2020.json`).
  - **Roll-forward.** The identity holds (T2) when the engine flag F is unset or equals R. With F set and different from R, a bond whose last flow falls on a valuation date breaks it by exactly that flow: `isExpired` uses R while the engine uses F. The model == pureql there; `test_roll_forward_breaks_when_f_differs_from_r` pins it.
  - **Speed.** Compiled core PV is 20.9 µs per bond-point, against the plan's 2–8 µs estimate (`docs/performance.md`); plan Phase 5 addresses the gap (docs/mx2cy-issues.md #1–#3).

### Phase 4 (analytics)

- **Data.**
  - `quote_columns()` [O] is the dict source of the five 4.8 quote arrays. Slots are numbered in (scen_id, t) order over the cells that have at least one quote. A blank `price_type` is Clean. Rows outside the curve_params grid or naming an unknown bond are left out of the arrays; `quote_errors()` (already in `check_inputs()`) reports them.
- **Lib.** `sign(x)` and `stepwise_time(...)` are as contracted. In `stepwise_time`, the non-coupon `d - 1Y` reference start is `dates.advance_date(d, -1, TU_YEARS)`.
- **Valuation, extra Cells.**
  - `nt_ok(b)` [C] is the one tradability guard of every BondFunctions member the model transcribes: the prices from a z-spread or a yield, `y_target`, `z_target`, `ytm`, `zspread`, `risk_yield` and the six risk measures. It returns True if `notional_s(b) != 0.0`. Otherwise it returns False under `NT_ENGINE` and raises pureql's "non tradable at ... (maturity being ...)" under `NT_RAISE`. `dirty_from_z` now uses it, with unchanged behaviour.
  - `z_price(b)` and `z_price_type(b)` [C] mirror `y_price` / `y_price_type` for the z-spread: the input price; else, with `zspread_price_source = 1`, the engine clean price (`PRICE_CLEAN`); else NaN / -1.
- **Valuation, behaviour the contract left open.**
  - **Yield solver codes.** `yield_solver` 0 is NewtonSafe, the default and `BondFunctions.bondYield`'s solver. 1 is Brent, the option comparable with QuantLib 1.41's `yieldBrent`. Any other value raises "unknown yield solver ...". The z-spread always uses Brent, as `CashFlows.zSpread` does.
  - **No price.** `zspread(b)` is NaN when `z_price(b)` is NaN. This is decided before the NT gate, so a non-tradable bond with no price is NaN even under `NT_RAISE`. `y_target` and `z_target` are NaN for a missing price and for a non-tradable bond under `NT_ENGINE`. `solve(b, kind)` returns NaN at once for a NaN target; `ytm` and `zspread` gate those cases before calling it.
  - **InterestRate guard.** Every `(b, y)` Cells first calls `lib.check_rate(ycomp(b), yfreq(b))`, because pureql builds the `InterestRate` before the call.
  - **Scope of the ERR policy.** `ERR_NAN` covers exactly the three solver failures (no bracket, maximum evaluations, `checkSign`) and the Macaulay gate. Every other error stays raised under either policy:
    - a non-positive accuracy;
    - an error inside an objective, e.g. "positive compound factor required" from the z-spread objective's ZeroSpreaded rate;
    - a curve error that reaches a target through the engine price.
  - **`risk_yield`** follows the NT policy even when an input yield exists, as the 4.8 NT row lists it among the NaN outputs.
  - **Gating.** `dirty_at_yield_in` / `clean_at_yield_in` are NaN without an input yield. The `(b, y)` CashFlows Cells (`npv_yield`, the durations, `convexity_y`, `bpv_y`, `yvbp_y`) carry no NT gate, because the pureql functions they transcribe have none. `dirty_from_yield` / `clean_from_yield` carry it (BondFunctions). Called directly on a yield that is not Compounded, `macaulay_duration_y` raises "compounded rate required"; the ERR policy is applied by the bond-level `duration_macaulay` gate.
  - **Solver.** `enforceBounds` is left out because no caller sets bounds. Upstream's final `f(root)` call is kept as a call of the cached [D] Cells. The evaluation counter is a double compared with `float(max evaluations)`; the messages print the integer.
  - **Renamed locals.** pureql's `npv`, `discount`, `convexity`, `b` and `t` clash with Cells or Space-parameter names. They are renamed `npvSum` / `npvy`, `discountProduct`, `cvx`, `bf` and `tt`.
- **Outputs.** `result_frame()` adds the 4.8 columns at `output_level` 2 and 3. Under the default `ERR_RAISE`, level 2 or 3 raises at the first bond whose yield is not Compounded, at its Macaulay duration (on the demo inputs: `US_1M_A365F_SIMPLEYLD`). That is the contract's policy. Runs over such inputs use `ERR_NAN`.
- **Driver.**
  - `run.py` gains `--output-level 1|2|3` (`Data.output_level`, default 1) and `--solver-errors raise|nan` (`Data.solver_error_policy`; the default keeps the model's `ERR_RAISE`).
  - On a `ValueError` at level ≥ 2 without `--solver-errors`, it prints a hint naming `--solver-errors nan`.
  - `run_summary.json` records both settings.
  - `tools/bench.py` passes `--output-level` / `--solver-errors` through.
- **Tool.** `tools/calibrate_spreads.py` (runs in any of the three modes):
  - **Solve.** Without `--scen`, each scenario is calibrated at its own t = 0, and a bond priced at t = 0 in only some scenarios is refused. `--scen K` gives the spreads solved at (K, 0) to every scenario. A bond that is not tradable at t = 0 is left uncalibrated, with a note. A failed solve stops the tool (`ERR_RAISE`) with the bond's key.
  - **Write.** The spreads are written with `repr`. Each calibrated bond gets `spread_id = bond_key`, and earlier rows of that spread_id are replaced. A calibrated `bond_key` that is already another bond's spread_id is refused.
  - **Check.** A fresh model on the output checks two things: the spread reads back exactly, and the engine clean price equals `clean_from_z` bit for bit. The largest gap to the quote is printed (7.5e-10 on the demo inputs: the solver accuracy).
  - **Caveat.** The solved number is fed to every t as it is. If the spread conventions of a later (scen_id, t) differ, the same number means a different curve there.
- **Build.**
  - `SPEC_MAP` gains `(b, kind)`. `tools/cy/sample.py` traces the analytics with `ERR_NAN` and `output_level` 3, and calls `macaulay_duration_y` on Compounded yields only, so nothing raises during the trace. Every new cached Cells comes out of mx2cy with C types (the pxd audit passes).
  - MSVC warns C4048 twice in Cython's generated unpickle code. It is harmless (docs/mx2cy-issues.md #9).
- **Tests.**
  - `tests/pv/test_analytics_smoke.py` (implementer) compares every bond at every (scen_id, t) of the demo and coverage inputs with pureql bit for bit: the yield family, both solvers, the z-spread, the risk measures, the policies, `result_frame` levels and the calibration tool.
  - `tests/analytics/` (independent author) covers the Phase 4 exit:
    - t = 0 and future t, the five yield compoundings, the Phase 3 edge grid (`slow`), round trips, monotonicity and the Q-09 pins;
    - QuantLib 1.41 (`oracle`), with goldens `tests/data/analytics_{demo,coverage,pins}.json` (regenerate with `pureql_val.write_analytics_golden` / `write_analytics_pins`);
    - `tests/helpers/pureql_val.py` gains the pureql reference `pq_analytics`.
  - `tests/modes/test_modes.py` adds the probe set `coverage_analytics`: level 3, `ERR_NAN`, Brent yields, and z-spreads from the engine price. The solving Cells and the `(b, y)` / `(b, kind)` Cells are probed on the first 24 bonds of each item, which keeps the 600-bond fuzz portfolios of `test_modes_future.py` affordable in modelx mode. The demo and coverage sets have fewer than 24 bonds, so they are probed in full.
- **Phase 4 exit, as met.**
  - **Headline yield.** `0.030250400779423203` is reproduced exactly (`yield_accuracy = 1e-8`, engine clean price), equal to pureql's `Bond.bondYield`.
  - **zcb-10y.** The QuantLib 1.41 goldens (Brent yield, z-spread, the three durations, convexity, BPV, YVBP, price from the z-spread) hold at their recorded tiers.
  - **z round trip.** z → P → z holds within 1e-11 over `Z_GRID` × 4 conventions × 2 curve types, from clean and dirty prices, at t = 0 and a future t. Each solved z is also == pureql. The fourth upstream convention, ActualActual.ISDA, is outside v1; Thirty360.USA with Simple / Annual stands in.
  - **y round trip.** y → P → y holds within 1e-11 with NewtonSafe and Brent under all five compoundings.
  - **Q-09 pins** hold bit for bit: the stepwise and accumulated-time schemes are both kept.
  - **== pureql.** Every output equals pureql bit for bit.
  - **Compile gate.** It passes: `compiled == export == modelx` on the Phase 1–4 corpus.
  - **QuantLib 1.41.**
    - The z-spread matches at T2.
    - The Brent yield matches `yieldBrent` at T2.
    - The NewtonSafe yield is checked through 1.41's pricer at the model's yield, at T2 (OS-10).
  - **Speed** (compiled, `docs/performance.md`).
    - Level 1 is unchanged: 21.1 µs per bond-point on the Phase 3 profile.
    - Level 2 costs about 200 µs per bond-point at 10,000 bonds, about 8.4 min for the full 10k × 121 × 2 grid. That is within the plan's 6–10 min.
