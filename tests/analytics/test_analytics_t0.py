"""Phase 4 analytics at t = 0 (docs/model-contract.md 4.8): the model against pureql, bit for bit.

The oracle is ``helpers/pureql_val.py::pq_analytics``: pureql's own
``BondFunctions`` / ``CashFlows`` entry points with an EXPLICIT settlement
date ``s = bond.settlementDate(vdate)``, the bond built from the model's own
parsed inputs, the engine clean price taken with Settings moved (form (A) of
Phase 2), and the model's policies applied in one place (its module comment
lists them). The model must agree EXACTLY: floats bit for bit and of type
``float`` (NaN-aware), ints and bools with ``==`` and of the same type, and
where pureql raises, the model raises ``ValueError`` with the same message
(DECISIONS.md D-2: a mismatch is a defect, never a tolerance).

1. The contract's names: the Data quote arrays, the Lib additions and the
   Valuation Cells of 4.8, with their parameter names.
2. Lib: ``sign(x)`` and ``stepwise_time(...)`` (all three branches of
   ``_getStepwiseDiscountTime``) against pureql.
3. Data: the sparse quote arrays against prices.csv / yields.csv.
4. The quantlib-migration README headline yield ``0.030250400779423203``
   (``Bond.bondYield`` parity: NewtonSafe at accuracy 1e-8 on the engine
   clean price) and the risk at that yield, frozen in
   ``tests/data/analytics_pins.json``.
5. The tracer ``zcb-10y`` analytics keys of ``tests/data/tracer_bonds.json``
   (QuantLib 1.41) at the tiers recorded beside them: the Brent yield, the
   z-spread, the durations, convexity, BPV, YVBP and the clean price from the
   z-spread. The Newton yield is NOT compared with that golden (oracle skew
   OS-10: 1.41 predates the v1.43 IrrFinder derivative); it is compared with
   pureql, exactly, below.
6. Every bond of the demo and coverage input sets at t = 0 of both scenarios,
   under six settings variants (default; Brent; round-trip z-spread source;
   NT_RAISE; ERR_NAN; both): every per-bond Cells, the [D] Cells at four
   yields, the step times, and ``solve``.
7. The policies on a purpose-built set (``pureql_val.write_policy_inputs``):
   no bracket, maximum evaluations and checkSign failures under ERR_RAISE and
   ERR_NAN, NT_ENGINE / NT_RAISE on a matured bond with quotes, the Macaulay
   gate, small evaluation budgets on both solvers; and the IEEE edge yields
   of the [D] Cells (``1 + y/f == 0`` and beyond).
8. ``result_frame()`` by ``output_level``.

``tests/analytics/test_analytics_future.py`` repeats 6 at the future t,
replays the frozen analytics goldens and runs the generated portfolio.
"""

import json
import math

import numpy as np
import pytest

from helpers import pureql_val as pv
from helpers.approx import soft
from helpers.model import MODEL_DIR
from helpers.pureql_ref import pq_bond, pq_daycounter, serial

ROOT = MODEL_DIR.parents[1]
DEMO = ROOT / "bond_portfolio"
COVERAGE = ROOT / "tools" / "cy" / "sample_inputs"
DATA = ROOT / "tests" / "data"
SETS = {"demo": DEMO, "coverage": COVERAGE}
PINS = json.loads((DATA / "analytics_pins.json").read_text(encoding="utf-8"))
TRACER = json.loads((DATA / "tracer_bonds.json").read_text(encoding="utf-8"))

#: Yields of the [D] Cells: negative, zero, ordinary and high.
Y_GRID = (-0.005, 0.0, 0.0325, 0.11)

#: Settings variants (overrides of the Data References) of the every-bond comparison.
VARIANTS = {
    "default": {},
    "brent": {"yield_solver": pv.YIELD_BRENT},
    "roundtrip": {"zspread_price_source": 1},
    "nt_raise": {"nontradable_policy": pv.NT_RAISE},
    "err_nan": {"solver_error_policy": pv.ERR_NAN},
    "raise_nan": {"nontradable_policy": pv.NT_RAISE, "solver_error_policy": pv.ERR_NAN},
}

HEADLINE_YIELD = 0.030250400779423203


def model_for(set_model, name, variant):
    """The module's instance of input set ``name`` under a settings variant."""
    return set_model(f"{name}_{variant}", SETS[name], **VARIANTS[variant])


def every_bond(model, scen_id, t, ys=Y_GRID, settings=None):
    """Messages for every bond of ``model`` at (scen_id, t) (all of 4.8, the [D] Cells at ``ys``)."""
    q = pv.quote_inputs(model)
    c = pv.curve_inputs(model, scen_id, t)
    bad = []
    for b in range(model.Data.n_bonds()):
        bad += pv.compare_analytics(model, scen_id, t, b, ys, settings, q, c)[0]
    return bad


# --------------------------------------------------------------------------- 1. the contract's names
DATA_CELLS = ("px_slot_arr", "px_val_arr", "px_type_arr", "yl_slot_arr", "yl_val_arr")
LIB_CELLS = {"sign": ("x",),
             "stepwise_time": ("is_coupon", "d", "acc_start", "ref_start", "ref_end", "dc", "npv_date",
                               "last_date")}
VALUATION_CELLS = {
    "price_in": ("b",), "price_type_in": ("b",), "yield_in": ("b",), "ydc": ("b",), "ycomp": ("b",),
    "yfreq": ("b",), "ystep": ("p",),
    "npv_yield": ("b", "y"), "simple_duration_y": ("b", "y"), "modified_duration_y": ("b", "y"),
    "macaulay_duration_y": ("b", "y"), "convexity_y": ("b", "y"), "bpv_y": ("b", "y"), "yvbp_y": ("b", "y"),
    "dirty_from_yield": ("b", "y"), "clean_from_yield": ("b", "y"),
    "y_price": ("b",), "y_price_type": ("b",), "y_target": ("b",), "sign_ok": ("b",), "z_target": ("b",),
    "solve": ("b", "kind"), "ytm": ("b",), "zspread": ("b",), "risk_yield": ("b",),
    "duration_simple": ("b",), "duration_modified": ("b",), "duration_macaulay": ("b",), "convexity": ("b",),
    "bpv": ("b",), "yvbp": ("b",), "dirty_at_yield_in": ("b",), "clean_at_yield_in": ("b",),
}


def test_the_contract_names_exist(set_model):
    """Every Phase 4 name of contract 4.8, with the contract's parameter names; [D] Cells are cached."""
    m = set_model("demo_default", DEMO)
    with soft("contract 4.8 names") as s:
        for name in DATA_CELLS:
            s.check(name in m.Data.cells, f"Data has no Cells {name!r}")
        for name, params in LIB_CELLS.items():
            if s.check(name in m.Lib.cells, f"Lib has no Cells {name!r}"):
                got = tuple(m.Lib.cells[name].parameters)
                s.check(got == params, f"Lib.{name} has parameters {got}, the contract says {params}")
        space = m.Valuation
        for name, params in VALUATION_CELLS.items():
            if not s.check(name in space.cells, f"Valuation has no Cells {name!r}"):
                continue
            got = tuple(space.cells[name].parameters)
            s.check(got == params, f"Valuation.{name} has parameters {got}, the contract says {params}")
            if "y" in params:
                s.check(space.cells[name].is_cached, f"Valuation.{name} is a [D] Cells and must be cached")


# --------------------------------------------------------------------------- 2. Lib
def test_lib_sign(set_model):
    """``Lib.sign(x)`` == pureql ``_sign`` (cashflows.py:311-324), NaN answering -1 like C++."""
    lib = set_model("demo_default", DEMO).Lib
    assert "sign" in lib.cells, "Lib has no Cells 'sign' (docs/model-contract.md 4.8)"
    with soft("Lib.sign") as s:
        for x in (-2.5, -1e-300, -0.0, 0.0, 5e-324, 1e-300, 3.0, float("inf"), float("-inf"), float("nan")):
            e = pv.run_pq(pv._sign, x)
            g = pv.run_model(lib.cells["sign"], x)
            s.check(pv.same_outcome(g, e), f"sign({x!r}): model {pv.show(g)} vs pureql {pv.show(e)}")


@pytest.mark.parametrize("name", list(SETS))
def test_lib_stepwise_time(set_model, name):
    """``Lib.stepwise_time`` == ``_getStepwiseDiscountTime`` (cashflows.py:327-378) on every flow of a set.

    For each flow ``p`` of each bond, under every v1 day counter, at npv
    dates and last dates that take all three branches: a coupon whose accrual
    start is not ``last_date`` (a stub, a settlement inside a period), a
    coupon whose accrual start is ``last_date``, and a non-coupon with
    ``last_date == npv_date`` (the faked one-year reference period) or not.
    """
    m = set_model(f"{name}_default", SETS[name])
    lib = m.Lib
    assert "stepwise_time" in lib.cells, "Lib has no Cells 'stepwise_time' (docs/model-contract.md 4.8)"
    cell = lib.cells["stepwise_time"]
    lg = m.Legs
    lo, date, kind = lg.cf_lo_arr().tolist(), lg.cf_date_arr().tolist(), lg.cf_kind_arr().tolist()
    acc_s, ref_s, ref_e = lg.cf_acc_start_arr().tolist(), lg.cf_ref_start_arr().tolist(), lg.cf_ref_end_arr().tolist()
    branches = set()
    with soft(f"Lib.stepwise_time on {name}") as s:
        for b in range(m.Data.n_bonds()):
            leg = pq_bond(m, b).cashflows()
            for i, cf in enumerate(leg):
                p = lo[b] + i
                d = date[p]
                coupon = kind[p] == 0
                npv_dates = {d - 30, d - 400}
                lasts = {d - 30}
                if i > 0:
                    lasts.add(date[p - 1])
                if coupon:
                    lasts.add(acc_s[p])
                    npv_dates.add(acc_s[p])
                for dc in (1, 2, 10, 11, 12):
                    for npv_date in npv_dates:
                        for last in lasts | {npv_date}:
                            e = pv.run_pq(pv._getStepwiseDiscountTime, cf, pq_daycounter(dc), pv.pq_date(npv_date),
                                          pv.pq_date(last))
                            g = pv.run_model(cell, 1 if coupon else 0, d, acc_s[p], ref_s[p], ref_e[p], dc,
                                             npv_date, last)
                            branches.add("coupon-stub" if coupon and last != acc_s[p] else
                                         "coupon-regular" if coupon else
                                         "non-coupon-fake-year" if last == npv_date else "non-coupon")
                            s.check(pv.same_outcome(g, e),
                                    f"stepwise_time(p={p}, dc={dc}, npv={npv_date}, last={last}): "
                                    f"model {pv.show(g)} vs pureql {pv.show(e)}")
    assert branches == {"coupon-stub", "coupon-regular", "non-coupon-fake-year", "non-coupon"}


# --------------------------------------------------------------------------- 3. Data: the quote arrays
@pytest.mark.parametrize("name", list(SETS))
def test_data_quote_arrays(set_model, name):
    """``px_slot/val/type_arr`` and ``yl_slot/val_arr`` hold exactly prices.csv and yields.csv.

    A (scen_id, t) without quotes has slot -1; the slots of the others are
    distinct rows; absent entries are NaN (and type -1).
    """
    m = set_model(f"{name}_default", SETS[name])
    d = m.Data
    missing = [n for n in DATA_CELLS if n not in d.cells]
    assert not missing, f"Data has no Cells {missing} (docs/model-contract.md 4.8)"
    q = pv.quote_inputs(m)
    keys = list(d.bond_keys())
    S, T = d.n_scen(), d.n_times()
    arrays = {n: d.cells[n]() for n in DATA_CELLS}
    for n in ("px_slot_arr", "px_type_arr", "yl_slot_arr"):
        assert isinstance(arrays[n], np.ndarray) and arrays[n].dtype == np.int64, f"{n} is not an int64 array"
    for n in ("px_val_arr", "yl_val_arr"):
        assert isinstance(arrays[n], np.ndarray) and arrays[n].dtype == np.float64, f"{n} is not a float64 array"
    assert arrays["px_slot_arr"].shape == (S, T) and arrays["yl_slot_arr"].shape == (S, T)
    with soft(f"quote arrays of {name}") as s:
        for kind, slot_n, val_n, typ_n in (("price", "px_slot_arr", "px_val_arr", "px_type_arr"),
                                           ("yield", "yl_slot_arr", "yl_val_arr", None)):
            used = {}
            for sc in range(1, S + 1):
                for t in range(T):
                    slot = int(arrays[slot_n][sc - 1, t])
                    quoted = {k: q[kind][(sc, t, k)] for k in keys if (sc, t, k) in q[kind]}
                    if not quoted:
                        s.check(slot == -1, f"{slot_n}[{sc - 1}, {t}] = {slot}: no {kind} there, expected -1")
                        continue
                    if not s.check(slot >= 0 and slot not in used, f"{slot_n}[{sc - 1}, {t}] = {slot} "
                                   f"(already used by {used.get(slot)})"):
                        continue
                    used[slot] = (sc, t)
                    s.check(arrays[val_n].shape[1] == len(keys), f"{val_n} has {arrays[val_n].shape[1]} columns")
                    for b, k in enumerate(keys):
                        v = float(arrays[val_n][slot, b])
                        if k in quoted:
                            e = quoted[k][0] if kind == "price" else quoted[k]
                            s.check(pv.same(v, e), f"{val_n}[{slot}, {b}] = {v!r}, {kind}s.csv says {e!r}")
                            if typ_n:
                                got_type = int(arrays[typ_n][slot, b])
                                s.check(got_type == quoted[k][1],
                                        f"{typ_n}[{slot}, {b}] = {got_type}, expected {quoted[k][1]}")
                        else:
                            s.check(math.isnan(v), f"{val_n}[{slot}, {b}] = {v!r}, expected NaN (no quote)")
                            if typ_n:
                                s.check(int(arrays[typ_n][slot, b]) == -1, f"{typ_n}[{slot}, {b}] is not -1")
            s.check(len(used) == len({(sc, t) for sc, t, _ in q[kind]}), f"{kind}: slot count")


# --------------------------------------------------------------------------- 4. the README headline yield
def test_headline_yield_and_risk(new_model):
    """``0.030250400779423203`` (quantlib-migration README.md:60-79): NewtonSafe at 1e-8 on the engine clean price.

    The demo HEADLINE_10Y at (1, 0) has no input price, so ``y_price`` is the
    engine clean price (``108.34563953853349``) and ``ytm`` with
    ``yield_accuracy = 1e-8`` is ``Bond.bondYield``'s root, bit for bit; the
    pins also hold the durations, convexity, BPV, YVBP and the prices at that
    yield, computed by pureql (tests/data/analytics_pins.json).
    """
    pins = PINS["headline"]
    assert pins["readme_literal"] == pins["bond_bondYield"] == HEADLINE_YIELD
    m = new_model("Headline", DEMO, yield_accuracy=1e-8)
    b = list(m.Data.bond_keys()).index(pins["bond_key"])
    item = m.Valuation[1, 0]
    st = pv.analytics_settings(m)
    # live pureql still reproduces the pins (no model involved)
    live = pv.pq_analytics(m, 1, 0, b, (HEADLINE_YIELD,), st, steps=False)
    for k, v in pins["bond"].items():
        assert pv.same_outcome(live["bond"][k], pv.decode_golden(v)), f"pureql drifted on {k}"
    # the model, bit for bit
    with soft("headline analytics") as s:
        for k, v in pins["bond"].items():
            cell = pv.analytics_cell(item, k)
            if not s.check(cell is not None, f"MISSING Valuation.{k}"):
                continue
            g, e = pv.run_model(cell, b), pv.decode_golden(v)
            s.check(pv.same_outcome(g, e), f"{k}: model {pv.show(g)} vs pin {pv.show(e)}")
        for k, v in pins["y_at_ytm"].items():
            cell = pv.analytics_cell(item, k)
            if not s.check(cell is not None, f"MISSING Valuation.{k}"):
                continue
            g, e = pv.run_model(cell, b, HEADLINE_YIELD), pv.decode_golden(v)
            s.check(pv.same_outcome(g, e), f"{k}({HEADLINE_YIELD!r}): model {pv.show(g)} vs pin {pv.show(e)}")
    assert pv.same(pv.analytics_cell(item, "ytm")(b), HEADLINE_YIELD)


def test_headline_yield_at_the_default_accuracy(set_model):
    """At the contract default (``BondFunctions.bondYield``: 1e-10) NewtonSafe lands on the same root here."""
    m = set_model("demo_default", DEMO)
    b = list(m.Data.bond_keys()).index("HEADLINE_10Y")
    e = pv.decode_golden(PINS["headline"]["ytm_default_accuracy"])
    cell = pv.analytics_cell(m.Valuation[1, 0], "ytm")
    assert cell is not None, "Valuation has no Cells 'ytm'"
    g = pv.run_model(cell, b)
    assert pv.same_outcome(g, e), f"model {pv.show(g)} vs pureql {pv.show(e)}"


# --------------------------------------------------------------------------- 5. zcb-10y tracer goldens (QuantLib 1.41)
#: tracer key -> (Valuation Cells, how it is called)
TRACER_KEYS = {
    "durationSimple": "duration_simple", "durationModified": "duration_modified",
    "durationMacaulay": "duration_macaulay", "convexity": "convexity", "basisPointValue": "bpv",
    "yieldValueBasisPoint": "yvbp", "zSpread": "zspread", "yieldBrent": "ytm",
    "cleanPriceFromZSpread": "clean_from_z",
}


@pytest.mark.parametrize("scen_id,curve", [(1, "flat"), (2, "zero")])
def test_zcb_10y_tracer_analytics(new_model, scen_id, curve):
    """The demo's ZCB_10Y at (scen_id, 0) is the tracer's zcb-10y on its curve: the 1.41 analytics at their tiers.

    How quantlib-migration produced them (tests/helpers/scenario.py
    ``_bond_analytics``): clean price 80, yield conventions Actual365Fixed /
    Compounded / Annual, the risk measures at the quoted yield 2.5%, the
    yield from ``yieldBrent`` and the z-spread (Compounded / Annual) both at
    accuracy 1e-12, guess 0.05 and 0.0. The demo carries the same quotes in
    prices.csv / yields.csv; the model runs with ``yield_solver`` = Brent and
    both accuracies at 1e-12. Tiers as recorded: "value" = T2 (relative
    1e-12, floor 1e-14), "solver" = absolute 1e-11. ``cleanPriceFromZSpread``
    is the price at the ORACLE's z-spread, so the model is asked at that same
    spread (``clean_from_z(b, zSpread)``). The Newton yield is pureql-only (OS-10).
    """
    case = TRACER["cases"][f"bonds/zerocouponbond[zcb-10y,{curve}]"]
    params, result, tiers = case["params"], case["result"], case["tiers"]
    assert (params["yieldDayCounter"], params["compounding"], params["frequency"], params["cleanPrice"],
            params["quotedYield"]) == ("Actual365Fixed", "Compounded", "Annual", 80.0, 0.025)
    m = new_model("Zcb10y", DEMO, yield_solver=pv.YIELD_BRENT, yield_accuracy=1e-12, zspread_accuracy=1e-12)
    b = list(m.Data.bond_keys()).index("ZCB_10Y")
    item = m.Valuation[scen_id, 0]
    missing = [c for c in set(TRACER_KEYS.values()) | {"price_in", "price_type_in", "yield_in", "risk_yield"}
               if pv.analytics_cell(item, c) is None]
    assert not missing, f"Valuation has no Cells {sorted(missing)} (docs/model-contract.md 4.8)"
    # the fixture is the golden's
    assert pv.same(item.cells["price_in"](b), 80.0) and item.cells["price_type_in"](b) == pv.PRICE_CLEAN
    assert pv.same(item.cells["yield_in"](b), 0.025) and pv.same(item.cells["risk_yield"](b), 0.025)
    assert (item.spread_comp(), item.spread_freq()) == (pv.COMP_COMPOUNDED, 1)
    with soft(f"zcb-10y {curve} vs QuantLib 1.41 goldens") as s:
        for key, cell in TRACER_KEYS.items():
            if key == "cleanPriceFromZSpread":
                got = item.cells[cell](b, float(result["zSpread"]))
            else:
                got = item.cells[cell](b)
            if tiers[key] == "value":
                s.t2(got, result[key], f"{key} ({cell})")
            elif tiers[key] == "solver":
                s.t2_solver(got, result[key], f"{key} ({cell})")
            else:
                s.error(f"{key}: unexpected tier {tiers[key]!r}")
    # and model == pureql exactly, on every analytics output of the bond
    pv.report_analytics(pv.compare_analytics(m, scen_id, 0, b, (0.025,))[0], f"zcb-10y {curve} vs pureql")


# --------------------------------------------------------------------------- 6. every bond at t = 0
@pytest.mark.parametrize("variant", list(VARIANTS))
@pytest.mark.parametrize("scen_id", [1, 2])
@pytest.mark.parametrize("name", list(SETS))
def test_every_bond_t0(set_model, name, scen_id, variant):
    """Every 4.8 Cells of every bond at (scen_id, 0) == pureql, under a settings variant."""
    m = model_for(set_model, name, variant)
    pv.report_analytics(every_bond(m, scen_id, 0), f"{name} ({scen_id}, 0) {variant}")


@pytest.mark.parametrize("name", list(SETS))
def test_the_input_sets_cover_the_cases(set_model, name):
    """Precondition of the every-bond tests (pureql only): what the two sets exercise, over all points."""
    m = set_model(f"{name}_default", SETS[name])
    q = pv.quote_inputs(m)
    seen = set()
    for sc in range(1, m.Data.n_scen() + 1):
        for t in range(m.Data.n_times()):
            c = pv.curve_inputs(m, sc, t)
            for b in range(m.Data.n_bonds()):
                e = pv.pq_analytics(m, sc, t, b, (), None, q, c, steps=False)
                f = e["facts"]
                seen.add(("comp", f["ycomp"]))
                seen.add(("tradable", f["tradable"]))
                if f["has_price"]:
                    seen.add(("price_type", e["bond"]["price_type_in"][1]))
                    seen.add(("zspread", e["bond"]["zspread"][0], f["tradable"]))
                if f["has_yield"]:
                    seen.add(("yield", f["tradable"]))
                if f["tradable"] and f["ycomp"] != pv.COMP_COMPOUNDED:
                    seen.add(("macaulay gate", e["bond"]["duration_macaulay"][0]))
    want = {("tradable", True), ("price_type", pv.PRICE_CLEAN), ("zspread", "ok", True)}
    if name == "coverage":
        want |= {("comp", c) for c in pv.COMPOUNDINGS} | {("tradable", False), ("price_type", pv.PRICE_DIRTY),
                                                          ("yield", True), ("yield", False),
                                                          ("macaulay gate", "err")}
    else:
        want |= {("tradable", False), ("yield", True)}
    assert want <= seen, f"{name} does not exercise {sorted(want - seen, key=repr)}"


# --------------------------------------------------------------------------- 7. the policies
@pytest.fixture(scope="module")
def policy_inputs(tmp_path_factory):
    return pv.write_policy_inputs(tmp_path_factory.mktemp("analytics_policy"))


#: (label, settings) of the policy matrix. Every combination of the two policies on
#: both solvers, and evaluation budgets that stop the bracketing (2, 4) and the solver (4, 6, 7).
POLICY_SETTINGS = [
    (f"nt{nt}_err{err}_solver{sv}", {"nontradable_policy": nt, "solver_error_policy": err, "yield_solver": sv})
    for nt in (pv.NT_ENGINE, pv.NT_RAISE) for err in (pv.ERR_RAISE, pv.ERR_NAN)
    for sv in (pv.YIELD_NEWTON, pv.YIELD_BRENT)
] + [
    (f"maxeval{n}_err{err}_solver{sv}", {"yield_max_evaluations": n, "zspread_max_evaluations": n,
                                          "solver_error_policy": err, "yield_solver": sv})
    for n in (2, 4, 7) for err in (pv.ERR_RAISE, pv.ERR_NAN) for sv in (pv.YIELD_NEWTON, pv.YIELD_BRENT)
] + [
    ("zspread_source1_nan", {"zspread_price_source": 1, "solver_error_policy": pv.ERR_NAN}),
    ("guess_and_accuracy", {"yield_guess": 0.2, "yield_accuracy": 1e-12, "zspread_guess": 0.01,
                            "zspread_accuracy": 1e-12}),
]


def test_the_policy_set_reaches_every_failure(policy_inputs, new_model):
    """Precondition (pureql only): each solver failure, the NT raise and the Macaulay raise occur in the matrix."""
    m = new_model("PolicyPre", policy_inputs)
    q = pv.quote_inputs(m)
    messages = set()
    for _, over in POLICY_SETTINGS:
        st = pv.analytics_settings(m, **over)
        for t in range(m.Data.n_times()):
            for b in range(m.Data.n_bonds()):
                e = pv.pq_analytics(m, 1, t, b, (), st, q, steps=False)
                for k in ("ytm", "zspread", "duration_macaulay", "bpv"):
                    o = e["bond"][k]
                    if o[0] == "err":
                        messages.add(o[2])
    for want in ("unable to bracket root", "maximum number of function evaluations",
                 "the given cash flows cannot result in the given market price due to their sign",
                 "compounded rate required", "non tradable at", "positive compound factor required"):
        assert any(msg.startswith(want) for msg in messages), f"the policy set never raises {want!r}: {messages}"


@pytest.mark.parametrize("label,settings", POLICY_SETTINGS, ids=[p[0] for p in POLICY_SETTINGS])
def test_policy_matrix(new_model, policy_inputs, label, settings):
    """Every bond of the policy set, both dates, under each setting: model == pureql with the policies applied."""
    m = new_model("Policy", policy_inputs, **settings)
    bad = []
    for t in range(m.Data.n_times()):
        bad += every_bond(m, 1, t, ys=(0.03,))
    pv.report_analytics(bad, f"policy set {label}")


def test_nt_policy_on_the_matured_bond(new_model, policy_inputs):
    """N == 0 with a price and a yield: NaN / 0.0 under NT_ENGINE, pureql's raise under NT_RAISE (contract 4.8).

    ``risk_yield`` is gated with the rest even though the bond has an input
    yield: the contract lists it among the NT outputs ("Under NT_RAISE:
    pureql's raise").
    """
    eng = new_model("NtEngine", policy_inputs)
    rai = new_model("NtRaise", policy_inputs, nontradable_policy=pv.NT_RAISE)
    b = list(eng.Data.bond_keys()).index("Z_MATURED")
    nan_cells = ("ytm", "zspread", "risk_yield", "duration_simple", "duration_modified", "duration_macaulay",
                 "convexity", "bpv", "yvbp")
    with soft("NT policy") as s:
        for name in nan_cells:
            cell = pv.analytics_cell(eng.Valuation[1, 0], name)
            if s.check(cell is not None, f"MISSING Valuation.{name}"):
                g = pv.run_model(cell, b)
                s.check(g[0] == "ok" and isinstance(g[1], float) and math.isnan(g[1]),
                        f"NT_ENGINE {name}: {pv.show(g)}, expected NaN")
        for name, args in (("dirty_at_yield_in", ()), ("clean_at_yield_in", ()), ("dirty_from_yield", (0.03,)),
                           ("clean_from_yield", (0.03,))):
            cell = pv.analytics_cell(eng.Valuation[1, 0], name)
            if s.check(cell is not None, f"MISSING Valuation.{name}"):
                g = pv.run_model(cell, b, *args)
                s.check(pv.same_outcome(g, ("ok", 0.0)), f"NT_ENGINE {name}: {pv.show(g)}, expected 0.0")
        for name in ("ytm", "zspread", "risk_yield", "duration_modified", "dirty_from_yield"):
            cell = pv.analytics_cell(rai.Valuation[1, 0], name)
            if s.check(cell is not None, f"MISSING Valuation.{name}"):
                g = pv.run_model(cell, b, *((0.03,) if name == "dirty_from_yield" else ()))
                s.check(g[0] == "err" and g[1] is ValueError and g[2].startswith("non tradable at "),
                        f"NT_RAISE {name}: {pv.show(g)}, expected pureql's 'non tradable at ...'")


def test_macaulay_gate(new_model, policy_inputs):
    """Macaulay with a Simple yield: NaN under ERR_NAN, 'compounded rate required' under ERR_RAISE."""
    for err, expect in ((pv.ERR_NAN, ("ok", pv.NAN)), (pv.ERR_RAISE, ("err", ValueError, "compounded rate required"))):
        m = new_model("Macaulay", policy_inputs, solver_error_policy=err)
        b = list(m.Data.bond_keys()).index("F_SIMPLE_YLD")
        cell = pv.analytics_cell(m.Valuation[1, 0], "duration_macaulay")
        assert cell is not None, "Valuation has no Cells 'duration_macaulay'"
        g = pv.run_model(cell, b)
        assert pv.same_outcome(g, expect), f"ERR policy {err}: model {pv.show(g)}, expected {pv.show(expect)}"
        # the rest of the risk is computed at the input yield
        dm = pv.run_model(m.Valuation[1, 0].cells["duration_modified"], b)
        assert dm[0] == "ok" and not math.isnan(dm[1])


@pytest.mark.parametrize("scen_id,t", [(1, 0), (2, 0), (1, 3), (2, 3)])
def test_edge_yields(set_model, scen_id, t):
    """The [D] Cells at IEEE edge yields: ``1 + y/f == 0`` (IEEE-11/13), y = -1, -0.99, -2, 1.5, 25, +-1e-300.

    pureql answers inf / nan there through ``_cxx`` rather than raising
    (measured at (1, 0) of the coverage set: ``npv_yield`` is inf on 13 of
    the 136 bond-yields and nan on 7), and the model's ``lib.cxx_*`` sites
    must answer the same.
    """
    m = model_for(set_model, "coverage", "default")
    q = pv.quote_inputs(m)
    c = pv.curve_inputs(m, scen_id, t)
    bad = []
    for b in range(m.Data.n_bonds()):
        yfreq = int(m.Data.b_yfreq_arr()[b])
        ys = (-0.99, -1.0, -2.0, -float(max(yfreq, 1)), 1.5, 25.0, 1e-300, -1e-300)
        exp = pv.pq_analytics(m, scen_id, t, b, ys, None, q, c, steps=False)
        exp = {"bond": {}, "y": exp["y"], "p": {}, "k": {}}
        got = pv.analytics_model_values(m.Valuation[scen_id, t], b, exp)
        bad += pv.analytics_mismatches(got, exp, f"({scen_id}, {t}) b={b}")
    pv.report_analytics(bad, f"edge yields at ({scen_id}, {t})")


# --------------------------------------------------------------------------- 8. result_frame by output_level
LEVEL2 = ("ytm", "risk_yield", "duration_simple", "duration_modified", "duration_macaulay", "convexity", "bpv",
          "yvbp")


@pytest.mark.parametrize("level", [1, 2, 3])
def test_result_frame_by_output_level(new_model, level):
    """Level 2 adds ytm, risk_yield and the risk measures; level 3 adds zspread; each column is its Cells.

    Run under ERR_NAN: under ERR_RAISE a bond whose yield is not Compounded
    raises from ``duration_macaulay`` (the contract's Macaulay rule), so a
    level-2 frame of the coverage set would raise.
    """
    m = new_model("Frame", COVERAGE, output_level=level, solver_error_policy=pv.ERR_NAN)
    with soft(f"result_frame at output_level {level}") as s:
        for sc, t in ((1, 0), (2, 3)):
            item = m.Valuation[sc, t]
            g = pv.run_model(item.cells["result_frame"])
            if not s.check(g[0] == "ok", f"result_frame() at ({sc}, {t}) raises {pv.show(g)}"):
                continue
            df = g[1]
            want = (LEVEL2 if level >= 2 else ()) + (("zspread",) if level >= 3 else ())
            absent = (LEVEL2 + ("zspread",)) if level == 1 else (("zspread",) if level == 2 else ())
            for col in want:
                if not s.check(col in df.columns, f"level {level}: no column {col!r}"):
                    continue
                cell = pv.analytics_cell(item, col)
                if not s.check(cell is not None, f"MISSING Valuation.{col}"):
                    continue
                exp = [cell(b) for b in range(m.Data.n_bonds())]
                s.check(pv.same(df[col].tolist(), exp), f"({sc}, {t}) column {col!r} is not {col}(b)")
            for col in absent:
                s.check(col not in df.columns, f"level {level}: column {col!r} should not be there")
            s.check(list(df["bond_key"]) == list(m.Data.bond_keys()), "bond_key column")


def test_settlement_dates_are_the_pureql_ones(set_model):
    """Harness check: the oracle's settlement date is the model's ``settle(b)`` (Phase 2) at every coverage point."""
    m = model_for(set_model, "coverage", "default")
    for sc in (1, 2):
        for t in range(m.Data.n_times()):
            item = m.Valuation[sc, t]
            for b in range(m.Data.n_bonds()):
                with pv.pq_settings():
                    s = serial(pq_bond(m, b).settlementDate(pv.pq_date(int(m.Data.val_date_arr()[t]))))
                assert item.settle(b) == s
