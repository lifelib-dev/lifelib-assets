# BondPortfolio technical notes: valuation at future dates

These notes explain, for a user of the model, what `Valuation[scen_id, t]`
computes at a valuation date `t` other than "today", which cash flows each
figure includes, and the policies the model applies where QuantLib leaves a
choice. The model's inputs are described in [inputs.md](inputs.md); its
Spaces, outputs and run modes in [model.md](model.md).

Every formula of the model is a transcription of
[quantlib-migration](https://github.com/lifelib-dev/quantlib-migration)'s
`pureql`, a pure-Python port of QuantLib v1.43. Below, "pureql `x.py`" is a
file under `quantlib-migration/src/pureql/` and `x.cpp:a-b` the QuantLib
v1.43 source lines it ports (the same anchors as the `# ported from` comments
in the model).

## 1. One valuation item = QuantLib with the evaluation date moved to v_t

QuantLib and pureql price at "today", `Settings.evaluationDate`. The model
has no global settings: one item `Valuation[scen_id, t]` is QuantLib with

- the evaluation date set to `v_t = val_date[t]` (`Valuation.vdate()`),
- the discount curve, spreads and conventions of row `(scen_id, t)` of the
  inputs, with reference date `v_t`,
- a `DiscountingBondEngine` on that curve (or on a `ZeroSpreadedTermStructure`
  over it, for a bond with a spread).

Nothing else changes. Generating the cash flows never reads the evaluation
date when the effective date is given, so every bond has one leg for all
items (`Legs`), and every pricing function of pureql accepts explicit dates.
Valuing at a future date therefore needs no new mathematics: the model's
results at `(scen_id, t)` are bit-identical to

1. pureql called with explicit dates (`settlementDate`, `npvDate`),
2. pureql with `Settings.evaluationDate` moved to `v_t`,

and agree with QuantLib 1.41 with its evaluation date moved to `v_t` to the
T2 tolerance (relative 1e-12). The tests check all three
(`tests/pv`, `tests/future`).

## 2. The rules at a valuation date v_t

The six rules below hold identically at `t = 0` and at every later `t`.

### 2.1 Valuation date and curve

`v_t = val_date[t]`. The curve of `(scen_id, t)` is a fixed-reference curve
whose reference date is `v_t`, so times are measured from `v_t` with the
curve's day counter (`timeFromReference`, pureql `termstructure.py`,
`termstructure.hpp:133-135`) and `D(v_t) = 1.0` exactly.

- **ZeroCurve** (pureql `termstructures/yield_/zerocurve.py`): node 0 must be
  `v_t`; nodes given by tenor are `v_t + tenor` (`Date + Period`, no
  calendar). Node times are `dayCounter.yearFraction(v_t, date)`
  (`InterpolatedCurve.setupTimes`, `interpolatedcurve.hpp:100-115`); rates
  quoted in a compounding other than Continuous are converted to continuous
  zero rates (node 0 over 1/365 of a year, `zerocurve.hpp:249-276`); the
  curve is linear in the continuous zero rate, with flat-forward
  extrapolation beyond the last node (`zerocurve.hpp:159-169`).
- **FlatForward** (pureql `termstructures/yield_/flatforward.py`):
  `D(t) = 1 / compoundFactor(t)` of the flat rate in its quoted convention.
- **ZeroSpreadedTermStructure** (pureql
  `termstructures/yield_/zerospreadedtermstructure.py`,
  `zerospreadedtermstructure.hpp:142-150`), for a bond with a `spread_id`:
  the curve's zero rate in the spread's compounding and frequency, plus the
  spread of `(scen_id, t)`, converted back to a continuous rate. The model
  performs this full round trip with no algebraic shortcut, as pureql does.
  The range check is the original curve's (its extrapolation flag and
  maximum time).

### 2.2 Settlement date

`s_t = max(calendar.advance(v_t, n, Days, Following), issueDate)`
(`Bond::settlementDate`, pureql `instruments/bond.py`, `bond.cpp:162-173`;
`Valuation.settle(b)`), where `n` is the bond's `settlement_days` and
`calendar` its calendar. With `n = 0` this is `v_t` adjusted to a business
day. Before the issue date `s_t` is the issue date: a bond valued before it is
issued is a forward-start bond, priced for settlement at issue.

### 2.3 NPV: the flows after v_t

`NPV_t = sum over the flows that have not occurred at v_t of amount * D(d)`,
divided by `D(npvDate) = D(v_t) = 1.0`
(`DiscountingBondEngine::calculate`, pureql
`pricingengines/bond/discountingbondengine.py`,
`discountingbondengine.cpp:36-67`; `CashFlows::npv`, pureql
`cashflows/cashflows.py`, `cashflows.cpp:424-447`; `Valuation.npv(b)`).

- A flow dated after `v_t` counts; one dated before does not; one dated on
  `v_t` counts only if the engine's include flag is set (section 3).
- The sum runs in leg order with sequential `+=`, as upstream.
- Flows trading ex-coupon are skipped (no v1 bond has an ex-coupon period).
- `NPV_t = 0.0` if the bond has expired at `v_t`, i.e. all its flows have
  occurred (`Instrument::isExpired`, `Bond::isExpired`, `bond.cpp:104-111`).
- A bond with a spread is discounted on the spreaded curve; one without on
  the plain curve (section 4.5).

### 2.4 Settlement value, prices and accrued: at s_t

The settlement value, dirty and clean prices and accrued interest are all
taken at the settlement date `s_t`, as `Bond::settlementValue()`,
`dirtyPrice()`, `cleanPrice()` and `accruedAmount()` take them at
`settlementDate()`:

- `settlement_value(b)`: 0.0 if expired; the NPV when the engine flag is off
  and `v_t == s_t` (the engine's shortcut, `discountingbondengine.cpp:36-67`);
  otherwise the flows that have not occurred at `s_t` (a flow ON `s_t` does
  not count: the include flag is hard-coded False), discounted to `s_t`:
  `sum amount * D(d) / D(s_t)`.
- `dirty_price(b) = settlement_value * 100 / N(s_t)`, where `N(s_t)` is the
  notional in force at `s_t` (`Bond::notional`, `bond.cpp:113-139`; 0.0 after
  the last redemption, and already reduced on a redemption date).
- `accrued_amount(b)`: the accrued interest at `s_t` of the coupons paid on
  the next payment date after `s_t` (`CashFlows::accruedAmount`,
  `cashflows.cpp:376-393`), per 100 of `N(s_t)` (`BondFunctions::accruedAmount`,
  `bondfunctions.cpp:224-235`).
- `clean_price(b) = dirty_price(b) - accrued_amount(b)`.

So a flow dated in `(v_t, s_t]` counts in `NPV_t` but not in the settlement
value or the prices: it is paid to the seller. In particular a bond that
matures inside `(v_t, s_t]` has a positive NPV but `N(s_t) = 0`: it is not
tradable and its prices are 0.0 (section 4.3).

The prices from a given z-spread, `dirty_from_z(b, z)` and `clean_from_z(b, z)`
(`BondFunctions::dirtyPrice` / `cleanPrice` with a z-spread,
`bondfunctions.cpp:488-528`), are also taken at `s_t`.

### 2.5 Yield and risk: at s_t, in the bond's yield conventions

A yield `y` is the InterestRate `InterestRate(y, yield_day_counter,
yield_compounding, yield_frequency)` of the bond (`Valuation.ydc/ycomp/yfreq`).
Every yield function of the model is pureql's `CashFlows` function with
`includeSettlementDateFlows = False` and `settlementDate = npvDate = s_t`, so
it covers the flows that have not occurred at `s_t` (the SETTLE role of
section 3) and does not use the curve at all:

- `npv_yield(b, y)`: `CashFlows::npv` at a rate (`cashflows.cpp:813-855`),
  the **stepwise** scheme: walking the live flows in leg order, each flow
  multiplies a running discount factor by `y.discountFactor(step)`, where
  `step` is the time from the previous live flow (or from `s_t`) to the flow
  (`getStepwiseDiscountTime`, `cashflows.cpp:567-600`; `Lib.stepwise_time`,
  `Valuation.ystep(p)`). A coupon whose accrual start is not the previous date
  (a coupon in progress at `s_t`, a stub) steps by the difference of two year
  fractions from its accrual start; a redemption with no previous live flow
  gets the reference period `[d - 1Y, d]`.
- `simple_duration_y`, `modified_duration_y`, `macaulay_duration_y`,
  `convexity_y` (`cashflows.cpp:602-722, 975-1043`): the **accumulated**
  scheme: the time to each flow is the sum of the same steps, `tt`, and the
  factor is `y.discountFactor(tt)` over the whole of it.
- `bpv_y`, `yvbp_y` (`cashflows.cpp:1059-1130`): the stepwise npv combined
  with the accumulated modified duration and convexity, in upstream's order.
- `dirty_from_yield(b, y) = npv_yield * 100 / N(s_t)`, `clean_from_yield =
  dirty_from_yield - accrued_amount` (`BondFunctions::dirtyPrice` /
  `cleanPrice` at a yield, `bondfunctions.cpp:306-346`).

The two schemes are QUIRK Q-09 of quantlib-migration, and the model keeps
both, never unified: for a Compounded yield they agree to the last bits over
whole periods and differ elsewhere, and for a Simple yield they always differ,
so a Simple-yield modified duration is not the logarithmic derivative of the
price at that yield. This is QuantLib's arithmetic.

**The yield** `ytm(b)` (`BondFunctions::yield`, `bondfunctions.hpp:167-195`):
the target is the quoted price of `prices.csv` at `(scen_id, t)` if there is
one, else the engine's clean price (`clean_price(b)`, as `Bond::yield` uses
it). A clean price is made dirty with `accrued_amount(b)`, then divided by
`100 / N(s_t)` (`y_target`). The cash flows must change sign against the
target (`IrrFinder::checkSign`, `sign_ok`), and the root of
`npv_yield(b, y) - target` is found by `solve(b, SOLVE_YIELD)`: Solver1D's
bracketing walk from the guess with step `guess/10`, then NewtonSafe with
QuantLib v1.43's derivative `-modifiedDuration(y) * npv(y)` (the default, as
`BondFunctions::yield`), or Brent (`Data.yield_solver = 1`). The defaults are
`BondFunctions::yield`'s: accuracy 1e-10, 100 evaluations, guess 0.05.
`Bond::yield` uses accuracy 1e-8; with `yield_accuracy = 1e-8` the model
reproduces quantlib-migration's headline yield `0.030250400779423203`.

**The risk measures** `duration_simple/modified/macaulay(b)`, `convexity(b)`,
`bpv(b)`, `yvbp(b)` (`BondFunctions::duration`, ..., `bondfunctions.cpp:389-476`,
not rescaled to par) are taken at `risk_yield(b)`: the quoted yield of
`yields.csv` if there is one, else `ytm(b)`. `dirty_at_yield_in(b)` and
`clean_at_yield_in(b)` are the prices at the quoted yield.

QuantLib 1.41, which the tests use as a second oracle, predates the v1.43
derivative: its NewtonSafe yield differs from v1.43's in the last ~1e-10
(oracle skew OS-10). The model's NewtonSafe yield is therefore compared with
pureql only (bit for bit); against QuantLib 1.41 the price at the model's
yield and the model's Brent yield are compared.

### 2.6 Z-spread: over the curve of (scen_id, t), in its spread conventions

`zspread(b)` (`BondFunctions::zSpread`, `bondfunctions.cpp:540-568`;
`CashFlows::zSpread`, `cashflows.cpp:1190-1225`) is the spread `z` for which
`pv_z(b, z)`, the bond's flows after `s_t` on `ZeroSpreaded(curve, z,
spread_compounding, spread_frequency)` discounted to `s_t`, equals the
quoted price made dirty and divided by `100 / N(s_t)` (`z_target`). It is
solved by Brent (`solve(b, SOLVE_ZSPREAD)`): the bracketing walk from the
guess (default 0.0) with step 0.01, accuracy 1e-10, 100 evaluations. It is
solved only where `prices.csv` gives a price at `(scen_id, t)` (NaN
elsewhere), or, with `Data.zspread_price_source = 1`, also from the engine's
clean price. The z-spread is measured over the plain curve whatever the
bond's own `spread_id`.

Spreads are calibrated at `t = 0` by the model itself and fed forward in
`spreads.csv` (DECISIONS.md D-4): `tools/calibrate_spreads.py` solves
`zspread(b)` at `(scen_id, 0)` and writes an input set in which each priced
bond has its own `spread_id` with that spread at every `(scen_id, t)`. A
spread is a number in each `(scen_id, t)`'s spread conventions: if they
change over t, the same number means a different curve.

### 2.7 The solver, as transcribed

`solve(b, kind)` is one formula holding pureql's `Solver1D.solve(f,
accuracy, guess, step)` (`solver1d.hpp:83-147`) and its two concrete
solvers, `NewtonSafe.solveImpl` (`newtonsafe.hpp:42-109`) and
`Brent.solveImpl` (`brent.hpp:39-133`), statement for statement, with the
objective inlined (each trial yield or spread is one call of the cached
`npv_yield` / `pv_z`). The accuracy is floored at machine epsilon; the
bracket grows by 1.6 on the side with the smaller absolute value, alternating
sides when they are equal (that branch counts one extra evaluation, as
upstream); both solvers make upstream's final `f(root)` call before
returning. No caller sets solver bounds, so `enforceBounds` is left out. The
solver state is held in doubles, including the evaluation counter.

## 3. Which flows have "occurred": the three flags

QuantLib decides whether a cash flow dated `d` has occurred at a reference
date with `CashFlow::hasOccurred` and `Event::hasOccurred` (pureql
`cashflow.py`, `cashflow.cpp:27-49`; pureql `event.py`, `event.cpp:28-39`;
`Lib.has_occurred`). A flow before the reference date has occurred and one
after it has not; for a flow ON the reference date three settings decide.
They are `Data` References; the defaults are QuantLib's.

| `Data` Reference | QuantLib | Values | Default |
|---|---|---|---|
| `include_reference_date_events` (R) | `Settings::includeReferenceDateEvents` | 0, 1 | 0 |
| `include_todays_cashflows` (T) | `Settings::includeTodaysCashFlows` | -1 (none), 0, 1 | -1 |
| `engine_include_settlement_flows` (F) | `DiscountingBondEngine`'s `includeSettlementDateFlows` | -1 (none), 0, 1 | -1 |

A flow on the reference date is still to be paid ("not occurred") when the
effective include flag is 1:

| Role | Used by | Reference date | Effective include flag |
|---|---|---|---|
| ENGINE | NPV, `Proj` period buckets | `v_t` | T if set, else F if set, else R |
| SETTLE | settlement value, prices, accrued | `s_t` | 0; but T if set and `s_t == v_t` |
| EXPIRY | `is_expired` | `v_t` | T if set, else R |

T overrides the others whenever the reference date is the evaluation date
(`v_t`), as in QuantLib. With the defaults a flow on `v_t` has occurred: it
is not in `NPV_t`, and it falls in projection period `t`.

## 4. Policies (DECISIONS.md D-4)

### 4.1 Market value

`market_value(b) = npv(b)`: the engine NPV at `v_t` on the valuation curve
(spreaded if the bond has a spread). It is the one figure for which the
roll-forward identity of section 5 holds with the `Proj` cash-flow periods.
The settlement value, dirty and clean prices and accrued are reported too
(`result_frame()`).

### 4.2 Flags

The QuantLib defaults of section 3 (R = False, T = None, F = None), exposed as
`Data` References.

### 4.3 Non-tradable bonds (QUIRK Q-04)

A bond whose notional at `s_t` is 0.0 (it has matured, or matures, by the
settlement date) is not tradable (`BondFunctions::isTradable`,
`bondfunctions.cpp:39-45`). pureql's and QuantLib's `BondFunctions` raise
"non tradable" when a price is asked of it, while the `Bond` methods
(`dirtyPrice()`, `cleanPrice()`, `accruedAmount()`) return 0.0. The model's
`Data.nontradable_policy`:

- `NT_ENGINE` (0, default): the dirty and clean prices and the accrued amount
  are 0.0 (as `Bond::dirtyPrice()` etc. give them), the prices from a
  z-spread or a yield are 0.0, and the yield, z-spread, risk yield and risk
  measures are NaN. A run never stops on such a bond.
- `NT_RAISE` (1): the BondFunctions members (`dirty_from_z`, `clean_from_z`,
  `dirty_from_yield`, `clean_from_yield`, `ytm`, `zspread`, `risk_yield` and
  the risk measures) raise pureql's message `non tradable at <date> (maturity
  being <date>)` (`Valuation.nt_ok`). Used by the tests.

`accrued_total()` sums the accrued interest in currency (`accrued_cash`), so
a non-tradable bond can add to it while its `accrued_amount` is 0.0.

### 4.4 Extrapolation

`extrapolate` is an input per `(scen_id, t)` (`curve_params.csv`), off by
default as in pureql. Without extrapolation, discounting a date past the
curve's last node raises pureql's `time (...) is past max curve time (...)`
(`TermStructure::checkRange`, `termstructure.cpp:64-72`). The driver checks
coverage before valuing anything: for every `(scen_id, t)` it runs the range
check at the portfolio's latest flow date, and lists every item that would
fail (`run.py`, the curve pre-flight). A FlatForward curve reaches
`Date::maxDate()` and never fails the check.

### 4.5 Bonds without a spread

A bond with a blank `spread_id` is valued on the plain curve, not on
`ZeroSpreaded(curve, 0)`: the two differ in the last bits (the headline
bond's dirty price at t = 0 is 108.41230620520015 on the curve and
108.41230620520007 on `ZeroSpreaded(curve, 0)`), and the plain curve is what
pureql gives a bond priced on the curve itself.

### 4.6 Yield, Macaulay duration, z-spread and solver failures

- Yield: the target price is the input price if given, else the engine clean
  price; the defaults reproduce pureql's `BondFunctions.bondYield` (accuracy
  1e-10, 100 evaluations, guess 0.05). Parity with `Bond.bondYield` needs
  `yield_accuracy = 1e-8`.
- Z-spread at future t: solved only where an input price exists (or, with
  `zspread_price_source = 1`, from the engine's clean price).
- Solver failures (`Data.solver_error_policy`): a bracketing walk that does
  not find a sign change ("unable to bracket root in N function evaluations
  (...)"), a solver that runs out of evaluations ("maximum number of function
  evaluations (N) exceeded") and cash flows that cannot reach the target
  ("the given cash flows cannot result in the given market price due to their
  sign") raise pureql's message under `ERR_RAISE` (0, default) and give NaN
  under `ERR_NAN` (1). The risk measures at a NaN yield are NaN. An error
  raised inside the objective itself (for example an InterestRate whose
  compound factor turns non-positive far out in a bracketing walk) and a
  non-positive accuracy raise under both policies.
- Macaulay duration with a yield that is not Compounded: NaN under
  `ERR_NAN`, raises "compounded rate required" under `ERR_RAISE`. It is
  decided before the duration is computed. With the default `ERR_RAISE`, a
  `result_frame()` at output level 2 or more on a portfolio that holds such a
  bond raises; set `ERR_NAN` (`run.py --solver-errors nan`) for such runs.

## 5. Identities across valuation dates

- **`D(v_t) = 1.0`** exactly on every curve, so `NPV_t` needs no division
  by the discount at the npv date (the model divides anyway, as upstream).
- **NPV and the projection periods.** `Proj` puts each flow in the period
  `per` of the first valuation date at which it has occurred for the ENGINE
  role (the same predicate as the NPV). So `NPV_t` covers exactly the flows of
  periods `t+1 .. T` (when F is unset or equals R; see the roll-forward
  below), and the cash of period `t+1` is what leaves the valuation between
  `v_t` and `v_{t+1}`.
- **Roll-forward.** If the curve of `t+1` is the forward curve implied by the
  curve of `t` (`D_{t+1}(d) = D_t(d) / D_t(v_{t+1})`) and the bond has no
  spread, then
  `NPV_t = sum of amount * D_t(d) over the flows of period t+1 + D_t(v_{t+1}) * NPV_{t+1}`.
  It holds to rounding (T2 tolerance), not bit for bit: the two sides
  discount on different curves. It needs the engine flag F to be unset or
  equal to R: `NPV_t` is 0.0 once the bond has expired, and expiry uses R
  (section 3, EXPIRY role) while the periods use the engine's flag. With F
  set and different from R, a bond whose last flow falls ON a valuation date
  breaks the identity by exactly that flow, in QuantLib as in the model
  (`tests/future/test_future_identities.py`).

## 6. Validation before valuation

`Data.check_inputs()` rejects every input pureql would refuse when the
curve, the schedule or the bond is built, so that a run does not stop half
way: unknown names, dates out of range, non-increasing valuation dates, a
non-dense `(scen_id, t)` grid, an InterestRate convention that needs a
frequency, a ZeroCurve with fewer than 2 or more than `MAX_NODES` nodes, node
0 off `v_t`, node dates not increasing, or two node dates that map to the same
time under the curve's day counter (30E/360 maps the 30th and the 31st of a
month to the same time; pureql refuses the curve with "two passed dates (...)
correspond to the same time under this curve's day count convention (...)").
`Legs.check_limits()` then checks the sizes the compiled model is built with
(see [model.md](model.md), "Limits").

## 7. Where each rule lives

| Rule | Model Cells | pureql | QuantLib v1.43 |
|---|---|---|---|
| evaluation date | `Valuation.vdate()` | `settings.py` | `Settings::evaluationDate` |
| curve times, node checks | `node_time`, `curve_ok`, `Data.node_errors` | `termstructures/interpolatedcurve.py` | `interpolatedcurve.hpp:100-115` |
| ZeroCurve | `node_zc`, `node_slope`, `zero_c`, `discount_core` | `termstructures/yield_/zerocurve.py` | `zerocurve.hpp:159-169, 249-276` |
| FlatForward | `discount_core` | `termstructures/yield_/flatforward.py` | `flatforward.hpp:102-105` |
| range check | `range_ok` | `termstructure.py` | `termstructure.cpp:64-72` |
| ZeroSpreaded | `zs_base`, `zs_discount_kd`, `zdisc` | `termstructures/yield_/zerospreadedtermstructure.py` | `zerospreadedtermstructure.hpp:142-150` |
| settlement date | `settle_cal`, `settle` | `instruments/bond.py` | `bond.cpp:162-173` |
| notional at settlement | `notional_s`, `is_tradable` | `instruments/bond.py`, `pricingengines/bond/bondfunctions.py` | `bond.cpp:113-139`, `bondfunctions.cpp:39-45` |
| occurrence | `Lib.has_occurred`, `first_live` | `cashflow.py`, `event.py`, `cashflows/cashflows.py` | `cashflow.cpp:27-49`, `event.cpp:28-39`, `cashflows.cpp:101-117` |
| expiry | `is_expired` | `instruments/bond.py` | `bond.cpp:104-111` |
| NPV, settlement value | `pv_base`, `pv_sprd`, `npv`, `settlement_value` | `cashflows/cashflows.py`, `pricingengines/bond/discountingbondengine.py` | `cashflows.cpp:424-447`, `discountingbondengine.cpp:36-67` |
| accrued | `accrued_cash`, `accrued_amount`, `Lib.coupon_accrued_amount` | `cashflows/cashflows.py`, `cashflows/fixedratecoupon.py` | `cashflows.cpp:376-393`, `fixedratecoupon.cpp:73-89` |
| prices | `dirty_price`, `clean_price` | `instruments/bond.py` | `bond.cpp:175-185` |
| prices from a z-spread | `pv_z`, `dirty_from_z`, `clean_from_z` | `pricingengines/bond/bondfunctions.py` | `bondfunctions.cpp:488-528`, `cashflows.cpp:1146-1175` |
| tradability guard | `nt_ok` | `pricingengines/bond/bondfunctions.py` | `bondfunctions.cpp:39-45` |
| stepwise time | `Lib.stepwise_time`, `ystep` | `cashflows/cashflows.py` | `cashflows.cpp:567-600` |
| npv at a yield | `npv_yield` | `cashflows/cashflows.py` | `cashflows.cpp:813-855` |
| durations, convexity | `simple_duration_y`, `modified_duration_y`, `macaulay_duration_y`, `convexity_y` | `cashflows/cashflows.py` | `cashflows.cpp:602-722, 926-958, 975-1043` |
| BPV, YVBP | `bpv_y`, `yvbp_y` | `cashflows/cashflows.py` | `cashflows.cpp:1059-1130` |
| prices from a yield | `dirty_from_yield`, `clean_from_yield` | `pricingengines/bond/bondfunctions.py` | `bondfunctions.cpp:306-346` |
| yield target, sign check | `y_price`, `y_target`, `sign_ok`, `Lib.sign` | `instruments/bond.py`, `pricingengines/bond/bondfunctions.py`, `cashflows/cashflows.py` | `bond.cpp:199-216`, `bondfunctions.hpp:167-195`, `cashflows.cpp:556-565, 771-811` |
| z-spread target | `z_price`, `z_target` | `pricingengines/bond/bondfunctions.py` | `bondfunctions.cpp:540-568` |
| solvers | `solve` | `math/solver1d.py`, `math/solvers1d/newtonsafe.py`, `math/solvers1d/brent.py`, `cashflows/cashflows.py` | `solver1d.hpp:83-147`, `newtonsafe.hpp:42-109`, `brent.hpp:39-137`, `cashflows.cpp:754-769, 1190-1225` |
| yield, z-spread, risk | `ytm`, `zspread`, `risk_yield`, `duration_*`, `convexity`, `bpv`, `yvbp` | `pricingengines/bond/bondfunctions.py` | `bondfunctions.cpp:373-476, 540-568` |
| projection periods | `Proj.bucket_arr` | (model only) | |
