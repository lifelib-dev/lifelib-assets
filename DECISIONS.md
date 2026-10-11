# Decisions

This file records the modelling policies of `BondPortfolio` and what the model derives from. The full rationale is in [docs/plan.md](docs/plan.md).

## D-1. What is derived, and how

- **Source.** The model's financial formulas are transcribed from quantlib-migration's `pureql`, which is a port of QuantLib v1.43, tag v1.43, commit 6b57206e04598f092efee66e3b367efc84771995.
- **No imports.** The model never imports `pureql` or QuantLib (quantlib-migration decision D-11). Tests import both as oracles.
- **Attribution.**
  - Every transcribed formula carries `# ported from pureql/<path> (ql/<file>:<lines>), QuantLib v1.43, BSD-3-Clause` in its body.
  - Its docstring carries `Derived from QuantLib (BSD-3-Clause); see NOTICE.md.`.
  - NOTICE.md sits at the project root, outside the model directory.
- **Licences.** The project's own (non-derived) files are under the MIT License (`LICENSE.txt`), like lifelib. The derived files stay BSD-3-Clause, as NOTICE.md states.
- **Open item for the owner:** the legal judgements listed in quantlib-migration `MIGRATION_PLAN.md` §6.10.

## D-2. Fidelity

- **Bit-exact with pureql.** Every output is `==` to `pureql`, bit for bit, in modelx, export and compiled modes. A mismatch is a defect, never a tolerance.
- **Where tolerance tiers apply.** Comparisons with QuantLib 1.41 use the quantlib-migration T2 tier (relative 1e-12). The same tier applies to identities across different computation paths.

## D-3. v1 scope

| Area | Covered |
|---|---|
| Bonds | FixedRateBond and ZeroCouponBond |
| Schedule rules | DateGeneration Backward, plus the Zero arm a zero tenor forces |
| Calendars | NullCalendar, TARGET, UnitedStates (Settlement, GovernmentBond) |
| Day counters | Actual360, Actual365Fixed, Thirty360 (USA, BondBasis/ISMA, European/EurobondBasis) |
| Curves | ZeroCurve (linear in zero rate), FlatForward, ZeroSpreadedTermStructure |

Other conventions raise "not supported" until a later phase adds them.

## D-4. Valuation policies

| Topic | Policy |
|---|---|
| Market value | `market_value = npv(b)`, the engine NPV at the valuation date on the valuation curve (spreaded if the bond has a spread). Settlement value, dirty and clean price, and accrued are also reported. |
| Flow-inclusion flags | QuantLib defaults: `includeReferenceDateEvents=False`, `includeTodaysCashFlows=None`, engine `includeSettlementDateFlows=None`. They are exposed as `Data` References. |
| Non-tradable bonds (`notional(settlement) == 0`, QUIRK Q-04) | `NT_ENGINE` (default): prices and accrued are 0.0, and yield, z-spread and risk are NaN. `NT_RAISE` reproduces pureql's raise and is used in tests. |
| Extrapolation | An input per (scenario, t), default off as in pureql, with a pre-flight coverage check. |
| No-spread bonds | Valued on the plain curve. `ZeroSpreaded(curve, 0)` is not bit-identical to `curve`. |
| Yield | The default reproduces `BondFunctions.bondYield`: NewtonSafe (`yield_solver = 0`) with the v1.43 `IrrFinder` derivative, accuracy 1e-10, 100 evaluations, guess 0.05. `yield_solver = 1` uses Brent instead, the solver QuantLib 1.41 can be compared with (oracle skew OS-10). The target price is the input price if given, else the engine clean price (Clean). `Bond.bondYield` parity needs `yield_accuracy = 1e-8`. |
| Risk yield | The risk measures are taken at the input yield if given, else at the solved yield. A non-tradable bond follows the non-tradable policy even when it has an input yield. |
| Solver failures | `ERR_RAISE` (default) raises pureql's message, `ERR_NAN` gives NaN. The policy covers exactly a root that cannot be bracketed, the maximum number of evaluations, the cash-flow sign check and the Macaulay rule below. Any other error is raised under both policies: a non-positive accuracy, an error inside the objective, a curve error. |
| Macaulay duration | For a non-Compounded yield it is NaN under `ERR_NAN` and raises under `ERR_RAISE`. Analytics output (level 2 or 3) over inputs with such yields therefore needs `ERR_NAN` (`run.py --solver-errors nan`). |
| Z-spread | Solved where an input price exists; with `zspread_price_source = 1`, also from the engine clean price elsewhere. Without a price it is NaN, under either non-tradable policy. Brent, as `CashFlows.zSpread`. |
| Spread calibration | Spreads are calibrated at t = 0 by the model itself (`tools/calibrate_spreads.py`) and fed forward unchanged to every t. Each scenario is calibrated at its own t = 0, or every scenario takes scenario K's spreads (`--scen K`). A bond that is not tradable at t = 0 is left uncalibrated. |
