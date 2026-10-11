# Plan: `BondPortfolio`, a modelx bond portfolio model transcribed from quantlib-migration (`pureql`)

## Context

### Why
The user wants a fast, modelx-native bond-portfolio model that does three things:
1. **Generates bond cash flows** by reusing the cash-flow logic of quantlib-migration (`pureql`, a faithful pure-Python port of QuantLib v1.43's fixed-rate subset).
2. **Computes present values** by reusing `pureql`'s PV logic.
3. **Extends (2) to future valuation points t**, taking curves, spreads and other parameters at each t as inputs. `pureql` and QuantLib price only at "today".

### Constraints
- **No observer machinery.** QuantLib's Observer, LazyObject, Handle and Settings are left out. modelx's dependency graph and memoisation replace them.
- **Transcribe, never import.** `pureql` is meant to be read and transcribed (decision D-11, `quantlib-migration/docs/migration/DECISIONS.md:193-206`). The **model never imports `pureql` or QuantLib**. Tests may import both as oracles; QuantLib 1.41 is installed in py313.
- **Not BasicBonds.** lifelib `BasicBonds` (QuantLib SWIG, one object per bond) is too slow and is **not a reference**.
- **Must compile with modelx-cython.** The same model must run in modelx (development) and compiled (export, then `mx2cy`, for production).
- **Per-bond generation is fine.** Per-instrument cash-flow generation that stays close to QuantLib's code is in scope.

### User decisions
- **Inputs** are keyed by **scenario × t** (`Valuation[scen_id, t]`); a deterministic run is one scenario.
- **v1 coverage:**
  - Bonds: **FixedRateBond and ZeroCouponBond**.
  - Schedule: DateGeneration **Backward**, including its stub and end-of-month logic, plus the Zero arm that a zero-length tenor forces.
  - Calendars: **NullCalendar, TARGET, UnitedStates (Settlement, GovernmentBond)**.
  - Day counters: **Actual360, Actual365Fixed, Thirty360 (USA, BondBasis/ISMA, European/EurobondBasis)**.
  - Curves: ZeroCurve (linear interpolation on zero rates, flat-forward extrapolation), FlatForward, ZeroSpreaded.
  - InterestRate: all five compoundings.
- **Analytics at every (scen, t):**
  - NPV, settlement value, dirty price, clean price and accrued amount;
  - **z-spread solve** (Brent);
  - **yield solve** (NewtonSafe, with the v1.43 IrrFinder derivative) and **price-from-yield**;
  - **duration** (simple, modified, Macaulay), **convexity, BPV, YVBP**.
- **Compiled speed** comes from **improving modelx-cython** (Phase 5). The model keeps exactly one canonical copy of each transcribed function and duplicates no code blocks.

### Facts established by exploration (read-only workflows; the evidence is in the session journals)
- **Cash-flow generation never reads the evaluation date** when an explicit effective date is given. A trap test showed this: patching `Settings` to raise did not affect it.
- **Every PV function accepts explicit dates.** Pricing at a future t was **bit-identical** across three computations:
  - `pureql` with explicit dates;
  - `pureql` with `Settings` moved to t;
  - QuantLib 1.41 with `Settings` moved to t.

  The inputs were the settlement date `s_t = max(cal.advance(t, n, Days), issueDate)` and a curve whose reference date is t. So **Goal 3 needs no new mathematics**: only explicit dates, and curves with reference date t.
- **Bit-exactness depends on five things:**
  - sequential `+=` sums (never `sum()` or `np.sum`);
  - the three price-scaling orders;
  - the ZeroSpreaded round trip with no algebraic shortcut;
  - the ZeroCurve `if compounding != Continuous` guard (`zerocurve.py:569`);
  - exact solver algorithms.
- **`ZeroSpreaded(curve, 0)` is not bit-identical to `curve`** (108.41230620520015 vs 108.41230620520007). Bonds with no spread are therefore valued on the plain curve.

---

## Design

### Project layout (`C:/Users/fumito/OneDrive/pyproj/lifelib-assets`)
```
NOTICE.md            QuantLib BSD-3 notice (holders list, BSD text, 3 attributions, non-endorsement,
                     derived-files statement); at the root, outside the model dir (write_model rotates _BAKn)
LICENSE.txt          licence of the project's own files (assumed MIT, like lifelib; user to confirm)
README.md, DECISIONS.md  policies below, fidelity tiers, and what is derived from what
pyproject.toml       pytest markers: oracle, slow, compiled, perf; env PUREQL_SRC (default ../quantlib-migration/src)
bond_portfolio/
  BondPortfolio/     the modelx model (serializer 8, formulas only, no IOSpec/ModuleData)
  bonds.csv valuation_dates.csv curve_params.csv curve_nodes.csv spreads.csv [prices.csv yields.csv coupon_rates.csv]
  run.py             driver: modes modelx | export | compiled; scenario-major streaming
  generate_inputs.py seeded synthetic portfolios and scenarios
  model.md, technical-notes.md
tools/  new_model.py (one-off skeleton via the modelx API), export_model.py, build_cy.py (export + spec + mx2cy),
        cy/sample.py + cy/sample_inputs/, make_goldens.py, calibrate_spreads.py (runs the MODEL itself), bench.py
tests/  lint/, unit/, cashflows/, pv/, future/, modes/, perf/, helpers/ (approx.py copied from QLM), data/ (goldens + provenance)
build/  (gitignored) BondPortfolio_nomx/, BondPortfolio_nomx_cy/, spec.py
```
The model is created once with `tools/new_model.py`. After that, formulas are edited in place in `BondPortfolio/<Space>/__init__.py`. The serializer keeps comments inside function bodies, so provenance comments survive.

### Space tree
The ItemSpaces' references to top-level singletons survive both `export_model` and mx2cy. This was verified against `exporter.py:401-407` and against modelx-cython's BasicTerm_SC and ref_space samples.

**Legend:** **[C]** cached with int-only parameters (a C array once compiled), **[S]** parameterless, **[D]** has a float parameter (dict cache), **[O]** returns an object or array, **[U]** canonical uncached function.

| Space | Kind | Contents and the `pureql` source each part transcribes |
|---|---|---|
| **Data** | singleton | References: `input_dir` (str); flags R=0, T=-1, F=-1; policies (`nontradable_policy`, `solver_error_policy`, `output_level`); solver settings. CSV readers [O] (DataFrames; ISO date → serial `(date-1899-12-30).days`; names → int codes; tenor parser). Numpy-array Cells [O] (int64/float64, read **element-only**). Counts [S]. `check_inputs()`. **All** readers live here, including the scen×t tables. |
| **Lib** | singleton, [U] | `_cxx` IEEE helpers (`cxx_exp/pow/div`); `close`, `close_enough` (`math/comparison.py:78-118`); InterestRate `compound_factor`, `discount_factor`, `implied_rate`, `equivalent_rate` (`interestrate.py:279-575`); `has_occurred` (`cashflow.py:123-155` + `event.py:92-128`, with Settings as explicit arguments); `trading_ex_coupon`; `stepwise_time` (`cashflows.py:327-378`); `coupon_accrued_amount` (`fixedratecoupon.py:294-317`); `nan_value()`, `inf_value()`. |
| **Dates** | singleton | Date tables and algebra keyed by int serial **[C]** (`time/date.py`); `easter_monday`; `target_bd`, `us_settlement_bd`, `us_govbond_bd` (`calendars/target.py:72`, `unitedstates.py`); `is_business_day(cal, d)` [C]; `adjust`, `advance` (`calendar.py:548-700`); `day_count`, `year_fraction` (`actual360.py`, `actual365fixed.py:97`, `thirty360.py:141-219`). |
| **Bond[b]** | ItemSpace, generated once per bond at Python speed | Input accessors [S]; `calendar()`; `schedule()` = `Schedule._init_rule` (`time/schedule.py:340-716`) transcribed statement for statement, Backward and Zero arms, other rules raise "not supported"; `coupons()` = `FixedRateLeg.build` (`fixedratecoupon.py:532-630`) with FixedRateBond's builder settings (`fixedratebond.py:111-205`); `coupon_amounts()` = `nominal*(compoundFactor-1.0)`; `notional_schedule()` (`bond.py:1385-1436`; ZCB `setSingleRedemption` `bond.py:1336-1382`); `redemptions()` (`bond.py:1270-1323`); `leg()` (stable sort); `maturity_date()`; `cashflow_table()`. |
| **Legs** | singleton | The portfolio leg in CSR form: `cf_lo`, `cf_date`, `cf_kind`, `cf_amount`, `cf_nominal`, accrual/reference dates, coupon rate/dc, `ns_*` notional schedule, `bk_*` per-bond scalars. `cashflow_frame()` [O]: the **Goal 1 output**, with ISO dates, bond_key, kind, amount, accrual dates, nominal, rate. `check_limits()`. |
| **Proj** | singleton | `bucket_arr()`: the period of each flow, using the **same ENGINE occurrence predicate as NPV**. `bucket_sums()`: [T+1, 4] in a single pass in flow order. `coupon_cf(per)`, `redemption_cf(per)`, `total_cf(per)`, `bond_cf_table()`. |
| **Valuation[scen_id, t]** | ItemSpace (Goals 2 and 3) | See below. |

**`Valuation[scen_id, t]`.** All Cells take small int indices: `b`, `role`, `kind`, `kd` (a day offset), `n` (a node), `p` (a global flow), `(cal, nsd)`.

- **Context.** `vdate()`, which replaces `Settings.evaluationDate`; curve conventions at (scen, t); `engine_flag()` = F if set, else R (`discountingbondengine.py:144-148`); `max_time()`; `curve_ok()`.
- **Curve.**
  - `node_time(n)`, `node_zc(n)`: the ZeroCurve `_initialize` conversion, which runs only for non-Continuous rates, with node 0 converted over 1/365.
  - `node_slope(n)`.
  - Day-offset Cells shared by all bonds: `curve_time(kd)`, `range_ok(kd)` (checkRange), `zero_c(kd)` (`zerocurve.py:519-539`), `discount_core(kd)` (ZeroYield `exp(-r t)` with the `t==0` guard; FlatForward uses `1/compoundFactor`), `discount(kd)`, `zs_base(kd)`.
  - `zdisc(p)`: the ZeroSpreaded per-flow discount, using the full round trip (`zerospreadedtermstructure.py:238-261`).
- **Per-bond state.**
  - `settle_cal(cal, nsd)`, `settle(b)` (`bond.py:756-786`);
  - `notional_s(b)` (`bond.py:630-686`), `is_tradable(b)`;
  - `first_live(b, role)`: a binary search over the monotone predicate;
  - `is_expired(b)`.
- **Engine family.**
  - `pv_base(b, role)` = `CashFlows._npv_curve` (`cashflows.py:1234-1283`), sequential `+=`, final `/ D(npvDate)`;
  - `pv_sprd(b, role)`;
  - `npv(b)`: the engine NPV (`discountingbondengine.py:113-171`) with the expiry short-circuit;
  - `settlement_value(b)`;
  - `accrued_cash(b)` / `accrued_amount(b)` (`cashflows.py:1099-1133`, `bondfunctions.py:494-518`);
  - `dirty_price(b)`, `clean_price(b)` (`bond.py:822-911`);
  - `market_value(b)`.
- **Z-spread.**
  - `pv_z(b, z)` [D] (`cashflows.py:1376-1453`);
  - `dirty_from_z`, `clean_from_z`;
  - `z_target(b)`;
  - `zspread(b)` (`bondfunctions.py:1470-1542`, then `cashflows.py:2520-2615`).
- **Yield and risk.**
  - Stepwise discounting: `ystep_first(b)`, `ystep(p)`, which is dynamic whenever the previous live flow is dated `s_t`. Used by `npv_yield(b, y)` [D] (`cashflows.py:1285-1353`, QUIRK Q-09).
  - Accumulated time: `simple_/modified_/macaulay_duration_y`, `convexity_y`.
  - `bpv_y` and `yvbp_y` mix the stepwise NPV with accumulated duration and convexity (`cashflows.py:2343-2518`).
  - `y_target(b)`, `sign_ok(b)` (IrrFinder.checkSign), `ytm(b)`, `risk_yield(b)`;
  - risk outputs, prices from yield.
- **`solve(b, kind)`**, one formula:
  - Solver1D bracketing (`solver1d.py:192-254`);
  - then Brent (`brent.py:80-157`, including the general `close(xMin, xMax)`) or NewtonSafe (`newtonsafe.py:112-168`);
  - the objective and derivative are inlined, keeping v1.43 operand order;
  - double locals throughout, with a double evaluation counter.
- **Aggregates.** `npv_total()`, `mv_total()`, …; `result_frame()` and `result_block()`, according to `output_level`.

**Occurrence roles** (a single predicate, `Lib.has_occurred`; `eval_date = vdate()`; the T-override applies only when `ref == vdate()`):

| Role | ref | include flag | Used by |
|---|---|---|---|
| ENGINE | `vdate()` | `engine_flag()` | NPV, Proj buckets |
| SETTLE | `settle(b)` | False (hard-coded upstream) | SV, accrued, prices, yield, z-spread |
| EXPIRY | `vdate()` | None, which resolves to R | `is_expired` |

### Inputs
- **Representation.** Dates are int serials; 0 is the null date. Enums are pureql's int values, and calendars, day counters and bond types get model codes. Tri-state flags are −1/0/1.
- **`bonds.csv`** (row order defines `b`):
  - all bonds: `bond_key`, `bond_type`, `face_amount`, `settlement_days`, `calendar`, `issue_date`, `redemption`, `spread_id` (blank means the plain curve);
  - FixedRateBond schedule: `effective_date`, `termination_date`, `tenor`, `convention`, `termination_convention`, `rule`, `end_of_month`, `first_date`, `next_to_last_date`;
  - coupons: `coupon_rate` (step-ups go in `coupon_rates.csv`), `accrual_day_counter`, `first_period_day_counter`, `payment_convention`, `payment_calendar`;
  - ZeroCouponBond: `maturity_date`;
  - yield quote: `yield_day_counter`, `yield_compounding`, `yield_frequency`.
- **Scenario × t tables:**
  - `valuation_dates.csv` (t, val_date; strictly increasing; shared by all scenarios);
  - `curve_params.csv` (scen_id, t, curve_type, day_counter, compounding, frequency, extrapolate, flat_rate, spread_compounding, spread_frequency);
  - `curve_nodes.csv` (scen_id, t, node, date or tenor, rate; node 0 must equal val_date);
  - `spreads.csv` (scen_id, t, spread_id, spread);
  - optional `prices.csv` and `yields.csv`, both sparse.

### Future-t semantics (identical to t = 0; each is exactly `pureql` with E = v_t)
1. `v_t = val_date[t]`. `curve_t` is a fixed-reference curve with reference date v_t, so `D(v_t) = 1.0` exactly.
2. Settlement date: `s_t = max(cal.advance(v_t, n, Days, Following), issueDate)`. With n = 0 this is `adjust(v_t)`. Before issue, `s_t` is the issue date (forward start).
3. `NPV_t` covers flows with `d > v_t`, or `d >= v_t` if the ENGINE flag is set. Ex-coupon flows are skipped. It is 0 if the bond has expired.
4. `SV_t`, dirty, clean and accrued are all taken at `s_t`. A flow in (v_t, s_t] counts in NPV_t but not in prices.
5. Yield and risk are computed from npvDate = `s_t` using the bond's yield conventions, independent of the curve.
6. Z-spread is solved only where an input price exists at (scen, t).

**Policies, recorded in DECISIONS.md**

| Topic | Policy |
|---|---|
| Market value | `market_value = npv(b)`, the only figure that satisfies the roll-forward identity with the Proj buckets. SV, dirty, clean and accrued are also reported. |
| Flags | QuantLib defaults (R=False, T=None, F=None), exposed as references. |
| Q-04 (bond with `notional(s_t) == 0`) | `NT_ENGINE` default: prices and accrued are 0.0; yield, z-spread and risk are NaN. `NT_RAISE` replicates pureql and is used in tests. |
| Extrapolation | Per (scen, t) input, default 0 (pureql-faithful), with a pre-flight coverage check. |
| Yield default | Price target is the input price, else the engine clean price (Price.Clean). Defaults match `BondFunctions.bondYield` (accuracy 1e-10, 100 evaluations, guess 0.05). Parity with `Bond.bondYield` needs `yield_accuracy=1e-8`. |
| Macaulay duration with a non-Compounded yield | NaN under `ERR_NAN`, raise under `ERR_RAISE`, gated before the call. |
| Spread calibration | Calibrate at t = 0 with `tools/calibrate_spreads.py`, which solves with the model, not pureql, then feed spreads forward. |

### modelx-cython rules (from the mx2cy survey and verification)
- **Types and parameters:**
  - Date serials appear only as parameters of singleton Cells (Dates). ItemSpace Cells take only small-index int parameters, with **distinct parameter names per domain**.
  - Cells return int/float/bool scalars: `bool(...)` for bools, float literals (`0.0`) for floats. Never None, `np.bool_` or lists on hot paths.
  - **Wrap every float64 array element read, and every float argument to a [D] Cells, in `float(...)`.** Otherwise the export-mode sample mixes `float` and `np.float64`, and mx2cy silently types the parameter `object`. The wrap is free once compiled.
- **Arrays and data.**
  - Array Cells are used **only element-wise** everywhere. Code that needs whole arrays (validation, aggregates, frames) reads the DataFrame or dict sources instead.
  - No pandas inside per-bond or per-flow Cells.
- **Arithmetic and solvers.**
  - No `**`. Use `float(math.pow(..))` with `except (OverflowError, ValueError)` falling back to `Lib.cxx_pow`, and the same for `exp`. This is exact in every mode.
  - No `sum()`, `np.sum` or `round(`.
- **Calls.** No keyword-argument calls to Cells.
- **Model structure.**
  - No names starting with `_`.
  - No Space-formula base/refs, `_bases`, or child spaces under ItemSpaces.
  - No ModuleData or PandasData. Inputs are CSV files reached through the typed `input_dir` string reference, because the exported `_model.path` is the export package.
- **Build files.**
  - `sample.py` exercises every branch with floats only, raises nothing, and **leaves Bond and Valuation items alive**, so that Space-parameter types are traced.
  - `spec.py` is generated from model-level `MAX_*` references through a static tuple-to-reference map, with a completeness test against the generated `.pxd`.
- **Driver memory.** Exported and compiled spaces are self-cyclic (`_space`, `_mx_roots`). After building Legs, delete the Bond items, then call `gc.collect()` and `gc.freeze()`. After each `del Valuation[s, t]`, call `gc.collect()`.
- **Sizing at a 10k-bond profile** (estimates; to be measured in Phase 5):
  - About 21 MB of C arrays per Valuation item; only one item is live at a time.
  - Core PV about 2–8 µs per bond-point compiled, so 10k bonds × 121 t × 10 scenarios takes about 0.5–1.5 min.
  - Adding yield and risk takes about 6–10 min more.

### Fidelity policy
- **`==` pureql, bitwise, in modelx, export and compiled modes** for every output: dates, legs, buckets, discounts, NPV, SV, prices, accrued, solved z-spreads and yields, durations, convexity, BPV and YVBP. Any mismatch is a defect; there are no tolerance waivers.
- **`compiled == export == modelx`**: bitwise.
- **T2 tier** (relative 1e-12, absolute floor 1e-14; solver results 1e-11) applies only to:
  - comparisons with QuantLib 1.41. NewtonSafe yields are never compared directly with 1.41 because of oracle skew OS-10; the price at the model's yield is compared, and the Brent option is compared against 1.41's yieldBrent. isRegular is not compared on OS-02 shapes;
  - identities across computation paths: forward-implied, roll-forward, and `dirty = clean + accrued`.
- **T1 tier** applies to upstream cached constants.

---

## Phases (each delivers a usable increment; from Phase 1 on, every phase ends with the compile gate)

**Compile gate.** It has three checks:
- `tools/build_cy.py` succeeds;
- `compiled == export == modelx` holds bitwise on the phase's corpus;
- a `.pxd` audit finds no hot or [D] Cells with an `object`-typed parameter or return.

**Phase 0: Scaffolding**
- Create the layout, NOTICE.md (verbatim from `QLM/LICENSES/QuantLib-LICENSE.TXT` 1-192 and 195-231, plus `docs/ATTRIBUTION_TEMPLATE.md:54-84`), DECISIONS.md, pyproject.toml and the test helpers.
- Write `tools/new_model.py` and the empty spaces.
- Write the L0 lints:
  - no `pureql` or QuantLib in the model;
  - the forbidden constructs above;
  - each transcribed Cells has its body comment `# ported from pureql/<path> (ql/<file>:<lines>), QuantLib v1.43, BSD-3-Clause`, whose anchor matches the pureql `# ql:` line;
  - each docstring has the line `Derived from QuantLib (BSD-3-Clause); see NOTICE.md.`;
  - naming and collision rules.
- Run a one-command export plus mx2cy smoke test on the skeleton.

**Phase 1: Goal 1, cash flows**
- 1a. Lib (IEEE, comparison, InterestRate, predicates).
- 1b. Dates: tables, algebra, the 4 calendars, adjust/advance, day counters.
- 1c. Data: **all** readers and parsers (bonds, coupon rates, valuation dates, curve params and nodes, spreads, prices, yields), `check_inputs`, `generate_inputs.py`.
- 1d. `Bond[b]` generators.
- 1e. Legs (CSR, `cashflow_frame`, `check_limits`) and Proj (`bucket_sums`).
- 1f. A minimal `run.py` that writes the cash-flow table and the period buckets.
- **Exit criteria:**
  - Exhaustive L1 tests pass.
  - 10k random v1 legs `==` pureql.
  - The headline bond's 21 flows match bit-exactly; the `tracer_bonds.json` zcb-10y keys match.
  - Bucket reconciliation passes.
  - The compile gate passes.

**Phase 2: Goal 2, core PV at t = 0** (item (1, 0); full (scen_id, t) signatures from the start)
- Steps:
  - Curve Cells.
  - Settlement, notional, `first_live`, expiry.
  - Engine family on the plain and spreaded curves: NPV, SV, accrued, dirty, clean, market value.
  - Price from z-spread.
  - NT policy and aggregates.
- **Exit criteria:**
  - Headline bond NPV `108.36776235612268` and clean `108.34563953853349` bit-exact.
  - testCachedZero (`QLM tests/unit/test_bonds.py:1002-1077`) at T1, plus a T2 twin against QuantLib 1.41.
  - A 1k-bond random portfolio on both curve types, with and without spread, `==` pureql.
  - The compile gate passes.

**Phase 3: Goal 3, future t** (inputs and driver; no new Valuation formulas)
- Steps:
  - Extend `generate_inputs.py` to multiple scenarios and T > 1, with tenor nodes resolved against `val_date(t)`.
  - Streaming `run.py`: scenario-major loop; `del` plus `gc.collect()` per item; per-scenario output files; refuses inputs that exceed the build sizes.
  - Write `technical-notes.md`.
- **Exit criteria:**
  - Measured 2020 goldens: NPV `102.13530449214969`, dirty `102.18428521477128`, clean `102.11761854810462`.
  - The edge grid: coupon dates, a payment falling in (v, s], before issue, maturity inside (v, s] and after maturity, holidays, extrapolation 0/1, and the R/T/F flag matrix including the T-override (dirty 98.0607 → 100.3107).
  - A fuzz of 10k (bond, t) cases `==` pureql explicit-date and `==` pureql with Settings moved, and T2 against QuantLib 1.41 with its evaluation date moved.
  - The forward-implied identity and the roll-forward identity against the buckets.
  - The compile gate passes.
  - An export-mode run of 10k bonds × 121 t × 2 scenarios, with time and RSS recorded.

**Phase 4: Analytics at every (scen, t)**
- Steps:
  - z-spread solve (Brent).
  - Yield solve (NewtonSafe, plus a Brent option) with `sign_ok`.
  - Stepwise `npv_yield`, durations, convexity, BPV, YVBP, prices from yield.
  - The ERR policy and the Macaulay rule.
  - `calibrate_spreads.py`.
- **Exit criteria:**
  - Headline yield `0.030250400779423203` (at `yield_accuracy=1e-8` with the engine clean price).
  - zcb-10y z-spread, duration and convexity goldens.
  - z round trip over `_Z_GRID` × 4 conventions × 2 curves within 1e-11, from clean and from dirty prices, at t = 0 and at future t.
  - y → P → y round trip.
  - Q-09 pins.
  - Everything `==` pureql.
  - The compile gate passes.

**Phase 5: Compile and performance, by improving modelx-cython**
- Steps:
  - Bench at 10k × 121 × 10 and profile.
  - Make the mx2cy changes, each gated by `compiled == export` over the full corpus and with its own mx2cy tests:
    1. trace and type **uncached Cells**: admit their names in `MxCodeFilter` (`modelx_cython/tracer.py:589-603`) and map them in fqname/flush;
    2. a spec or CLI option for Cython **compiler directives** (`infer_types`), emitted into the generated `setup.py` (`cli.py:552-601`);
    3. optionally, lower `math.exp/log/pow` on doubles to libm behind bit-equality tests;
    4. optionally, an exporter/mx2cy `__delitem__` that breaks the `_space`/`_mx_roots` cycles (`modelx/export/exporter.py:731-734`).
  - Re-run the `.pxd` and annotate audit.
  - Publish `docs/performance.md`.
- **Exit:** full corpus bitwise across modes; a timed production configuration.

**Phase 6 onwards: Later conventions** (codes are reserved, and the dispatch arms raise "not supported" today)
- Forward and other DateGeneration rules.
- Ex-coupon: the canonical Lib functions already exist; add the Legs columns and hot-loop branches.
- AmortizingFixedRateBond with `sinkingNotionals`, DEV-28/29 guards.
- ActualActual (ISDA, and ISMA with schedule, replicating Q-13).
- UnitedKingdom, WeekendsOnly, Joint calendars and the other Thirty360 variants.
- Holiday overrides.
- Bond chunking.
- Scenario-dependent flows (calls, defaults, trading).

---

## Verification (pytest; `pureql` imported in tests only, via `PUREQL_SRC`; QuantLib 1.41 behind the `oracle` marker with Settings restored)
- **L0 static.** The lints described in Phase 0; spec completeness; NOTICE.md present at the root and verbatim; a `write_model` round trip into `tmp_path`.
- **L1 units `==` pureql:**
  - date functions, exhaustive over serials 367..109574;
  - `is_business_day`, exhaustive for the 4 calendars;
  - adjust/advance grids;
  - day counters over `DAY_COUNT_PAIRS` plus random pairs;
  - InterestRate in all compoundings, including the IEEE edge cases;
  - the `has_occurred` matrix;
  - all 3 branches of `stepwise_time`;
  - schedules: `market.SCHEDULES` plus random specs;
  - curve Cells at nodes, off nodes and when extrapolating (Continuous and non-Continuous);
  - solvers on synthetic objectives.
- **L2 cash flows.** Random legs `==` pureql, headline flows, tracer goldens, bucket reconciliation.
- **L3/L4 at t = 0.** Headline bond, testCachedZero, zcb-10y, the 1k portfolio, round trips, Q-09 pins, `pv_z` at the input spread `==` `pv_sprd`.
- **L5/L6 at future t.** As listed in the Phase 3 and 4 exits.
- **L7 modes.**
  - `export == modelx` and `compiled == export`, bitwise and NaN-aware;
  - the `.pxd` type audit;
  - IndexError beyond the spec limits versus `check_limits`;
  - a trace-type test asserting every [D] float parameter is traced as `float`.
- **L8 perf/memory.** µs per bond-point by output level. A streaming test asserts that the number of live `_c_Valuation` objects stays at most base+1 over 50 or more items.

**Running it:**

```
C:/Users/fumito/anaconda3/envs/py313/python.exe -m pytest tests
```

```
C:/Users/fumito/anaconda3/envs/py313/python.exe tools/build_cy.py
```

Then `bond_portfolio/run.py --mode compiled`.

---

## Reused sources
- **pureql** (transcription sources; `# ql:` anchors give the provenance):
  - `time/{date,period,calendar,schedule}.py`, `time/calendars/{target,unitedstates,nullcalendar}.py`, `time/daycounters/{actual360,actual365fixed,thirty360}.py`;
  - `interestrate.py`, `_cxx.py`, `math/{comparison,interpolation,solver1d}.py`, `math/interpolations/linearinterpolation.py`, `math/solvers1d/{brent,newtonsafe}.py`;
  - `cashflow.py`, `event.py`, `cashflows/{coupon,fixedratecoupon,simplecashflow,cashflows}.py`;
  - `instruments/{bond.py,bonds/fixedratebond.py,bonds/zerocouponbond.py}`;
  - `pricingengines/bond/{bondfunctions,discountingbondengine}.py`;
  - `termstructure.py`, `termstructures/{yieldtermstructure,interpolatedcurve}.py`, `termstructures/yield_/{zerocurve,flatforward,zeroyieldstructure,zerospreadedtermstructure}.py`.
- **QLM tests and data:**
  - `tests/helpers/{approx,market,scenario,oracle}.py`, used as patterns or copied with attribution;
  - `tests/data/tracer_bonds.json` (QuantLib 1.41 goldens, evaluation date 2015-09-16);
  - `tests/meta/test_documentation_set.py:306-392` (headline bond);
  - `tests/unit/test_bonds.py:1002-1077` (testCachedZero);
  - `tests/unit/test_cashflows.py:377-497` (flag matrix);
  - `tests/differential/test_fixedratebond_vs_oracle.py:900-1083` (fuzz pattern);
  - `tests/new/instruments/test_fixedratebond_port_only.py:295-396` (round trips, monotonicity).
- **Licence material:** `docs/ATTRIBUTION_TEMPLATE.md`, `LICENSES/QuantLib-LICENSE.TXT`, `NOTICE`.
- **modelx and modelx-cython** (Phase 5 changes): `modelx_cython/{tracer,builder,transformer,cli}.py`, `modelx_cython/_mx_sys.pxd`, `modelx/export/exporter.py`. Reference examples: `examples/basiclife/BasicTerm_SC` (Data arrays read through Cells), `tests/samples/ref_space`.
- **lifelib conventions:** uslib house style (`lifelib/libraries/uslib/tests/test_model_conventions.py`): CSV inputs beside the model, docstrings on every Space and Cells, snake_case names.

## Risks and open items
- **mx2cy is experimental**, and Cells types come only from the sample trace. Mitigations: the L0 lints, the no-raise full-coverage sample, the `.pxd` audit, and the compile gate in every phase.
- **Python-level `math` calls cap compiled speed** until the optional Phase 5 libm lowering, which must stay bit-identical.
- **Build flags.** FMA or fast-math flags would break `compiled == export`. Keep the default MSVC flags.
- **modelx mode does not scale.** It is for development subsets only, because Bond items cannot be freed there without clearing Legs.
- **Golden coverage under the v1 conventions is thin**: the headline bond, zcb-10y, testCachedZero and the 2020 goldens. Most validation therefore rests on live `==` pureql comparisons.
- **For the user to confirm:** the MIT licence for the project's own files; the legal and trademark judgements of QLM `MIGRATION_PLAN.md` §6.10, i.e. whether a transcription is a derived work and the "QuantLib" naming. No name in this project contains "QuantLib".
