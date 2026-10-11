"""Round trips, monotonicity and the Q-09 pins of the Phase 4 analytics (docs/model-contract.md 4.8).

The pattern is quantlib-migration's
``tests/new/instruments/test_fixedratebond_port_only.py:295-396``, run on the
MODEL: a price from a spread (or a yield) is written to prices.csv, and the
model solves the spread (the yield) back.

1. **z -> price(z) -> zspread == z** within 1e-11 (tier T2 solver) at
   ``zspread_accuracy = 1e-12``, from the CLEAN and from the DIRTY price, over
   ``_Z_GRID = (-0.02, -0.01, -0.0025, 0.0, 0.0025, 0.01, 0.02, 0.05)`` x the
   four conventions of ``_YIELD_CONVENTIONS`` x both curve types (FlatForward,
   ZeroCurve), at t = 0 and at a future t, on three bonds (the README headline
   bond, the tracer zcb-10y and a quarterly Actual360 bond with a short first
   stub). In the model a convention is (curve day counter, spread
   compounding, spread frequency). ActualActual.ISDA (the fourth upstream
   convention) is outside v1 (DECISIONS.md D-3); Thirty360.USA (with Simple /
   Annual) is substituted. The prices are the model's own
   ``clean_from_z`` / ``dirty_from_z`` (== pureql, checked), and every solved
   z-spread is also == pureql's ``BondFunctions.zSpread`` bit for bit.
2. **y -> price(y) -> ytm == y** within 1e-11 at ``yield_accuracy = 1e-12``,
   with NewtonSafe and with Brent, under all five yield compoundings, from
   clean and dirty prices, at t = 0 and a future t; each ytm == pureql.
3. **Monotonicity**: the clean price is strictly decreasing in the yield
   (``_Y_GRID``) and in the z-spread (``_Z_GRID``).
4. **QUIRK Q-09 pins** (tests/data/analytics_pins.json): with a Simple yield
   the stepwise ``npv_yield`` (a running product of one-step factors) and the
   accumulated-time price behind the durations differ - by -3.08 at 3% on the
   headline bond - and the modified duration is NOT the log-derivative of the
   price the same model reports (25% apart at 3%). With a Compounded yield
   the two schemes agree to rounding. The model must keep both schemes (never
   unify them): its values equal the pins bit for bit.
"""

import json
import math

import pytest

from helpers import pureql_val as pv
from helpers.approx import soft
from helpers.model import MODEL_DIR
from helpers.pureql_ref import pq_bond

ROOT = MODEL_DIR.parents[1]
PINS = json.loads((ROOT / "tests" / "data" / "analytics_pins.json").read_text(encoding="utf-8"))
SOLVER_TIER = 1e-11
T_POINTS = range(len(pv.RT_VDATES))


def bix(m):
    return {k: b for b, k in enumerate(m.Data.bond_keys())}


def cell(item, name):
    c = pv.analytics_cell(item, name)
    assert c is not None, f"Valuation has no Cells {name!r} (docs/model-contract.md 4.7/4.8)"
    return c


# --------------------------------------------------------------------------- 1. z round trip
@pytest.fixture(scope="module")
def z_base(tmp_path_factory, set_model):
    """The z set without prices, and the model's own prices from a spread: {(scen_id, t, key): price}."""
    m = set_model("z_base", pv.write_z_roundtrip_inputs(tmp_path_factory.mktemp("z_rt_base")))
    idx = bix(m)
    prices = {}
    for s in pv.z_roundtrip_scenarios():
        for t in T_POINTS:
            item = m.Valuation[s, t]
            for key, _, z, ptype in pv.z_roundtrip_bonds():
                prices[(s, t, key)] = cell(item, "clean_from_z" if ptype == "Clean" else "dirty_from_z")(idx[key],
                                                                                                         float(z))
    return m, prices


@pytest.fixture(scope="module")
def z_solved(tmp_path_factory, set_model, z_base):
    """The z set WITH those prices, solved at accuracy 1e-12."""
    _, prices = z_base
    d = pv.write_z_roundtrip_inputs(tmp_path_factory.mktemp("z_rt_priced"), prices)
    return set_model("z_solved", d, zspread_accuracy=1e-12)


def test_z_prices_are_pureqls(z_base):
    """The prices fed back are pureql's ``BondFunctions.cleanPrice / dirtyPrice(bond, curve, z, comp, freq, s)``."""
    m, prices = z_base
    idx = bix(m)
    with soft("price from a z-spread vs pureql") as s:
        for sc in pv.z_roundtrip_scenarios():
            for t in T_POINTS:
                c = pv.curve_inputs(m, sc, t)
                with pv.pq_settings(c["vdate"]):
                    curve = pv.pq_curve(m, sc, t, c)
                    for key, _, z, ptype in pv.z_roundtrip_bonds():
                        bond = pq_bond(m, idx[key])
                        st = bond.settlementDate(pv.pq_date(c["vdate"]))
                        fn = pv.BondFunctions.cleanPrice if ptype == "Clean" else pv.BondFunctions.dirtyPrice
                        e = fn(bond, curve, float(z), pv.pq_comp(c["sp_comp"]), pv.pq_freq(c["sp_freq"]), st)
                        s.check(pv.same(prices[(sc, t, key)], e),
                                f"({sc}, {t}) {key}: model {prices[(sc, t, key)]!r} vs pureql {e!r}")


@pytest.mark.parametrize("ctype", ["FlatForward", "ZeroCurve"])
@pytest.mark.parametrize("t", list(T_POINTS))
def test_z_round_trip(z_solved, t, ctype):
    """zspread(price(z)) == z within 1e-11, clean and dirty, 4 conventions; and == pureql exactly."""
    m = z_solved
    idx = bix(m)
    bad = []
    with soft(f"z round trip t={t} {ctype}") as s:
        for sc, (ct, conv) in pv.z_roundtrip_scenarios().items():
            if ct != ctype:
                continue
            item = m.Valuation[sc, t]
            zcell = cell(item, "zspread")
            for key, _, z, ptype in pv.z_roundtrip_bonds():
                g = pv.run_model(zcell, idx[key])
                if s.check(g[0] == "ok", f"({sc}, {t}) {key} {conv}: zspread raises {pv.show(g)}"):
                    s.t2_solver(g[1], z, f"({sc}, {t}) {key} {conv} {ptype}: z={z!r} came back as {g[1]!r}",
                                bound=SOLVER_TIER)
            q = pv.quote_inputs(m)
            c = pv.curve_inputs(m, sc, t)
            for key, _, _, _ in pv.z_roundtrip_bonds():
                bad += pv.compare_analytics(m, sc, t, idx[key], (), None, q, c, steps=False)[0]
    pv.report_analytics(bad, f"z round trip t={t} {ctype} vs pureql")


def test_price_strictly_decreasing_in_z(z_base):
    """``clean_from_z(b, z)`` is strictly decreasing over ``_Z_GRID`` for every base bond, curve and t."""
    m, _ = z_base
    idx = bix(m)
    with soft("monotone in z") as s:
        for sc in pv.z_roundtrip_scenarios():
            for t in T_POINTS:
                item = m.Valuation[sc, t]
                for base in pv.BASE_BONDS:
                    b = idx[f"{base}_Z0_C"]
                    prices = [cell(item, "clean_from_z")(b, float(z)) for z in pv.Z_GRID]
                    s.check(all(prices[i] > prices[i + 1] for i in range(len(prices) - 1)),
                            f"({sc}, {t}) {base}: {prices}")


# --------------------------------------------------------------------------- 2. y round trip
@pytest.fixture(scope="module")
def y_base(tmp_path_factory, set_model):
    m = set_model("y_base", pv.write_y_roundtrip_inputs(tmp_path_factory.mktemp("y_rt_base")))
    idx = bix(m)
    prices = {}
    for t in T_POINTS:
        item = m.Valuation[1, t]
        for key, _, _, y, ptype in pv.y_roundtrip_bonds():
            prices[(1, t, key)] = cell(item, "clean_from_yield" if ptype == "Clean" else "dirty_from_yield")(
                idx[key], float(y))
    return m, prices


@pytest.fixture(scope="module")
def y_priced(tmp_path_factory, y_base):
    _, prices = y_base
    return pv.write_y_roundtrip_inputs(tmp_path_factory.mktemp("y_rt_priced"), prices)


@pytest.mark.parametrize("solver", [pv.YIELD_NEWTON, pv.YIELD_BRENT], ids=["newton", "brent"])
@pytest.mark.parametrize("t", list(T_POINTS))
def test_y_round_trip(set_model, y_priced, t, solver):
    """ytm(price(y)) == y within 1e-11 under all five compoundings, clean and dirty; and == pureql exactly."""
    m = set_model(f"y_solved_{solver}", y_priced, yield_accuracy=1e-12, yield_solver=solver)
    idx = bix(m)
    item = m.Valuation[1, t]
    q = pv.quote_inputs(m)
    c = pv.curve_inputs(m, 1, t)
    bad = []
    with soft(f"y round trip t={t} solver={solver}") as s:
        ycell = cell(item, "ytm")
        for key, _, conv, y, ptype in pv.y_roundtrip_bonds():
            g = pv.run_model(ycell, idx[key])
            if s.check(g[0] == "ok", f"{key}: ytm raises {pv.show(g)}"):
                s.t2_solver(g[1], y, f"{key} {conv} {ptype}: y={y!r} came back as {g[1]!r}", bound=SOLVER_TIER)
            bad += pv.compare_analytics(m, 1, t, idx[key], (), None, q, c, steps=False)[0]
    pv.report_analytics(bad, f"y round trip t={t} solver={solver} vs pureql")


def test_price_strictly_decreasing_in_y(y_base):
    """``clean_from_yield(b, y)`` is strictly decreasing over ``_Y_GRID``, every base bond and compounding."""
    m, _ = y_base
    idx = bix(m)
    with soft("monotone in y") as s:
        for t in T_POINTS:
            item = m.Valuation[1, t]
            for base in pv.BASE_BONDS:
                for conv in pv.Y_RT_CONVENTIONS:
                    b = idx[f"{base}_{conv[1]}_Y0_C"]
                    prices = [cell(item, "clean_from_yield")(b, float(y)) for y in pv.Y_GRID_MONO]
                    s.check(all(prices[i] > prices[i + 1] for i in range(len(prices) - 1)),
                            f"t={t} {base} {conv}: {prices}")


# --------------------------------------------------------------------------- 3. Q-09
@pytest.fixture(scope="module")
def q09_model(tmp_path_factory, set_model):
    return set_model("q09", pv.write_q09_inputs(tmp_path_factory.mktemp("q09")))


def test_q09_pins_are_pureqls(q09_model):
    """Live pureql reproduces the pins (the oracle has not drifted); no model Cells."""
    idx = bix(q09_model)
    for label, pin in PINS["q09"].items():
        key, y = label.split("@")
        live = pv.pq_q09(q09_model, idx[key], float(y))
        assert all(pv.same(live[k], pin[k]) for k in pin), (label, live, pin)


@pytest.mark.parametrize("label", sorted(PINS["q09"]))
def test_q09_pins(q09_model, label):
    """The stepwise npv and the accumulated-time durations, each bit for bit, and never unified."""
    key, ys = label.split("@")
    y = float(ys)
    pin = PINS["q09"][label]
    m = q09_model
    b = bix(m)[key]
    item = m.Valuation[1, 0]
    npv = cell(item, "npv_yield")
    p_step = npv(b, y)
    assert pv.same(p_step, pin["P_step"]), f"npv_yield {p_step!r} vs pin {pin['P_step']!r}"
    assert pv.same(cell(item, "dirty_from_yield")(b, y), pin["dirty_from_yield"])
    assert pv.same(cell(item, "modified_duration_y")(b, y), pin["modified_duration"])
    # the measured gap between the two schemes, exactly
    assert pv.same(p_step - pin["P_acc"], pin["gap"])
    h = 1e-6
    fd = -(npv(b, y + h) - npv(b, y - h)) / (2 * h) / p_step
    assert pv.same(fd, pin["fd_log_derivative"])
    if key == "Q09_FRB_SIMPLE":
        # Simple: the schemes differ, and the duration is not the log-derivative of the price
        assert abs(pin["gap"]) > 1.0 and pin["fd_vs_modified_rel"] > 0.1
    else:
        # Compounded (and a single-flow bond): the schemes agree to rounding
        assert abs(pin["gap"]) < 1e-12 and pin["fd_vs_modified_rel"] < 1e-8


def test_q09_the_yield_solves_the_stepwise_price(q09_model):
    """With a Simple yield ``ytm`` inverts the STEPWISE price: ``npv_yield(ytm)`` hits the target.

    The engine clean price is the target; the NewtonSafe derivative is the
    accumulated-time ``-modified_duration_y * npv_yield`` (v1.43, Q-09), so
    the Newton steps are not exact - the root is still the stepwise one, to
    the solver accuracy, and == pureql.
    """
    m = q09_model
    b = bix(m)["Q09_FRB_SIMPLE"]
    item = m.Valuation[1, 0]
    ytm = cell(item, "ytm")(b)
    assert math.isfinite(ytm)
    target = cell(item, "y_target")(b)
    npv = cell(item, "npv_yield")
    h = 1e-6
    slope = abs(npv(b, ytm + h) - npv(b, ytm - h)) / (2 * h)  # |dP/dy| of the STEPWISE price
    # the price error the yield accuracy allows (measured: 1.2e-8 against a bound of ~9e-7)
    assert abs(npv(b, ytm) - target) <= 10.0 * m.Data.yield_accuracy * slope
    pv.report_analytics(pv.compare_analytics(m, 1, 0, b, (ytm,))[0], "Q-09 yield vs pureql")
