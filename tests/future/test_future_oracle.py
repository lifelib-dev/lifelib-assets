"""Future valuation dates against QuantLib 1.41 with its evaluation date MOVED (plan Phase 3 exit), tier T2.

The bit-exact reference is pureql (the other ``test_future_*`` modules). Here
the model is compared with the installed QuantLib 1.41 SWIG binding, with
``Settings.evaluationDate = v_t``, at the T2 tier of DECISIONS.md D-2
(``helpers/approx.py``: relative 1e-12, absolute floor 1e-14); dates, ints
and bools exactly; where QuantLib raises, the model must raise. QuantLib's
Settings are restored after every test.

* The 2020 goldens of ``test_future_goldens.py``: the exploration's flat-curve
  literals, and this suite's zero-curve values (ZeroCurve Actual365Fixed /
  Continuous on {v, v+1Y, v+3Y, v+10Y} at {1%, 1.5%, 2.2%, 3%}) at 15- and
  16-Sep-2020, on 1.41 directly and through the model.
* The edge grid of ``test_future_edges.py`` at every (scenario, date) under
  the default flags, curve range errors included; and the T-override jump with
  1.41's own ``Settings.includeTodaysCashFlows = True``.
* The fuzz pairs of ``test_future_fuzz.py``: every 2nd pair of the default
  sample by default, all 10,000 under ``slow``.

Known gaps of the oracle, by design (quantlib-migration MIGRATION_PLAN 4.8):
the 1.41 ``FixedRateBond`` binds no ``firstPeriodDayCounter`` (such bonds are
skipped here, covered against pureql); the 1.41 ``DiscountingBondEngine``
binds no ``includeSettlementDateFlows`` (F is compared with pureql only); the
1.41 z-spread price is the deprecated day-counter overload (M-15), whose day
counter is ignored.
"""

import contextlib

import pytest

import test_future_edges as edges
import test_future_goldens as goldens
from helpers import pureql_val as pv
from helpers.approx import assert_t2
from helpers.pureql_ref import BOND_ZERO, bond_inputs

QL = pytest.importorskip("QuantLib")

pytestmark = pytest.mark.oracle

Z_ORACLE = (-0.0125, 0.0, 0.0125)
TRI = {-1: None, 0: False, 1: True}


# --------------------------------------------------------------------------- QuantLib 1.41 objects
@contextlib.contextmanager
def ql_settings(vdate=None, R=0, T=-1):
    """QuantLib's Settings for one computation, restored afterwards (an unset date stays unset)."""
    s = QL.Settings.instance()
    before = (s.evaluationDate, s.includeReferenceDateEvents, s.includeTodaysCashFlows)
    was_today = before[0] == QL.Date.todaysDate()
    try:
        if vdate is not None:
            s.evaluationDate = QL.Date(int(vdate))
        s.includeReferenceDateEvents = bool(R)
        s.includeTodaysCashFlows = TRI[int(T)]
        yield s
    finally:
        if was_today:
            s.resetEvaluationDate()
        else:
            s.evaluationDate = before[0]
        s.includeReferenceDateEvents = before[1]
        s.includeTodaysCashFlows = before[2]


@pytest.fixture(autouse=True)
def quantlib_settings_restored():
    s = QL.Settings.instance()
    before = (s.evaluationDate, s.includeReferenceDateEvents, s.includeTodaysCashFlows)
    yield
    after = (s.evaluationDate, s.includeReferenceDateEvents, s.includeTodaysCashFlows)
    assert after == before, f"QuantLib Settings changed by the test: {before} -> {after}"


def ql_date(serial):
    return QL.Date(int(serial)) if serial else QL.Date()


def ql_calendar(code):
    return {0: QL.NullCalendar, 1: QL.TARGET,
            2: lambda: QL.UnitedStates(QL.UnitedStates.Settlement),
            3: lambda: QL.UnitedStates(QL.UnitedStates.GovernmentBond)}[int(code)]()


def ql_daycounter(code):
    return {1: QL.Actual360, 2: QL.Actual365Fixed, 10: lambda: QL.Thirty360(QL.Thirty360.USA),
            11: lambda: QL.Thirty360(QL.Thirty360.BondBasis),
            12: lambda: QL.Thirty360(QL.Thirty360.European)}[int(code)]()


def ql_bond(model, b):
    """The QuantLib 1.41 bond of bond ``b`` from the model's parsed inputs, or None if 1.41 cannot build it."""
    x = bond_inputs(model, b)
    if x["type"] == BOND_ZERO:
        return QL.ZeroCouponBond(x["settlement_days"], ql_calendar(x["calendar"]), x["face"],
                                 ql_date(x["maturity"]), x["pay_conv"], x["redemption"], ql_date(x["issue"]))
    if x["first_dc"] != 0:
        return None  # no firstPeriodDayCounter in the 1.41 binding: port-only
    sched = QL.Schedule(ql_date(x["eff"]), ql_date(x["term"]), QL.Period(x["tenor_n"], x["tenor_unit"]),
                        ql_calendar(x["calendar"]), x["conv"], x["term_conv"], x["rule"], bool(x["eom"]),
                        ql_date(x["first"]), ql_date(x["ntl"]))
    kwargs = {}
    if x["pay_cal"] != -1:
        kwargs["paymentCalendar"] = ql_calendar(x["pay_cal"])
    return QL.FixedRateBond(x["settlement_days"], x["face"], sched, list(x["rates"]),
                            ql_daycounter(x["accrual_dc"]), x["pay_conv"], x["redemption"], ql_date(x["issue"]),
                            **kwargs)


def ql_curve(c):
    dc = ql_daycounter(c["dc"])
    if c["type"] == pv.CURVE_FLAT:
        curve = QL.FlatForward(QL.Date(c["vdate"]), c["flat"], dc, c["comp"], c["freq"])
    else:
        curve = QL.ZeroCurve([QL.Date(d) for d in c["node_dates"]], list(c["node_rates"]), dc,
                             QL.NullCalendar(), QL.Linear(), c["comp"], c["freq"])
    if c["extrap"]:
        curve.enableExtrapolation()
    return curve


def ql_run(fn, *args):
    try:
        return ("ok", fn(*args))
    except RuntimeError as e:  # QuantLib errors arrive as RuntimeError
        return ("err", RuntimeError, str(e))


def ql_values(model, scen_id, t, b, zs, R=0, T=-1):
    """QuantLib 1.41 values of bond ``b`` at (scen_id, t), Settings moved to v_t; None if 1.41 cannot build it."""
    c = pv.curve_inputs(model, scen_id, t)
    spread = pv.bond_spread(model, scen_id, t, b)
    with ql_settings(c["vdate"], R, T):
        bond = ql_bond(model, b)
        if bond is None:
            return None
        curve = ql_curve(c)
        engine_curve = curve if spread is None else QL.ZeroSpreadedTermStructure(
            QL.YieldTermStructureHandle(curve), QL.QuoteHandle(QL.SimpleQuote(spread)), c["sp_comp"], c["sp_freq"])
        bond.setPricingEngine(QL.DiscountingBondEngine(QL.YieldTermStructureHandle(engine_curve)))
        s = bond.settlementDate()
        out = {
            "settle": ("ok", s.serialNumber()),
            "notional_s": ql_run(bond.notional),
            "is_tradable": ql_run(QL.BondFunctions.isTradable, bond, s),
            "is_expired": ql_run(bond.isExpired),
            "npv": ql_run(bond.NPV),
            "settlement_value": ql_run(bond.settlementValue),
            "dirty_price": ql_run(bond.dirtyPrice),
            "clean_price": ql_run(bond.cleanPrice),
            "accrued_amount": ql_run(bond.accruedAmount),
        }
        dc = curve.dayCounter()
        for z in zs:
            out[("pv_z", z)] = ql_run(QL.CashFlows.npv, bond.cashflows(), curve, z, dc, c["sp_comp"],
                                      c["sp_freq"], False, s, s)
            for key, fn in (("dirty_from_z", QL.BondFunctions.dirtyPrice),
                            ("clean_from_z", QL.BondFunctions.cleanPrice)):
                o = ql_run(fn, bond, curve, z, dc, c["sp_comp"], c["sp_freq"], s)
                if o[0] == "err" and "non tradable" in o[2]:
                    o = ("ok", 0.0)  # NT_ENGINE (contract 4.7)
                out[(key, z)] = o
    return out


def t2_mismatches(model, item, b, want, ctx):
    """Model vs QuantLib: dates/ints/bools exactly, floats at T2; a QuantLib raise must be a model raise."""
    bad = []
    for key, w in want.items():
        name, args = (key, (b,)) if isinstance(key, str) else (key[0], (b, float(key[1])))
        g = pv.run_model(pv.model_cells(item, name), *args)
        if w[0] == "err" or g[0] == "err":
            if w[0] != g[0]:
                bad.append(f"{ctx} {key}: model {pv.show(g)} vs QuantLib {w}")
            elif "past max curve time" in w[2] and "past max curve time" not in g[2]:
                bad.append(f"{ctx} {key}: model raises {g[2]!r}, QuantLib {w[2]!r}")
            continue
        gv, wv = g[1], w[1]
        if isinstance(wv, float) and not isinstance(wv, bool):
            try:
                assert_t2(gv, wv, f"{ctx} {key}")
            except AssertionError as e:
                bad.append(str(e).replace("\n", " "))
        elif gv != wv or type(gv) is not type(wv):
            bad.append(f"{ctx} {key}: model {gv!r} ({type(gv).__name__}) vs QuantLib {wv!r} ({type(wv).__name__})")
    return bad


def compare_with_quantlib(model, points, zs=Z_ORACLE, R=0, T=-1, label=""):
    bad, compared, raised = [], 0, 0
    keys = model.Data.bond_keys()
    for s, t, b in points:
        want = ql_values(model, s, t, b, zs, R, T)
        if want is None:
            continue
        compared += 1
        raised += want["npv"][0] == "err"
        bad += t2_mismatches(model, model.Valuation[s, t], b, want, f"{label}({s}, {t}) b={b} {keys[b]}")
    return bad, compared, raised


# --------------------------------------------------------------------------- the 2020 goldens on 1.41
@pytest.fixture(scope="module")
def headline_model(set_model, tmp_path_factory):
    return set_model("oracle_headline", goldens.write_headline_inputs(tmp_path_factory.mktemp("oracle_headline")))


def test_quantlib_reproduces_the_2020_goldens():
    """QuantLib 1.41 itself (README construction, Settings moved): the flat literals and the zero-curve values (T2)."""
    def bond_and_curve(vd, zero):
        issue = QL.Date(15, QL.September, 2015)
        sched = QL.Schedule(issue, QL.Date(15, QL.September, 2025), QL.Period(QL.Semiannual), QL.TARGET(),
                            QL.Unadjusted, QL.Unadjusted, QL.DateGeneration.Backward, False)
        bond = QL.FixedRateBond(3, 100.0, sched, [0.04], QL.Thirty360(QL.Thirty360.BondBasis), QL.Following,
                                100.0, issue)
        if zero:
            dates = [vd, vd + QL.Period(1, QL.Years), vd + QL.Period(3, QL.Years), vd + QL.Period(10, QL.Years)]
            curve = QL.ZeroCurve(dates, [0.01, 0.015, 0.022, 0.03], QL.Actual365Fixed(), QL.NullCalendar(),
                                 QL.Linear(), QL.Continuous, QL.Annual)
        else:
            curve = QL.FlatForward(vd, 0.035, QL.Actual365Fixed())
        bond.setPricingEngine(QL.DiscountingBondEngine(QL.YieldTermStructureHandle(curve)))
        return bond, curve

    vd = QL.Date(16, QL.September, 2020)
    with ql_settings(vd.serialNumber()):
        bond, curve = bond_and_curve(vd, False)
        assert bond.settlementDate() == QL.Date(21, QL.September, 2020)
        for k, fn in (("npv", bond.NPV), ("settlement_value", bond.settlementValue), ("dirty_price", bond.dirtyPrice),
                      ("clean_price", bond.cleanPrice), ("accrued_amount", bond.accruedAmount)):
            assert_t2(fn(), goldens.FLAT_2020[k], f"QuantLib 1.41 {k} at 16-Sep-2020")
        z = QL.BondFunctions.cleanPrice(bond, curve, goldens.Z_PLAN, curve.dayCounter(), QL.Compounded, QL.Annual,
                                        bond.settlementDate())
        assert_t2(z, goldens.Z_CLEAN_2020, "QuantLib 1.41 clean price at z = 1.25%")
    for t, vd in ((goldens.T_COUPON, QL.Date(15, QL.September, 2020)), (goldens.T_2020, vd)):
        with ql_settings(vd.serialNumber()):
            bond, _ = bond_and_curve(vd, True)
            want = goldens.ZERO_2020[t]
            assert bond.settlementDate().ISO() == want["settle"]
            for k, fn in (("npv", bond.NPV), ("dirty_price", bond.dirtyPrice), ("clean_price", bond.cleanPrice),
                          ("accrued_amount", bond.accruedAmount)):
                assert_t2(fn(), want[k], f"QuantLib 1.41 zero curve {k} at {vd.ISO()}")


@pytest.mark.parametrize("scen_id", [goldens.SCEN_FLAT, goldens.SCEN_ZERO])
def test_headline_set_against_quantlib(headline_model, scen_id):
    bad, n, _ = compare_with_quantlib(headline_model, [(scen_id, t, 0) for t in range(3)],
                                      zs=goldens.Z_GOLDEN)
    assert n == 3
    pv.report_mismatches(bad, f"headline 2020 scenario {scen_id} vs QuantLib 1.41")


# --------------------------------------------------------------------------- the edge grid on 1.41
@pytest.fixture(scope="module")
def edge_inputs(tmp_path_factory):
    return edges.write_edge_inputs(tmp_path_factory.mktemp("oracle_edges"))


@pytest.mark.parametrize("scen_id", list(edges.SCENARIOS))
def test_edge_grid_against_quantlib(set_model, edge_inputs, scen_id):
    m = set_model("oracle_edges", edge_inputs)
    points = [(scen_id, t, b) for t in range(len(edges.VDATES)) for b in range(m.Data.n_bonds())]
    bad, n, raised = compare_with_quantlib(m, points)
    assert n == len(points)
    if scen_id == edges.SCEN_SHORT:
        assert raised > 0  # the range errors are compared too
    pv.report_mismatches(bad, f"edge grid scenario {scen_id} vs QuantLib 1.41")


@pytest.mark.parametrize("R,T", [(0, 1), (1, -1), (1, 0), (0, 0)])
def test_edge_flags_against_quantlib(new_model, edge_inputs, R, T):
    """R and T (1.41 Settings) on the event dates of the flat scenario, incl. the T-override with s == v."""
    m = new_model("OracleFlags", edge_inputs, include_reference_date_events=R, include_todays_cashflows=T)
    points = [(edges.SCEN_FLAT, edges.T_OF[v], b) for v in edges.EVENT_DATES for b in range(m.Data.n_bonds())]
    bad, n, _ = compare_with_quantlib(m, points, zs=(0.0,), R=R, T=T)
    assert n == len(points)
    pv.report_mismatches(bad, f"edge flags R={R} T={T} vs QuantLib 1.41")


def test_t_override_jump_on_quantlib():
    """1.41 with includeTodaysCashFlows = True: the T+0 bond's dirty price jumps by its 2.25 coupon on v == s."""
    vd = QL.Date(15, QL.September, 2020)

    def dirty(T):
        with ql_settings(vd.serialNumber(), 0, T):
            issue = QL.Date(15, QL.September, 2015)
            sched = QL.Schedule(issue, QL.Date(15, QL.September, 2025), QL.Period(QL.Semiannual), QL.TARGET(),
                                QL.Unadjusted, QL.Unadjusted, QL.DateGeneration.Backward, False)
            bond = QL.FixedRateBond(0, 100.0, sched, [0.045], QL.Thirty360(QL.Thirty360.BondBasis), QL.Following,
                                    100.0, issue)
            bond.setPricingEngine(QL.DiscountingBondEngine(QL.YieldTermStructureHandle(
                QL.FlatForward(vd, 0.035, QL.Actual365Fixed()))))
            return bond.dirtyPrice(), bond.NPV(), bond.accruedAmount()

    (d0, n0, a0), (d1, n1, a1) = dirty(-1), dirty(1)
    assert abs(d1 - d0 - 2.25) < 1e-12 * d1 and abs(n1 - n0 - 2.25) < 1e-12 * n1
    assert a0 == 0.0 and abs(a1 - 2.25) < 1e-12


# --------------------------------------------------------------------------- the fuzz subset on 1.41
def fuzz_points(pairs, lo, hi, stride):
    return [(s, t, b) for s, t, b, _, _ in pairs[lo:hi:stride]]


@pytest.mark.parametrize("name", sorted(pv.FUZZ_SETS))
def test_fuzz_subset_against_quantlib(fuzz_models, fuzz_pairs, name):
    """Every 2nd pair of the default fuzz sample, QuantLib 1.41 with its evaluation date moved to v_t (T2)."""
    m = fuzz_models[name]
    points = fuzz_points(fuzz_pairs[name], 0, pv.FUZZ_DEFAULT[name], 2)
    bad, n, _ = compare_with_quantlib(m, points, zs=(0.0, 0.01))
    assert n > 0.8 * len(points)  # the rest have a firstPeriodDayCounter (port-only)
    pv.report_mismatches(bad, f"fuzz {name} subset vs QuantLib 1.41")


@pytest.mark.slow
@pytest.mark.parametrize("name", sorted(pv.FUZZ_SETS))
def test_fuzz_full_subset_against_quantlib(fuzz_models, fuzz_pairs, name):
    """All 10,000 pairs (slow)."""
    m = fuzz_models[name]
    points = fuzz_points(fuzz_pairs[name], 0, pv.FUZZ_PAIRS[name], 1)
    bad, n, _ = compare_with_quantlib(m, points, zs=(0.0, 0.01))
    assert n > 0.8 * len(points)
    pv.report_mismatches(bad, f"fuzz {name} full subset vs QuantLib 1.41")
