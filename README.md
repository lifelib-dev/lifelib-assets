# lifelib-assets

Asset models for [lifelib](https://lifelib.io), built with [modelx](https://modelx.io).

## BondPortfolio

`bond_portfolio/BondPortfolio` is a modelx model of a bond portfolio. It does three things:

1. **Generates the cash flows** of fixed-rate and zero-coupon bonds: schedules, coupons and redemptions.
2. **Values the bonds** on a discount curve plus spread: NPV, settlement value, dirty and clean price, accrued interest, z-spread, yield, duration, convexity and BPV.
3. Does (2) **at future valuation dates** under scenarios, given the curves, spreads and conventions at each date as inputs.

The financial logic is a statement-for-statement transcription of
[quantlib-migration](https://github.com/lifelib-dev/quantlib-migration)'s
`pureql`, a pure-Python port of the fixed-rate bond subset of QuantLib v1.43.
QuantLib's observer, lazy-evaluation and global-settings machinery is
replaced by modelx's dependency graph and explicit arguments.

- **No QuantLib dependency.** The model does not import QuantLib or `pureql`.
- **Bit-exact with pureql.** It reproduces `pureql`'s numbers exactly (`==`). This holds in plain modelx, in the pure-Python package from `modelx.export_model`, and in the package compiled by [modelx-cython](https://github.com/fumitoh/modelx-cython).

This project includes code derived from QuantLib. See [NOTICE.md](NOTICE.md).
The derived files are licensed BSD-3-Clause, as NOTICE.md lists them; the
project's own files are under the MIT License ([LICENSE.txt](LICENSE.txt)).
It is not part of QuantLib and is not endorsed by the QuantLib Group.

## Status

v1 is implemented: phases 0-5 of [docs/plan.md](docs/plan.md).

**Supported conventions.**
- FixedRateBond and ZeroCouponBond.
- DateGeneration Backward.
- Calendars: NullCalendar, TARGET and UnitedStates (Settlement, GovernmentBond).
- Day counters: Actual360, Actual365Fixed and the simple Thirty360 conventions.
- Curves: ZeroCurve and FlatForward, plus z-spreads.

Later conventions are listed in the plan, phase 6 onwards.

**How it is checked.** Every output is checked against pureql with `==`, at t = 0 and at future valuation dates. Values are also checked against QuantLib 1.41 at the T2 tolerance. The compiled package equals the export, which equals modelx, bit for bit.

**Compiled speed** depends on the modelx-cython version:

- **Released modelx-cython.** It builds and passes every check.
- **Faster: unreleased branch.** The branch `bondportfolio/mx2cy-improvements` types the uncached helper Cells and runs about 30-40% faster. Point `MODELX_CYTHON_SRC` at a checkout of it when running `tools/build_cy.py`. See [docs/mx2cy-issues.md](docs/mx2cy-issues.md) and [docs/performance.md](docs/performance.md).

See [docs/model-contract.md](docs/model-contract.md) for the model's interface
(section 6 records what was built), [DECISIONS.md](DECISIONS.md) for the
modelling policies, and [bond_portfolio/model.md](bond_portfolio/model.md) for
the model itself.

## Running

`bond_portfolio/run.py` runs the model on a directory of input CSV files and
writes the cash flows, the cash flows per projection period, one valuation
file per scenario, the totals per (scenario, date) and a run summary (times,
peak memory):

```
python bond_portfolio/run.py --inputs bond_portfolio --out out                    # the demo inputs, modelx mode
python bond_portfolio/generate_inputs.py --n-bonds 10000 --n-scen 2 --n-times 121 --seed 1 --out big
python tools/build_cy.py                                                         # export + compile
python bond_portfolio/run.py --inputs big --out out_big --mode compiled [--scen 1] [--times 0-12,24]
python bond_portfolio/run.py --inputs bond_portfolio --out out2 --output-level 3 --solver-errors nan  # + analytics
python tools/calibrate_spreads.py --inputs bond_portfolio --out calibrated        # z-spreads at t = 0, fed forward
```

- **Modes.** `modelx` reads the model with modelx (development, small
  portfolios); `export` runs the pure-Python package from
  `modelx.export_model`; `compiled` runs that package compiled by
  modelx-cython. All three give byte-identical outputs.
- **Building.** `tools/build_cy.py` exports the model, compiles it and writes
  the build sizes (`sizes.json`). **On Windows run it from PowerShell**: from
  Git Bash the MSVC `cl.exe` step fails. The build goes to
  `~/.cache/lifelib-assets/build` when the project is in a OneDrive folder,
  else to `build/` (`BONDPORTFOLIO_BUILD` overrides). Rebuild after every
  change to the model.
- **Checks.** The driver validates the inputs, refuses any beyond the model
  limits or the build sizes, and pre-flights every curve before valuing
  anything; it then values one (scenario, date) item at a time.
- **Analytics.** `--output-level 1` (the default) writes the prices.
  Level 2 adds the yield to maturity, the durations, convexity, BPV and YVBP.
  Level 3 also adds the z-spread, for bonds with a quoted price in `prices.csv`.
  - A failed solve, or the Macaulay duration of a yield that is not
    Compounded, raises by default.
  - `--solver-errors nan` writes NaN instead. Inputs with such yields need it
    at level 2 or 3; the demo inputs and generated portfolios have them.
- **Spread calibration.** `tools/calibrate_spreads.py` solves each priced
  bond's z-spread at t = 0 with the model. It writes a copy of the input set
  that carries those spreads at every (scenario, date).

[bond_portfolio/model.md](bond_portfolio/model.md) describes the Spaces,
inputs, settings, outputs and limits;
[bond_portfolio/technical-notes.md](bond_portfolio/technical-notes.md) what a
valuation at a future date includes; [docs/performance.md](docs/performance.md)
the measured times and memory (10,000 bonds x 121 dates x 2 scenarios: about
65 s compiled, 184 s export, at output level 1; the level-2 analytics take
about 8 min compiled).

## Running the tests

The tests compare the model with `pureql`. They expect a quantlib-migration
checkout next to this project, or one named by the `PUREQL_SRC` environment variable.

```
python -m pytest                                   # all but the slow, perf and compiled tests
python -m pytest -m oracle                         # the QuantLib 1.41 comparisons (T2 tolerance)
python -m pytest -m slow                           # full sweeps (fuzz, flag matrices, all mode cases)
python tools/build_cy.py                           # from PowerShell on Windows; then:
python -m pytest -m compiled                       # compiled == export == modelx
python -m pytest -m perf                           # memory streaming on a generated portfolio
```
