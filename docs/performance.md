# BondPortfolio performance record

This file records measured run times and memory of `bond_portfolio/run.py`.
Plan Phase 3 asks for "an export-mode run of 10k bonds x 121 t x 2
scenarios, with time and RSS recorded". The section "Phase 5" below
records the same profiles after the modelx-cython improvements
(docs/mx2cy-issues.md). The Phase 3 and Phase 4 tables are kept as they
were measured.

## How the numbers are produced

```
C:/Users/fumito/anaconda3/envs/py313/python.exe -B tools/build_cy.py        # from PowerShell
C:/Users/fumito/anaconda3/envs/py313/python.exe -B tools/bench.py --doc docs/performance.md
```

`tools/bench.py` generates a seeded portfolio with
`bond_portfolio/generate_inputs.py` (default 10,000 bonds, 2 scenarios, 121
monthly valuation dates from 2015-09-16, seed 1), runs `run.py` once per mode
in a fresh process, checks that the modes wrote byte-identical CSV files, and
replaces the block below with the table. Its options (`--n-bonds`,
`--n-times`, `--modes`, `--scen`, `--times`, ...) time other shapes or a
subset of the (scen_id, t) grid.

Terms:

- **item**: one `Valuation[scen_id, t]`, i.e. every bond valued at one
  valuation date under one scenario. `run.py` creates one item, harvests
  `result_frame()` (settlement date, notional, NPV, settlement value, dirty
  and clean price, accrued, market value, tradable, expired) and the six
  aggregates, deletes the item and runs `gc.collect()`; one item is alive
  at a time.
- **bond-point**: one bond at one item. "us per bond-point (valuation)" is
  the `valuation` stage divided by bonds x items. It includes creating and
  deleting the items and `gc.collect()`, and excludes writing the CSV files,
  which the next row adds.
- **stages** are those of `run.py` (see its docstring): `load` (import or
  `read_model`), `inputs, Legs, limits` (`check_inputs`, every `Bond[b]`
  schedule and leg, `Legs`, `check_limits`, the `sizes.json` check),
  `free Bond items` (export and compiled only), `cash-flow outputs`
  (`cashflows.csv` and `period_cashflows.csv`, including `Proj`),
  `curve pre-flight`, `valuation` and `valuation output writing`.
- **RSS** is the working set from `GetProcessMemoryInfo` (Windows).

## Results

<!-- bench:begin -->
Generated portfolio: 10,000 bonds, 2 scenario(s) x 121 valuation dates (step 1M, seed 1); 408,290 flows. Valued: 242 (scen_id, t) item(s).

Machine: 12th Gen Intel(R) Core(TM) i7-12700KF, 20 logical CPUs, 63.8 GB RAM; Windows-11-10.0.26300-SP0. python 3.13.9, numpy 2.3.3, pandas 3.0.0, modelx 0.33.0, modelx_cython 0.1.0, Cython 3.2.4. Run on 2026-10-11; input generation took 0.6 s.

| | export | compiled |
|---|---:|---:|
| load (s) | 0.05 | 0.01 |
| inputs, Legs, limits (s) | 3.73 | 1.70 |
| free Bond items (s) | 0.05 | 0.05 |
| cash-flow outputs (s) | 3.15 | 2.43 |
| curve pre-flight (s) | 0.01 | 0.54 |
| valuation (s) | 166.79 | 50.53 |
| valuation output writing (s) | 10.05 | 9.74 |
| **total, in run.py** (s) | **183.88** | **65.05** |
| process wall time (s) | 184.47 | 65.67 |
| seconds per (scen_id, t) item | 0.731 | 0.249 |
| **us per bond-point** (valuation) | **68.9** | **20.9** |
| us per bond-point incl. output writing | 73.1 | 24.9 |
| RSS after Legs (MB) | 318 | 374 |
| **peak RSS** (MB) | **422** | **432** |

CSV outputs byte-identical across the modes: yes (5 files, 370 MB per mode).
<!-- bench:end -->

The table above is the full Phase 3 profile, measured in full (no subset, no
extrapolation): `python tools/bench.py --doc docs/performance.md` with the
defaults, after rebuilding with `tools/build_cy.py`. Other sessions may have
been running tests on the same machine at the time (and were, during the
modelx measurement below), so the times may be a few percent high.

### modelx mode, for reference (subset, extrapolated)

modelx mode is for development; the same portfolio, valuing 3 of the 242
items (`--modes modelx --scen 1 --times 0,60,120`):

| | modelx |
|---|---:|
| load (s) | 0.56 |
| inputs, Legs, limits (s) | 54.94 |
| cash-flow outputs (s) | 20.68 |
| curve pre-flight (s), all 242 items | 5.31 |
| valuation (s), 3 items | 73.79 |
| seconds per (scen_id, t) item | 24.7 |
| us per bond-point (valuation) | 2,460 |
| full grid (242 items), valuation extrapolated | 100 min |
| RSS after Legs (MB) | 2,290 |
| peak RSS (MB) | 4,032 |

Its 30,000 valuation rows, its totals and its two cash-flow files are
byte-identical to the corresponding rows and files of the compiled run.

## Reading the results

- **The Phase 3 production profile runs in about a minute compiled.**
  10,000 bonds x 121 monthly dates x 2 scenarios (2.42 million bond-points,
  408,290 flows) take 65 s in compiled mode and 184 s in export mode, end to
  end, including writing 370 MB of CSV output. Valuation is 78% (compiled)
  and 91% (export) of the time.
- **Speed per bond-point.** 20.9 us compiled, 68.9 us export, about 2,460 us
  in modelx: compiled is 3.3 times export and about 120 times modelx. The
  plan's estimate for compiled core PV was 2 to 8 us per bond-point; the gap
  is what plan Phase 5 addresses in modelx-cython (docs/mx2cy-issues.md):
  the canonical `Lib` and `Dates` helpers are uncached Cells, which mx2cy does
  not trace and compiles untyped, so every call from a hot Cells is a Python
  call on Python objects (#1); integer locals stay Python objects without
  `infer_types` (#2); `math.exp`/`pow` stay Python calls (#3).
- **Output writing** (pandas `to_csv` of 10,000 rows per item, shortest
  round-trip floats) costs about 10 s in either mode: 15% of the compiled
  run. A binary output format would remove most of it if it matters.
- **Setup** (reading the inputs, generating 10,000 schedules and legs, the
  CSR arrays, `check_limits`) takes 1.7 s compiled and 3.7 s export; the
  cash-flow outputs (`cashflows.csv`, 48 MB, and the period buckets) another
  2.4 to 3.2 s.
- **Memory is flat over the run.** One `Valuation` item is alive at a time,
  so the RSS after the last item equals the RSS before the first (375 MB
  export, 390 MB compiled) and the peak is 422 / 432 MB. Deleting the Bond
  items once `Legs` is built frees 27 MB in export mode and 171 MB in compiled
  mode. modelx mode keeps all 10,000 `Bond` items and its dependency graph:
  2.3 GB after Legs and a 4 GB peak.
- **`gc.collect()` after each `del` is required** (docs/mx2cy-issues.md #4).
  Without it, with the collector's default thresholds, about 20 deleted items
  were alive at once in `tests/perf/test_memory.py` before an automatic
  collection freed them. The per-item `gc.collect()` costs little after
  `gc.freeze()`, which moves the long-lived objects (inputs, Legs) out of the
  collector's view.
- **The compiled curve pre-flight** costs 0.5 s for 242 items (creating an
  item allocates its C arrays); in export mode it is negligible.
- **Bitwise across modes at scale.** The export and compiled runs wrote
  byte-identical files (5 files, 370 MB), and the modelx subset matches both:
  `compiled == export == modelx` holds on 2.42 million bond-points.

## Phase 4: analytics by output level (compiled)

Measured after Phase 4 with the rebuilt package. Only `compiled` mode was run, one `tools/bench.py` run per row (seed 1, step 1M). `--output-level 2` adds `ytm`, `risk_yield`, the three durations, convexity, BPV and YVBP for every bond at every item. A generated portfolio draws its yield compounding from all five, so level 2 runs with `--solver-errors nan`; otherwise its first non-Compounded Macaulay duration raises (DECISIONS.md D-4).

```
python tools/bench.py --modes compiled --n-bonds 1000 --n-scen 2 --n-times 13 --output-level 1
python tools/bench.py --modes compiled --n-bonds 1000 --n-scen 2 --n-times 13 --output-level 2 --solver-errors nan
python tools/bench.py --modes compiled --output-level 1                                       # the Phase 3 profile
python tools/bench.py --modes compiled --output-level 2 --solver-errors nan --scen 1 --times 0,60,120
```

| portfolio | items valued | level | valuation (s) | us per bond-point | us incl. writing | peak RSS (MB) |
|---|---:|---:|---:|---:|---:|---:|
| 1,000 bonds x 2 x 13 | 26 | 1 | 0.91 | 34.9 | 40.7 | 201 |
| 1,000 bonds x 2 x 13 | 26 | 2 | 6.63 | 254.9 | 264.6 | 203 |
| 10,000 bonds x 2 x 121 | 242 (full grid) | 1 | 51.13 | 21.1 | 25.2 | 450 |
| 10,000 bonds x 2 x 121 | 3 (scen 1, t = 0, 60, 120) | 2 | 5.99 | 199.6 | 207.8 | 466 |

- **Level 1 has not slowed.** The Phase 3 profile runs at 21.1 us per bond-point, against 20.9 before Phase 4 (66.3 s end to end, against 65.1).
  - The larger `Valuation` class costs a little per item: the compiled curve pre-flight, which only creates the items, takes 0.99 s for 242 items against 0.54 s. The peak RSS is 450 MB against 432 MB.
- **Level 2 costs 7 to 10 times level 1** per bond-point, about 200 to 255 us compiled.
  - Each yield is a NewtonSafe solve: every trial yield evaluates the stepwise `npv_yield` and the accumulated-time `modified_duration_y`, each one pass over the bond's live flows.
  - The six risk measures are further passes at the solved yield.
  - Extrapolated from the 3-item subset, the 10,000-bond x 121-date x 2-scenario grid at level 2 takes about 8.4 min of valuation. That is inside the plan's estimate of 6 to 10 min on top of core PV.
  - The `[D]` caches are per item and freed with it, so the peak RSS hardly grows: 466 MB against 450 MB at level 1.
- **Why level 2 is slow.** The per-flow work runs through the uncached `Lib` / `Dates` helpers (`discount_factor`, `stepwise_time` via `ystep`, `year_fraction`), which mx2cy compiles untyped (docs/mx2cy-issues.md #1-#3). That is plan Phase 5's target.
- The 1,000-bond rows give a higher figure per bond-point than the 10,000-bond rows. They amortise each item's fixed cost (creation, `result_frame`, `gc.collect()`) over fewer bonds, and the 13 early dates carry more live flows per bond than the 121-date average.

## Phase 5: modelx-cython improvements

Measured on 2026-10-11 with the modelx-cython branch `bondportfolio/mx2cy-improvements` (`main` 0f3e564 plus uncommitted changes; docs/mx2cy-issues.md, "Status after Phase 5"). The model is unchanged since Phase 4. Five builds of the same export were compared, each built by `tools/build_cy.py` into its own directory (`BONDPORTFOLIO_BUILD`):

| build | modelx-cython | `tools/build_cy.py` options |
|---|---|---|
| **main** | `main` 0f3e564, i.e. the Phase 4 build, rebuilt the same day | none |
| **P5** | the branch | none: the default build, which the tests and drivers use |
| **P5 + infer** | the branch | `--directive infer_types=True` |
| **P5 + libm** | the branch | `--use-libm` |
| **P5 + both** | the branch | `--directive infer_types=True --use-libm` |

```
# PowerShell, per build (MODELX_CYTHON_SRC: a checkout of the branch; unset for main)
$env:MODELX_CYTHON_SRC = 'C:/Users/fumito/.cache/lifelib-assets/modelx-cython-wt'
$env:BONDPORTFOLIO_BUILD = 'C:/Users/fumito/.cache/lifelib-assets/build_both'
python -B tools/build_cy.py --directive infer_types=True --use-libm
python -B -m pytest -m compiled                    # compiled == export, bitwise
python -B tools/bench.py --modes compiled ...      # the four Phase 4 configurations
```

**Method.**
- Each configuration ran 3 times per build, interleaved across the builds. The tables give the median run.
- `export` ran once per configuration, alongside the first P5 run.
- Every compiled run's CSV files were compared by SHA-256 with that export run's files. All 60 runs were byte-identical to export: 30 at 1,000 bonds and 30 at 10,000 bonds, about 7 GB of output in all, export runs included.
- No other benchmark ran at the same time. A test run of another session may have overlapped the first 1,000-bond runs.

**Gates passed by every build.**
- The extended pxd audit (`tools/build_cy.py`): no Cells, cached or uncached, has an `object` return or parameter outside the listed exceptions.
- `pytest -m compiled`: 17 passed.
- The default P5 build also passed `pytest -m "compiled or not compiled" tests/modes` (25 passed) and `pytest tests/lint tests/modes` (73 passed).
- The build with `main` fails the extended audit: 52 uncached Cells are typed `object`.

### Microseconds per bond-point (valuation), compiled

| portfolio | items valued | level | main | P5 | P5 + infer | P5 + libm | P5 + both | export |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 1,000 bonds x 2 x 13 | 26 | 1 | 34.6 | 26.1 | 25.4 | 23.0 | **21.4** | 104.9 |
| 1,000 bonds x 2 x 13 | 26 | 2 | 261.1 | 145.2 | 136.5 | 116.4 | **103.6** | 761.0 |
| 10,000 bonds x 2 x 121 | 242 (full grid) | 1 | 21.0 | 15.3 | 15.3 | 13.1 | **12.8** | 69.3 |
| 10,000 bonds x 2 x 121 | 3 (scen 1, t = 0, 60, 120) | 2 | 196.3 | 109.5 | 102.2 | 87.7 | **82.2** | 566.9 |

The `main` column reproduces the Phase 4 table within 2.5% (34.9, 254.9, 21.1, 199.6).

### The Phase 3 profile (10,000 bonds x 121 dates x 2 scenarios, level 1), by stage

| | main | P5 | P5 + both | export |
|---|---:|---:|---:|---:|
| load (s) | 0.02 | 0.01 | 0.01 | 0.07 |
| inputs, Legs, limits (s) | 1.72 | 1.44 | 1.22 | 3.84 |
| free Bond items (s) | 0.05 | 0.06 | 0.06 | 0.06 |
| cash-flow outputs (s) | 2.43 | 2.36 | 2.34 | 3.24 |
| curve pre-flight (s) | 0.95 | 0.94 | 0.94 | 0.01 |
| valuation (s) | 50.75 | 37.06 | 31.03 | 167.69 |
| valuation output writing (s) | 9.68 | 9.71 | 9.70 | 9.99 |
| **total, in run.py** (s) | **65.65** | **51.63** | **45.35** | **184.95** |
| process wall time (s) | 66.22 | 52.23 | 45.93 | 185.55 |
| seconds per (scen_id, t) item | 0.250 | 0.193 | 0.168 | 0.734 |
| us per bond-point incl. output writing | 25.0 | 19.3 | 16.8 | 73.4 |
| RSS after Legs (MB) | 392 | 403 | 415 | 318 |
| **peak RSS** (MB) | **450** | **452** | **464** | **422** |

At level 2, extrapolated from the 3-item subset at the measured seconds per item, the full grid's valuation takes 8.2 min with main, 4.7 min with P5 and 3.6 min with P5 + both. Phase 4 measured 8.4 min.

### Reading the Phase 5 results

- **Typing the uncached Cells (#1) is most of the gain.**
  - The default P5 build cuts valuation by 27% at level 1 and 44% at level 2 at 10,000 bonds, and by 25% and 44% at 1,000 bonds.
  - The Phase 3 profile runs in 51.6 s end to end, against 65.7 s.
  - Level 2 gains most because its NewtonSafe iterations and risk passes call `Lib.discount_factor` / `compound_factor`, `Lib.stepwise_time` and `Dates.year_fraction` for every live flow. These are now typed C calls rather than Python calls on Python objects.
- **`use_libm` (#3) is the second gain:** valuation is another 14% faster at level 1 and 20% faster at level 2 than P5. The C `exp` / `pow` / `log` now serve `Lib.cxx_exp`, `cxx_pow` and `implied_rate`, which the spreaded curve (`equivalent_rate`) and the yield functions call per flow. The plain ZeroCurve discount, `math.exp(-r * tt)` in `Valuation.discount_core` and `zs_discount_kd`, is not rewritten (new issue #10).
- **`infer_types=True` (#2) adds little.**
  - On its own it gains 0% at level 1 and 7% at level 2 at 10,000 bonds. On top of `use_libm` it gains 2% and 6%; at 1,000 bonds, 7% and 11%.
  - It also speeds up setup: `inputs, Legs, limits` takes 1.22 s, against 1.44 s with P5 and 1.72 s with main.
  - It costs about 12 MB more RSS after Legs; the cause was not investigated.
  - It brings the risk of 32-bit C `long` locals (docs/mx2cy-issues.md #2). The four it creates in this model are bounded counters.
- **Best build (P5 + both).**
  - 12.8 us per bond-point at level 1, 39% below main, and 82.2 at level 2, 58% below main.
  - The Phase 3 profile takes 45.4 s end to end, against 65.7 s.
  - By the same per-bond-point cost, the plan's 10,000 x 121 x 10 configuration would take about 2.6 min of valuation at level 1. This is not measured. It is above the plan's estimate of 0.5 to 1.5 min, or 2 to 8 us per bond-point.
  - Valuation output writing (pandas `to_csv`, 9.7 s) is now 21% of the run.
- **Export and modelx modes are unaffected.** Export runs at 69.3 us per bond-point, against 68.9 in Phase 3, and its outputs are the reference that every compiled run matched.
- **Memory is unchanged.** The peak RSS is 450 to 469 MB in every build at 10,000 bonds. The typed `cpdef` functions add no per-item state.
- **What remains.**
  - The two ZeroCurve `exp` sites (#10).
  - The per-call overhead of the cached Cells: the flag check and the C-array read for every `(kd)` / `(p)` / `(b)` value.
  - The per-item fixed costs: item creation (about 4 ms per item, as the curve pre-flight shows), `result_frame` and `gc.collect()`.
  - None of these was profiled in Phase 5.
- **Annotate audit.** These are the lines of the generated `_mx_classes.py` that Cython's annotation marks as touching the Python C-API, counted over the Cells method bodies of each Space, in the order main → P5 → P5 + both:

  | Space | main | P5 | P5 + both |
  |---|---:|---:|---:|
  | Lib | 203 | 120 | 115 |
  | Dates | 364 | 256 | 152 |
  | Valuation | 805 | 762 | 697 |
  | Data | 1,144 | 1,062 | 1,041 |
  | Bond | 361 | 356 | 345 |
  | Legs | 283 | 283 | 270 |
  | Proj | 93 | 93 | 86 |

  Most of the lines left in the hot Cells are error checks and the cache machinery, not Python arithmetic.
- **Recommendation.**
  - Keep the default build (P5) as the reference for the tests.
  - Use `--directive infer_types=True --use-libm` for production runs once the build passes `pytest -m compiled`. The C `exp` / `log` / `pow` were measured bit-identical to `math` only with MSVC on Windows (see the modelx-cython docs), so re-check before using them on another platform.

## Memory streaming test

`tests/perf/test_memory.py` checks the streaming itself: over 50 or more
items (the demo inputs by default; a generated 1,000-bond portfolio under
marker `perf`) the number of live `_c_Valuation` instances is base + 1 while
an item exists and base after each `del` + `gc.collect()`, in export and in
compiled mode, and no `Bond` item is re-created. Its negative control shows
the items piling up, one per item, when the collector is disabled.
