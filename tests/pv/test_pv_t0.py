"""Valuation (docs/model-contract.md 4.7, Phase 2 core): the model against pureql, bit for bit.

The oracle is ``helpers/pureql_val.py``: pureql computes every contract output
of a bond from the model's own parsed inputs, in two independent forms (the
Settings-moved engine form and the explicit-date form), which are checked
against each other first. The model must then agree with pureql EXACTLY:
floats bit for bit and of type ``float`` (NaN-aware), ints and bools with
``==`` and of the same Python type, and where pureql raises, the model raises
``ValueError`` with the same message (modelx wraps it in ``FormulaError``;
``mx.get_error()`` is the original). DECISIONS.md D-2: a mismatch is a
defect, never a tolerance.

1. The quantlib-migration README headline bond (README.md:61-80,
   tests/meta/test_documentation_set.py:306-392): NPV ``108.36776235612268``
   and clean price ``108.34563953853349``, and equality with pureql.
2. ``bonds.cpp`` testCachedZero (quantlib-migration
   tests/unit/test_bonds.py:1002-1077): the three cached clean prices at the
   upstream tolerance, and model == pureql exactly.
3. Every bond of the demo and coverage input sets at EVERY (scen_id, t):
   both curve types, with and without spread, matured, non-tradable and
   forward-start bonds; every per-bond output, ``first_live`` per role, the
   role values, ``zdisc``, ``settle_cal``, prices from a z-spread over a z
   grid (negative, zero, positive and one extreme), the aggregates and
   ``result_frame``; the NT policy both ways; the curve Cells; and a curve
   that does not cover the bonds (pureql's range errors).
4. A generated portfolio (1,000 bonds, 2 scenarios x 3 dates, fixed seed):
   t = 0 in the default run, every t under ``slow``.
5. The flow-inclusion flag matrix R x T x F on bonds with a cash flow on the
   valuation date, on the settlement date and in between (adapted from
   ``cashflows.cpp`` testSettings, quantlib-migration
   tests/unit/test_cashflows.py:377-497), and the check that assigning a
   Data Reference clears the cached Valuation values.

Frozen goldens of pureql (``tests/data/pv_demo.json``,
``tests/data/pv_coverage.json``) pin both sides against drift.
"""

import datetime
import importlib.util
import itertools
import json
import math

import pytest

from helpers import pureql_val as pv
from helpers.approx import soft
from helpers.model import MODEL_DIR
from helpers.pureql_ref import pq_bdc, pq_calendar, pq_date, pq_time_unit, ql, serial

ROOT = MODEL_DIR.parents[1]
DEMO = ROOT / "bond_portfolio"
COVERAGE = ROOT / "tools" / "cy" / "sample_inputs"
DATA = ROOT / "tests" / "data"
SETS = {"demo": DEMO, "coverage": COVERAGE}

_spec = importlib.util.spec_from_file_location("generate_inputs", DEMO / "generate_inputs.py")
gen = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gen)

#: z-spreads for the ``*_from_z`` prices: negative, zero, positive, and one extreme
#: (-0.5 drives a Simple / SimpleThenCompounded spread convention to a
#: non-positive compound factor at long times, which pureql refuses).
Z_GRID = (-0.5, -0.0125, 0.0, 0.0075, 0.04)
Z_SHORT = (-0.0125, 0.0)

HEADLINE_NPV = 108.36776235612268
HEADLINE_CLEAN = 108.34563953853349

#: The generated portfolio of item 4.
GEN_BONDS, GEN_SCEN, GEN_TIMES, GEN_SEED = 1000, 2, 3, 20261011

RESULT_COLUMNS = ("bond_key", "settlement_date", "notional", "npv", "settlement_value", "dirty_price",
                  "clean_price", "accrued_amount", "market_value", "tradable", "expired")


# --------------------------------------------------------------------------- helpers
def iso(d):
    return (datetime.date(1899, 12, 30) + datetime.timedelta(days=int(d))).isoformat()


def points(model):
    return [(s, t) for s in range(1, model.Data.n_scen() + 1) for t in range(model.Data.n_times())]


def zdisc_mismatches(model, item, scen_id, t, c, bonds):
    """``zdisc(p)`` for every flow on or after vdate of every spread bond."""
    out = []
    curve = pv.pq_curve(model, scen_id, t, c)
    lo_arr = model.Legs.cf_lo_arr()
    dates = model.Legs.cf_date_arr()
    for b in bonds:
        spread = pv.bond_spread(model, scen_id, t, b)
        if spread is None:
            continue
        zc = pv.pq_spreaded(curve, spread, c["sp_comp"], c["sp_freq"])
        for p in range(int(lo_arr[b]), int(lo_arr[b + 1])):
            d = int(dates[p])
            if d < c["vdate"]:
                continue
            e = pv.run_pq(zc.discount, pq_date(d))
            g = pv.run_model(pv.model_cells(item, "zdisc"), p)
            if not pv.same_outcome(g, e):
                out.append(f"({scen_id}, {t}) zdisc({p}) [b={b}]: model {pv.show(g)} vs pureql {pv.show(e)}")
    return out


def settle_cal_mismatches(item, c):
    """``settle_cal(cal, nsd)`` == ``Calendar.advance(v, nsd, Days, Following, False)`` for every v1 calendar."""
    out = []
    v = pq_date(c["vdate"])
    for cal in range(4):
        for nsd in range(8):
            e = pv.run_pq(lambda: serial(pq_calendar(cal).advance(v, nsd, pq_time_unit(0), pq_bdc(0), False)))
            g = pv.run_model(pv.model_cells(item, "settle_cal"), cal, nsd)
            if not pv.same_outcome(g, e):
                out.append(f"settle_cal({cal}, {nsd}) at {c['vdate']}: model {pv.show(g)} vs pureql {pv.show(e)}")
    return out


def seq_total(exps, key):
    """The sequential ``+=`` of one output in bond order; the first error in bond order if one raises."""
    total = 0.0
    for b in sorted(exps):
        o = exps[b]["bond"][key]
        if o[0] == "err":
            return o
        total += o[1]
    return ("ok", total)


def aggregate_mismatches(model, item, exps):
    """The aggregates and ``result_frame`` against the per-bond pureql values (bitwise)."""
    out = []
    # accrued_total sums the accrued interest in CURRENCY (accrued_cash), like the other three totals;
    # contract 4.7 says only "sequential sums in bond order" (reported as a contract clarification).
    for cell, key in (("npv_total", "npv"), ("mv_total", "market_value"), ("sv_total", "settlement_value"),
                      ("accrued_total", "accrued_cash")):
        e = seq_total(exps, key)
        g = pv.run_model(pv.model_cells(item, cell))
        if not pv.same_outcome(g, e):
            out.append(f"{cell}(): model {pv.show(g)} vs pureql {pv.show(e)}")
    for cell, key in (("n_expired", "is_expired"), ("n_tradable", "is_tradable")):
        e = ("ok", int(sum(1 for b in exps if exps[b]["bond"][key][1])))
        g = pv.run_model(pv.model_cells(item, cell))
        if not pv.same_outcome(g, e):
            out.append(f"{cell}(): model {pv.show(g)} vs pureql {pv.show(e)}")
    if any(o[0] == "err" for x in exps.values() for o in x["bond"].values()):
        return out  # result_frame needs every value; its raise is not specified
    g = pv.run_model(pv.model_cells(item, "result_frame"))
    if g[0] == "err":
        return out + [f"result_frame() raises {g[1].__name__}({g[2]!r})"]
    df = g[1]
    missing = [col for col in RESULT_COLUMNS if col not in df.columns]
    if missing:
        return out + [f"result_frame() lacks the columns {missing}"]
    if len(df) != len(exps):
        return out + [f"result_frame() has {len(df)} rows for {len(exps)} bonds"]
    keys = model.Data.bond_keys()
    expected = {
        "bond_key": [keys[b] for b in sorted(exps)],
        "settlement_date": [iso(exps[b]["bond"]["settle"][1]) for b in sorted(exps)],
        "notional": [exps[b]["bond"]["notional_s"][1] for b in sorted(exps)],
        "tradable": [exps[b]["bond"]["is_tradable"][1] for b in sorted(exps)],
        "expired": [exps[b]["bond"]["is_expired"][1] for b in sorted(exps)],
    }
    for col in ("npv", "settlement_value", "dirty_price", "clean_price", "accrued_amount", "market_value"):
        expected[col] = [exps[b]["bond"][col][1] for b in sorted(exps)]
    for col, e in expected.items():
        got = [bool(x) if col in ("tradable", "expired") else x for x in df[col].tolist()]
        if not pv.same(got, e):
            first = next(i for i, (x, y) in enumerate(zip(got, e)) if not pv.same(x, y))
            out.append(f"result_frame()[{col!r}] row {first}: model {got[first]!r} vs pureql {e[first]!r}")
    return out


def compare_point(model, scen_id, t, zs, policy=pv.NT_ENGINE, bonds=None, extras=True):
    """Every mismatch between ``model.Valuation[scen_id, t]`` and pureql, as messages."""
    item = model.Valuation[scen_id, t]
    c = pv.curve_inputs(model, scen_id, t)
    n = model.Data.n_bonds()
    bonds = list(range(n)) if bonds is None else list(bonds)
    keys = model.Data.bond_keys()
    bad, exps = [], {}
    for b in bonds:
        exp = pv.expected_values(pv.pq_bond_values(model, scen_id, t, b, zs, c), policy)
        got = pv.model_values(item, b, exp)
        bad += pv.value_mismatches(got, exp, f"({scen_id}, {t}) b={b} {keys[b]}")
        exps[b] = exp
    if extras:
        bad += zdisc_mismatches(model, item, scen_id, t, c, bonds)
        bad += settle_cal_mismatches(item, c)
        if len(bonds) == n:
            bad += aggregate_mismatches(model, item, exps)
    return bad


def report(bad, label):
    """Fail once with every mismatch (the first ones shown), or pass."""
    with soft(label) as s:
        s.checks = len(bad)
        for msg in bad:
            s.error(msg)


def write_inputs(out, bonds, vdates, params, nodes=(), spreads=(), coupon_rates=()):
    """Write an input set (the schema of bond_portfolio/inputs.md) into ``out``."""
    gen.write_tables(out, {
        "bonds.csv": (gen.BOND_COLUMNS, list(bonds)),
        "coupon_rates.csv": (gen.COUPON_RATE_COLUMNS, list(coupon_rates)),
        "valuation_dates.csv": (gen.VAL_DATE_COLUMNS,
                                [{"t": str(t), "val_date": v} for t, v in enumerate(vdates)]),
        "curve_params.csv": (gen.CURVE_PARAM_COLUMNS, list(params)),
        "curve_nodes.csv": (gen.CURVE_NODE_COLUMNS, list(nodes)),
        "spreads.csv": (gen.SPREAD_COLUMNS, list(spreads)),
    })
    return out


# --------------------------------------------------------------------------- the harness itself
@pytest.mark.parametrize("name", list(SETS))
def test_harness_forms_agree(set_model, name):
    """pureql's engine form (A) == its explicit-date form (B), bitwise, at every bond-point (no model Cells)."""
    m = set_model(name, SETS[name])
    n = 0
    for s, t in points(m):
        for b in range(m.Data.n_bonds()):
            pv.pq_bond_values(m, s, t, b, Z_GRID)  # raises AssertionError on any (A) != (B)
            n += 1
    assert n == 8 * m.Data.n_bonds()


def test_harness_forms_agree_on_the_flag_matrix(new_model, edge_inputs):
    """(A) == (B) under every (R, T, F), on the bonds with flows on vdate / on the settlement date."""
    m = new_model("Harness", edge_inputs)
    for flag_values in FLAGS:
        for s, t in points(m):
            for b in range(m.Data.n_bonds()):
                pv.pq_bond_values(m, s, t, b, (0.0, 0.01), flag_values=flag_values)


def test_harness_moves_the_flags(new_model, edge_inputs):
    """The flags reach pureql: on the edge set each flag changes some output (else the matrix is vacuous).

    Pairs that must differ: R alone; T = True alone; T = False overriding
    R = True (testSettings case 5 against case 3); F alone. (T = False with
    R = False is the default behaviour, testSettings case 2 = case 1.)
    """
    m = new_model("HarnessFlags", edge_inputs)
    keys = [(s, t, b) for s, t in points(m) for b in range(m.Data.n_bonds())]

    def values(flag_values):
        return {k: pv.pq_values_engine(m, *k, flag_values=flag_values) for k in keys}

    def moved(x, y):
        return any(not pv.same_outcome(o, y[k][g][key]) for k in keys for g in ("bond", "role")
                   for key, o in x[k][g].items())

    for a, b in (((0, -1, -1), (1, -1, -1)), ((0, -1, -1), (0, 1, -1)), ((1, -1, -1), (1, 0, -1)),
                 ((0, -1, -1), (0, -1, 1))):
        assert moved(values(a), values(b)), f"no pureql output differs between (R, T, F) = {a} and {b}"


# --------------------------------------------------------------------------- 0. the contract's Cells
VALUATION_CELLS = {
    # context [S]
    "vdate": (), "srow": (), "curve_type": (), "curve_dc": (), "curve_comp": (), "curve_freq": (),
    "spread_comp": (), "spread_freq": (), "node_lo": (), "n_nodes": (), "curve_extrapolate": (),
    "flat_rate": (), "engine_flag": (), "todays": (), "ref_events": (), "max_time": (), "curve_ok": (),
    # nodes, day offsets, flows
    "node_date": ("nd",), "node_rate_in": ("nd",), "node_time": ("nd",), "node_zc": ("nd",),
    "node_slope": ("nd",), "curve_time": ("kd",), "range_ok": ("kd",), "zero_c": ("kd",),
    "discount_core": ("kd",), "discount": ("kd",), "zs_base": ("kd",), "zs_discount_kd": ("kd", "z"),
    "zdisc": ("p",),
    # per bond
    "settle_cal": ("cal", "nsd"), "settle": ("b",), "notional_s": ("b",), "is_tradable": ("b",),
    "first_live": ("b", "role"), "is_expired": ("b",), "has_spread": ("b",), "spread": ("b",),
    "pv_base": ("b", "role"), "zdisc_npv": ("b", "role"), "pv_sprd": ("b", "role"), "npv": ("b",),
    "npv_base": ("b",), "settlement_value": ("b",), "accrued_cash": ("b",), "accrued_amount": ("b",),
    "dirty_price": ("b",), "clean_price": ("b",), "market_value": ("b",),
    "pv_z": ("b", "z"), "dirty_from_z": ("b", "z"), "clean_from_z": ("b", "z"),
    # aggregates
    "npv_total": (), "mv_total": (), "sv_total": (), "accrued_total": (), "n_expired": (), "n_tradable": (),
    "result_frame": (),
}


def test_valuation_has_the_contract_cells(set_model):
    """Every Phase 2 Cells of contract 4.7 exists with the contract's parameter names."""
    space = set_model("demo", DEMO).Valuation
    with soft("contract 4.7 Cells") as s:
        for name, params in VALUATION_CELLS.items():
            if not s.check(name in space.cells, f"Valuation has no Cells {name!r}"):
                continue
            got = tuple(space.cells[name].parameters)
            s.check(got == params, f"Valuation.{name} has parameters {got}, the contract says {params}")
    assert tuple(space.parameters) == ("scen_id", "t")


def test_zs_discount_kd_is_uncached(set_model):
    """``zs_discount_kd(kd, z)`` is [U] (contract 4.7)."""
    space = set_model("demo", DEMO).Valuation
    assert "zs_discount_kd" in space.cells, "Valuation has no Cells 'zs_discount_kd'"
    assert not space.cells["zs_discount_kd"].is_cached


# --------------------------------------------------------------------------- 1. the headline bond
def test_headline_bond_literals_and_pureql(set_model):
    """README headline: a 10Y semiannual 4% FixedRateBond, TARGET / Thirty360(BondBasis), T+3, flat 3%."""
    m = set_model("demo", DEMO)
    b = list(m.Data.bond_keys()).index("HEADLINE_10Y")
    # the harness reproduces the published literals ...
    raw = pv.pq_bond_values(m, 1, 0, b)
    assert pv.same_outcome(raw["bond"]["npv"], ("ok", HEADLINE_NPV))
    assert pv.same_outcome(raw["bond"]["clean_price"], ("ok", HEADLINE_CLEAN))
    # ... and so does the README's own construction (test_documentation_set.py:322-358), independently
    from pureql.time.calendars.target import TARGET
    from pureql.time.daycounters.thirty360 import Thirty360
    with pv.pq_settings(serial(ql.Date(16, ql.September, 2015))):
        issue = ql.Date(15, ql.September, 2015)
        sched = ql.Schedule(issue, ql.Date(15, ql.September, 2025), ql.Period(ql.Semiannual), TARGET(),
                            ql.Unadjusted, ql.Unadjusted, ql.DateGeneration.Backward, False)
        bond = ql.FixedRateBond(3, 100.0, sched, [0.04], Thirty360(Thirty360.BondBasis), ql.Following,
                                100.0, issue)
        bond.setPricingEngine(ql.DiscountingBondEngine(
            ql.Handle(ql.FlatForward(ql.Date(16, ql.September, 2015), 0.03, ql.Actual365Fixed()))))
        assert pv.same(bond.NPV(), HEADLINE_NPV) and pv.same(bond.cleanPrice(), HEADLINE_CLEAN)
    # the model: the literals, bit for bit, and every other output == pureql
    item = m.Valuation[1, 0]
    assert pv.same(pv.model_cells(item, "npv")(b), HEADLINE_NPV)
    assert pv.same(pv.model_cells(item, "clean_price")(b), HEADLINE_CLEAN)
    report(compare_point(m, 1, 0, Z_GRID, bonds=[b], extras=False), "headline bond")


# --------------------------------------------------------------------------- 2. testCachedZero
CACHED_ZERO = (("ZCB_2008", "2008-11-30", 88.551726), ("ZCB_2007", "2007-11-30", 91.278949),
               ("ZCB_2006", "2006-11-30", 94.098006))


@pytest.fixture(scope="module")
def cached_zero_inputs(tmp_path_factory):
    """``bonds.cpp`` testCachedZero (bonds.cpp:752-830): 22-Nov-2004, flat 3% Actual360, three ZCBs."""
    bonds = [{"bond_key": k, "bond_type": "ZeroCoupon", "face_amount": "1000000", "settlement_days": "1",
              "calendar": "UnitedStates.GovernmentBond", "issue_date": "2004-11-30", "redemption": "100",
              "maturity_date": mat, "payment_convention": "ModifiedFollowing"} for k, mat, _ in CACHED_ZERO]
    params = [{"scen_id": "1", "t": "0", "curve_type": "FlatForward", "day_counter": "Actual360",
               "compounding": "Continuous", "frequency": "Annual", "extrapolate": "0", "flat_rate": "0.03"}]
    return write_inputs(tmp_path_factory.mktemp("cached_zero"), bonds, ["2004-11-22"], params)


def test_cached_zero(set_model, cached_zero_inputs):
    m = set_model("cached_zero", cached_zero_inputs)
    item = m.Valuation[1, 0]
    tolerance = 1.0e-6  # bonds.cpp:761; the check is `fabs(price - cachedPrice) > tolerance` (absolute)
    # the upstream construction, independent of the harness (test_bonds.py:1002-1077)
    from pureql.time.calendars.unitedstates import UnitedStates
    from pureql.time.daycounters.actual360 import Actual360
    upstream = {}
    with pv.pq_settings(serial(ql.Date(22, ql.November, 2004))):
        today = ql.Date(22, ql.November, 2004)
        from pureql.termstructures.yieldtermstructure import YieldTermStructure
        curve = ql.Handle[YieldTermStructure](
            ql.FlatForward(today, ql.Handle[ql.Quote](ql.SimpleQuote(0.03)), Actual360()))
        engine = ql.DiscountingBondEngine(curve)
        for key, mat, _ in CACHED_ZERO:
            y, mo, d = (int(x) for x in mat.split("-"))
            bond = ql.ZeroCouponBond(1, UnitedStates(UnitedStates.GovernmentBond), 1000000.0,
                                     ql.Date(d, mo, y), ql.ModifiedFollowing, 100.0,
                                     ql.Date(30, ql.November, 2004))
            bond.setPricingEngine(engine)
            upstream[key] = bond.cleanPrice()
    keys = list(m.Data.bond_keys())
    for key, _, cached in CACHED_ZERO:
        b = keys.index(key)
        assert math.fabs(upstream[key] - cached) <= tolerance, f"pureql {key}: {upstream[key]!r} vs {cached}"
        price = pv.model_cells(item, "clean_price")(b)
        assert math.fabs(price - cached) <= tolerance, (
            f"failed to reproduce cached price {key}:\n    calculated: {price}\n    expected:   {cached}\n"
            f"    error:      {price - cached}")
        assert pv.same(price, upstream[key]), f"{key}: model {price!r} vs the upstream construction {upstream[key]!r}"
    report(compare_point(m, 1, 0, Z_GRID), "testCachedZero: model vs pureql")


# --------------------------------------------------------------------------- 3. demo and coverage, every (scen, t)
SET_POINTS = [(name, s, t) for name in SETS for s in (1, 2) for t in range(4)]


@pytest.mark.parametrize("name,scen_id,t", SET_POINTS, ids=[f"{n}-{s}-{t}" for n, s, t in SET_POINTS])
def test_every_bond(set_model, name, scen_id, t):
    m = set_model(name, SETS[name])
    assert (m.Data.n_scen(), m.Data.n_times()) == (2, 4)
    report(compare_point(m, scen_id, t, Z_GRID), f"{name} ({scen_id}, {t})")


@pytest.mark.parametrize("name", list(SETS))
def test_the_input_sets_cover_the_cases(set_model, name):
    """The sweep above is only as good as its cases: check that they are there."""
    m = set_model(name, SETS[name])
    seen = set()
    for s, t in points(m):
        c = pv.curve_inputs(m, s, t)
        seen.add(("curve", c["type"]))
        for b in range(m.Data.n_bonds()):
            raw = pv.pq_values_explicit(m, s, t, b)["bond"]
            seen.add(("spread", raw["has_spread"][1]))
            seen.add(("expired", raw["is_expired"][1]))
            seen.add(("tradable", raw["is_tradable"][1]))
            if int(m.Data.b_issue_arr()[b]) > c["vdate"]:
                seen.add(("forward start",))
    want = {("curve", 0), ("curve", 1), ("spread", True), ("spread", False), ("expired", True),
            ("expired", False), ("tradable", True), ("tradable", False)}
    if name == "coverage":
        want.add(("forward start",))
    assert want <= seen, f"{name}: missing {want - seen}"


@pytest.mark.parametrize("name", list(SETS))
def test_nt_raise_policy(new_model, name):
    """Under NT_RAISE (1) the ``*_from_z`` Cells raise pureql's "non tradable" message where N == 0.

    Everything else is unchanged: ``dirty_price`` / ``clean_price`` /
    ``accrued_amount`` stay ``Bond::dirtyPrice()`` & co., which return 0.0
    (bond.cpp:179-185, 256-262) rather than raise.
    """
    m = new_model(f"NtRaise_{name}", SETS[name], nontradable_policy=pv.NT_RAISE)
    bad, n_nt = [], 0
    for s, t in points(m):
        bad += compare_point(m, s, t, Z_SHORT, policy=pv.NT_RAISE, extras=False)
        for b in range(m.Data.n_bonds()):
            n_nt += not pv.pq_values_explicit(m, s, t, b)["bond"]["is_tradable"][1]
    assert n_nt > 0, "the input set has no non-tradable bond-point; the test is vacuous"
    report(bad, f"NT_RAISE {name}")


@pytest.mark.parametrize("name", list(SETS))
def test_nt_engine_returns_zero(set_model, name):
    """NT_ENGINE (default): where N == 0 the ``*_from_z`` Cells are exactly 0.0 (float)."""
    m = set_model(name, SETS[name])
    seen = 0
    for s, t in points(m):
        item = m.Valuation[s, t]
        for b in range(m.Data.n_bonds()):
            if pv.pq_values_explicit(m, s, t, b)["bond"]["is_tradable"][1]:
                continue
            seen += 1
            for cell in ("dirty_from_z", "clean_from_z"):
                for z in Z_SHORT:
                    assert pv.same(pv.model_cells(item, cell)(b, z), 0.0), (cell, s, t, b, z)
    assert seen > 0


# --------------------------------------------------------------------------- curve Cells
@pytest.mark.parametrize("name,scen_id,t", SET_POINTS, ids=[f"{n}-{s}-{t}" for n, s, t in SET_POINTS])
def test_curve_cells(set_model, name, scen_id, t):
    """Context, node and day-offset Cells == pureql's curve (``discount`` incl. its range errors)."""
    m = set_model(name, SETS[name])
    item = m.Valuation[scen_id, t]
    kds = pv.curve_kds(m, scen_id, t)
    exp = pv.pq_curve_values(m, scen_id, t, kds, zs=(0.0, 0.0075, -0.0125))
    bad = []
    for cell, e in exp["ctx"].items():
        g = pv.run_model(pv.model_cells(item, cell))
        if not pv.same_outcome(g, e):
            bad.append(f"{cell}(): model {pv.show(g)} vs pureql {pv.show(e)}")
    for group in ("node", "kd", "kdz"):
        for key, e in exp[group].items():
            g = pv.run_model(pv.model_cells(item, key[0]), *key[1:])
            if not pv.same_outcome(g, e):
                bad.append(f"{key[0]}{key[1:]}: model {pv.show(g)} vs pureql {pv.show(e)}")
    report(bad, f"curve {name} ({scen_id}, {t})")


@pytest.fixture(scope="module")
def short_curve_inputs(tmp_path_factory):
    """A ZeroCurve ending at 3Y without extrapolation, and bonds that outlive it (pureql's range errors)."""
    bonds = [
        {"bond_key": "FR_10Y", "bond_type": "FixedRate", "face_amount": "100", "settlement_days": "2",
         "calendar": "TARGET", "issue_date": "2015-03-16", "effective_date": "2015-03-16",
         "termination_date": "2025-03-16", "tenor": "6M", "coupon_rate": "0.04",
         "accrual_day_counter": "Thirty360.BondBasis"},
        {"bond_key": "FR_2Y", "bond_type": "FixedRate", "face_amount": "100", "settlement_days": "2",
         "calendar": "TARGET", "issue_date": "2015-03-16", "effective_date": "2015-03-16",
         "termination_date": "2017-03-16", "tenor": "6M", "coupon_rate": "0.02",
         "accrual_day_counter": "Actual360", "spread_id": "S"},
        {"bond_key": "ZCB_5Y_SPREAD", "bond_type": "ZeroCoupon", "face_amount": "100", "settlement_days": "0",
         "calendar": "NullCalendar", "issue_date": "2015-01-02", "maturity_date": "2020-01-02",
         "payment_convention": "Unadjusted", "spread_id": "S"},
        {"bond_key": "ZCB_3Y_EDGE", "bond_type": "ZeroCoupon", "face_amount": "100", "settlement_days": "0",
         "calendar": "NullCalendar", "issue_date": "2015-01-02", "maturity_date": "2018-09-16",
         "payment_convention": "Unadjusted"},
    ]
    params = [{"scen_id": "1", "t": "0", "curve_type": "ZeroCurve", "day_counter": "Actual365Fixed",
               "compounding": "Compounded", "frequency": "Annual", "extrapolate": "0",
               "spread_compounding": "Simple", "spread_frequency": ""}]
    nodes = [{"scen_id": "1", "t": "0", "node": str(k), "tenor": ten, "rate": r}
             for k, (ten, r) in enumerate((("0D", "0.01"), ("1Y", "0.012"), ("3Y", "0.015")))]
    spreads = [{"scen_id": "1", "t": "0", "spread_id": "S", "spread": "0.01"}]
    return write_inputs(tmp_path_factory.mktemp("short_curve"), bonds, ["2015-09-16"], params, nodes, spreads)


def test_curve_range_errors(set_model, short_curve_inputs):
    """Flows past the last node without extrapolation: the model raises pureql's checkRange messages."""
    m = set_model("short_curve", short_curve_inputs)
    raw = pv.pq_bond_values(m, 1, 0, 0)
    assert raw["bond"]["npv"][0] == "err" and "is past max curve time" in raw["bond"]["npv"][2]
    report(compare_point(m, 1, 0, Z_GRID), "short curve: bonds")
    item = m.Valuation[1, 0]
    kds = pv.curve_kds(m, 1, 0)
    exp = pv.pq_curve_values(m, 1, 0, kds, zs=(0.0, 0.01))
    bad = []
    for group in ("kd", "kdz"):
        for key, e in exp[group].items():
            g = pv.run_model(pv.model_cells(item, key[0]), *key[1:])
            if not pv.same_outcome(g, e):
                bad.append(f"{key[0]}{key[1:]}: model {pv.show(g)} vs pureql {pv.show(e)}")
    assert any(e[0] == "err" for e in exp["kd"].values())
    report(bad, "short curve: day-offset Cells")


# --------------------------------------------------------------------------- 4. a generated portfolio
@pytest.fixture(scope="module")
def gen_inputs(tmp_path_factory):
    out = tmp_path_factory.mktemp("pv_gen1k")
    gen.write_tables(out, gen.generate(GEN_BONDS, GEN_SCEN, GEN_TIMES, GEN_SEED))
    return out


@pytest.mark.parametrize("scen_id", [pytest.param(s, marks=() if s == 1 else pytest.mark.slow)
                                     for s in range(1, GEN_SCEN + 1)])
def test_generated_portfolio_t0(set_model, gen_inputs, scen_id):
    m = set_model("gen1k", gen_inputs)
    assert m.Data.n_bonds() == GEN_BONDS
    report(compare_point(m, scen_id, 0, Z_SHORT), f"generated portfolio ({scen_id}, 0)")


@pytest.mark.slow
@pytest.mark.parametrize("scen_id,t", [(s, t) for s in range(1, GEN_SCEN + 1) for t in range(1, GEN_TIMES)])
def test_generated_portfolio_future_t(set_model, gen_inputs, scen_id, t):
    m = set_model("gen1k", gen_inputs)
    report(compare_point(m, scen_id, t, Z_SHORT), f"generated portfolio ({scen_id}, {t})")


# --------------------------------------------------------------------------- 5. the flag matrix
@pytest.fixture(scope="module")
def edge_inputs(tmp_path_factory):
    """Bonds with a flow ON the valuation date, ON the settlement date and IN BETWEEN (cashflows.cpp:48-179).

    Valuation dates 16, 17 and 18-Sep-2015 (Wed-Fri). NullCalendar and
    Unadjusted unless stated, so every date is exact: settlement is T+n
    calendar days. Scenario 1 is a flat 3% curve, scenario 2 a ZeroCurve
    (Compounded, extrapolating); the spread bonds go through the spreaded
    curve.
    """
    def fr(key, eff, term, nsd, **kw):
        row = {"bond_key": key, "bond_type": "FixedRate", "face_amount": "100", "settlement_days": str(nsd),
               "calendar": "NullCalendar", "issue_date": eff, "effective_date": eff, "termination_date": term,
               "tenor": "1Y", "convention": "Unadjusted", "coupon_rate": "0.05",
               "accrual_day_counter": "Actual365Fixed", "payment_convention": "Unadjusted"}
        row.update(kw)
        return row

    def zcb(key, mat, nsd, **kw):
        row = {"bond_key": key, "bond_type": "ZeroCoupon", "face_amount": "100", "settlement_days": str(nsd),
               "calendar": "NullCalendar", "issue_date": "2010-09-16", "maturity_date": mat,
               "payment_convention": "Unadjusted"}
        row.update(kw)
        return row

    bonds = [
        fr("E01_CPN_ON_V_T2", "2014-09-16", "2017-09-16", 2),
        fr("E02_CPN_ON_S_T2", "2014-09-18", "2017-09-18", 2),
        fr("E03_CPN_BETWEEN_T2", "2014-09-17", "2017-09-17", 2),
        fr("E04_CPN_ON_V_T0", "2014-09-16", "2017-09-16", 0),
        zcb("E05_ZCB_MAT_ON_V_T2", "2015-09-16", 2),
        zcb("E06_ZCB_MAT_ON_S_T2", "2015-09-18", 2),
        zcb("E07_ZCB_MAT_ON_V_T0", "2015-09-16", 0),
        fr("E08_FR_MAT_ON_V_T0", "2012-09-16", "2015-09-16", 0),
        fr("E09_FR_MAT_ON_S_T1", "2012-09-18", "2015-09-18", 1),
        fr("E10_CPN_ON_V_T2_SPREAD", "2014-09-16", "2017-09-16", 2, spread_id="S"),
        zcb("E11_ZCB_MAT_ON_V_T0_SPREAD", "2015-09-16", 0, spread_id="S"),
        fr("E12_ISSUE_ON_S", "2015-09-18", "2018-09-18", 0),
        fr("E13_TARGET_6M_CPN_ON_V", "2015-03-16", "2020-03-16", 3, calendar="TARGET", tenor="6M",
           convention="Following", payment_convention="Following", accrual_day_counter="Thirty360.BondBasis"),
    ]
    vdates = ["2015-09-16", "2015-09-17", "2015-09-18"]
    params, nodes, spreads = [], [], []
    for t in range(3):
        params.append({"scen_id": "1", "t": str(t), "curve_type": "FlatForward", "day_counter": "Actual365Fixed",
                       "compounding": "Continuous", "frequency": "Annual", "extrapolate": "0",
                       "flat_rate": "0.03"})
        params.append({"scen_id": "2", "t": str(t), "curve_type": "ZeroCurve", "day_counter": "Actual365Fixed",
                       "compounding": "Compounded", "frequency": "Annual", "extrapolate": "1",
                       "spread_compounding": "Compounded", "spread_frequency": "Annual"})
        for k, (ten, r) in enumerate((("0D", "0.01"), ("1Y", "0.015"), ("5Y", "0.02"), ("10Y", "0.025"))):
            nodes.append({"scen_id": "2", "t": str(t), "node": str(k), "tenor": ten, "rate": r})
        for s in ("1", "2"):
            spreads.append({"scen_id": s, "t": str(t), "spread_id": "S", "spread": "0.01"})
    return write_inputs(tmp_path_factory.mktemp("flag_edges"), bonds, vdates, params, nodes, spreads)


FLAGS = list(itertools.product((0, 1), (-1, 0, 1), (-1, 0, 1)))


def test_edge_inputs_hit_the_edges(set_model, edge_inputs):
    """The edge set really has flows on vdate, on the settlement date and in between."""
    m = set_model("edges", edge_inputs)
    on_v = on_s = between = 0
    dates = m.Legs.cf_date_arr()
    lo = m.Legs.cf_lo_arr()
    for _, t in points(m):
        v = int(m.Data.val_date_arr()[t])
        for b in range(m.Data.n_bonds()):
            s = pv.pq_values_explicit(m, 1, t, b)["bond"]["settle"][1]
            for p in range(int(lo[b]), int(lo[b + 1])):
                on_v += int(dates[p]) == v
                on_s += int(dates[p]) == s and s != v
                between += v < int(dates[p]) < s
    assert on_v and on_s and between, (on_v, on_s, between)


@pytest.mark.parametrize("R,T,F", FLAGS, ids=[f"R{r}-T{t}-F{f}" for r, t, f in FLAGS])
def test_flag_matrix(new_model, edge_inputs, R, T, F):
    """Every output at every (scen, t) under one (R, T, F), on a FRESH model with the flags set first."""
    m = new_model("Flags", edge_inputs, include_reference_date_events=R, include_todays_cashflows=T,
                  engine_include_settlement_flows=F)
    assert pv.flags(m) == (R, T, F)
    bad = []
    for s, t in points(m):
        bad += compare_point(m, s, t, (0.0, 0.01))
    report(bad, f"flags R={R} T={T} F={F}")


def all_outputs(m):
    """Every model output of the edge set, as {(scen, t, b, key): outcome} (for the cache test)."""
    out = {}
    for s, t in points(m):
        item = m.Valuation[s, t]
        for b in range(m.Data.n_bonds()):
            for k in ("settle", "is_expired", "npv", "npv_base", "settlement_value", "accrued_amount",
                      "dirty_price", "clean_price"):
                out[(s, t, b, k)] = pv.run_model(pv.model_cells(item, k), b)
            for role in pv.ROLES:
                out[(s, t, b, "first_live", role)] = pv.run_model(pv.model_cells(item, "first_live"), b, role)
            for z in (0.0, 0.01):
                out[(s, t, b, "clean_from_z", z)] = pv.run_model(pv.model_cells(item, "clean_from_z"), b, z)
        for k in ("engine_flag", "todays", "ref_events", "npv_total", "n_expired"):
            out[(s, t, k)] = pv.run_model(pv.model_cells(item, k))
    return out


def test_assigning_flags_clears_valuation(new_model, edge_inputs):
    """Assigning a Data Reference clears the cached Valuation values (modelx clears dependents).

    One model goes through the flag combinations in turn, computing
    everything each time; after each assignment its values must equal a
    FRESH model's created with those flags. At least one combination must
    change some value, or the test proves nothing.
    """
    m = new_model("FlagsSeq", edge_inputs)
    before = all_outputs(m)
    changed = False
    for R, T, F in [(1, 0, 1), (0, 1, -1), (1, -1, 0), (0, -1, -1)]:
        m.Data.include_reference_date_events = R
        m.Data.include_todays_cashflows = T
        m.Data.engine_include_settlement_flows = F
        got = all_outputs(m)
        fresh = new_model("FlagsFresh", edge_inputs, include_reference_date_events=R,
                          include_todays_cashflows=T, engine_include_settlement_flows=F)
        want = all_outputs(fresh)
        stale = [k for k in want if not pv.same_outcome(got[k], want[k])]
        assert not stale, f"after setting R={R} T={T} F={F}, {len(stale)} stale values, e.g. {stale[:5]}"
        changed |= any(not pv.same_outcome(before[k], want[k]) for k in want)
    assert changed, "no flag combination changed any value; the edge set does not exercise the flags"


# --------------------------------------------------------------------------- goldens
def golden_path(name):
    return DATA / f"pv_{name}.json"


def decode(v):
    return ("err", ValueError, v["message"]) if isinstance(v, dict) else ("ok", v)


@pytest.mark.parametrize("name", list(SETS))
def test_golden_inputs_unchanged(name):
    """The goldens were frozen from these exact input files (else regenerate them)."""
    g = json.loads(golden_path(name).read_text(encoding="utf-8"))
    assert g["provenance"]["input_sha256"] == pv.input_hashes(SETS[name])


@pytest.mark.parametrize("name", list(SETS))
def test_pureql_still_reproduces_golden(set_model, name):
    """pureql today == the frozen pureql values, bit for bit (a drift of the oracle shows here)."""
    g = json.loads(golden_path(name).read_text(encoding="utf-8"))
    m = set_model(name, SETS[name])
    now = pv.golden_values(m)
    assert json.dumps(now, sort_keys=True) == json.dumps(g["values"], sort_keys=True)


@pytest.mark.parametrize("name", list(SETS))
def test_model_matches_golden(set_model, name):
    """The model == the frozen pureql values (bitwise; NT_ENGINE applied to the ``*_from_z`` prices)."""
    g = json.loads(golden_path(name).read_text(encoding="utf-8"))
    m = set_model(name, SETS[name])
    keys = list(m.Data.bond_keys())
    bad = []
    for point, recs in g["values"].items():
        s, t = (int(x) for x in point.split(","))
        item = m.Valuation[s, t]
        for key, rec in recs.items():
            b = keys.index(key)
            for k, v in rec["bond"].items():
                e = decode(v)
                g_ = pv.run_model(pv.model_cells(item, k), b)
                if not pv.same_outcome(g_, e):
                    bad.append(f"{point} {key} {k}: model {pv.show(g_)} vs golden {pv.show(e)}")
            for kr, v in rec["role"].items():
                k, role = kr[:-3], int(kr[-2])
                e = decode(v)
                g_ = pv.run_model(pv.model_cells(item, k), b, role)
                if not pv.same_outcome(g_, e):
                    bad.append(f"{point} {key} {kr}: model {pv.show(g_)} vs golden {pv.show(e)}")
            for kz, v in rec["z"].items():
                k, z = kz.split("[")
                z = float(z[:-1])
                e = decode(v)
                if k in ("dirty_from_z", "clean_from_z"):
                    e = pv.expected_values({"bond": {}, "role": {}, "z": {(k, z): e}})["z"][(k, z)]
                g_ = pv.run_model(pv.model_cells(item, k), b, z)
                if not pv.same_outcome(g_, e):
                    bad.append(f"{point} {key} {kz}: model {pv.show(g_)} vs golden {pv.show(e)}")
    report(bad, f"golden {name}")
