"""Valuation against QuantLib 1.41 (the SWIG oracle), at tier T2 (docs/model-contract.md 4.7, section 5).

The bit-exact reference is pureql (``test_pv_t0.py``). Here the model is
compared with the installed QuantLib 1.41 binding at the T2 tier of
DECISIONS.md D-2 (``helpers/approx.py``: relative 1e-12, absolute floor
1e-14); dates, ints and bools exactly. Every test restores QuantLib's
Settings (and pureql's, through the autouse guard of ``conftest.py``).

* ``bonds.cpp`` testCachedZero on 1.41: the three cached prices at the
  upstream tolerance and the model at T2 (the "T2 twin" of plan Phase 2).
* The demo and coverage sets at every (scen_id, t), and a sample of a
  generated portfolio at t = 0 and a future t: settlement date, notional,
  tradable, expired, NPV, settlement value, dirty and clean price, accrued
  amount, and prices from a z-spread.
* The frozen QuantLib 1.41 goldens of quantlib-migration
  (``tests/data/tracer_bonds.json``) for the demo's ``ZCB_10Y``, which is the
  tracer's ``zcb-10y`` on the tracer's flat and zero curves.

Known gaps of the oracle, by design (quantlib-migration MIGRATION_PLAN 4.8):

* the 1.41 ``FixedRateBond`` binds no ``firstPeriodDayCounter``: such bonds
  are PORT-ONLY and are skipped here (they are covered against pureql);
* the 1.41 ``DiscountingBondEngine`` binds no ``includeSettlementDateFlows``:
  only the default flags are compared here (the flag matrix is pureql's);
* the 1.41 z-spread price is the deprecated day-counter overload (M-15),
  whose day counter is ignored;
* ``isRegular`` skew OS-02 has no price impact for the v1 day counters.
"""

import contextlib
import importlib.util
import json
import math

import pytest

from helpers import pureql_val as pv
from helpers.approx import assert_t2, soft
from helpers.model import MODEL_DIR
from helpers.pureql_ref import BOND_ZERO, bond_inputs

QL = pytest.importorskip("QuantLib")

pytestmark = pytest.mark.oracle

ROOT = MODEL_DIR.parents[1]
DEMO = ROOT / "bond_portfolio"
COVERAGE = ROOT / "tools" / "cy" / "sample_inputs"
SETS = {"demo": DEMO, "coverage": COVERAGE}
TRACER = ROOT / "tests" / "data" / "tracer_bonds.json"

_spec = importlib.util.spec_from_file_location("generate_inputs", DEMO / "generate_inputs.py")
gen = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gen)

Z_ORACLE = (-0.0125, 0.0, 0.0075)
GEN_BONDS, GEN_SCEN, GEN_TIMES, GEN_SEED, GEN_STRIDE = 1000, 2, 3, 20261011, 7


# --------------------------------------------------------------------------- QuantLib 1.41 objects
@contextlib.contextmanager
def ql_settings(vdate=None):
    """QuantLib's Settings for one computation (default flags), restored afterwards.

    An unset evaluation date reads as today's date; it is put back with
    ``resetEvaluationDate()`` rather than anchored to today.
    """
    s = QL.Settings.instance()
    before = (s.evaluationDate, s.includeReferenceDateEvents, s.includeTodaysCashFlows)
    was_today = before[0] == QL.Date.todaysDate()
    try:
        if vdate is not None:
            s.evaluationDate = QL.Date(int(vdate))
        s.includeReferenceDateEvents = False
        s.includeTodaysCashFlows = None
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


def ql_spreaded(curve, z, comp, freq):
    return QL.ZeroSpreadedTermStructure(QL.YieldTermStructureHandle(curve), QL.QuoteHandle(QL.SimpleQuote(z)),
                                        comp, freq)


def ql_run(fn, *args):
    try:
        return ("ok", fn(*args))
    except RuntimeError as e:  # QuantLib errors arrive as RuntimeError
        return ("err", RuntimeError, str(e))


def ql_values(model, scen_id, t, b, zs):
    """QuantLib 1.41 values of bond ``b`` at (scen_id, t), Settings moved to vdate; None if not buildable."""
    c = pv.curve_inputs(model, scen_id, t)
    spread = pv.bond_spread(model, scen_id, t, b)
    with ql_settings(c["vdate"]):
        bond = ql_bond(model, b)
        if bond is None:
            return None
        curve = ql_curve(c)
        engine_curve = curve if spread is None else ql_spreaded(curve, spread, c["sp_comp"], c["sp_freq"])
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
            for key, fn in (("dirty_from_z", QL.BondFunctions.dirtyPrice), ("clean_from_z", QL.BondFunctions.cleanPrice)):
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


def compare_with_quantlib(model, scen_id, t, bonds, zs=Z_ORACLE):
    item = model.Valuation[scen_id, t]
    keys = model.Data.bond_keys()
    bad, compared = [], 0
    for b in bonds:
        want = ql_values(model, scen_id, t, b, zs)
        if want is None:
            continue
        compared += 1
        bad += t2_mismatches(model, item, b, want, f"({scen_id}, {t}) b={b} {keys[b]}")
    return bad, compared


def report(bad, label):
    with soft(label) as s:
        s.checks = len(bad)
        for msg in bad:
            s.error(msg)


@pytest.fixture(scope="module")
def models():
    made = {}

    def get(name, input_dir):
        if name not in made:
            made[name] = pv.private_model(f"PvOracle_{name}_", input_dir)
        return made[name]

    yield get
    for m in made.values():
        m.close()


# --------------------------------------------------------------------------- the binding's enums are the model's codes
def test_quantlib_enums_are_the_model_codes():
    """The int codes passed to the oracle are its own enum values (contract section 2)."""
    assert [QL.Following, QL.ModifiedFollowing, QL.Preceding, QL.ModifiedPreceding, QL.Unadjusted,
            QL.HalfMonthModifiedFollowing, QL.Nearest] == list(range(7))
    assert [QL.Days, QL.Weeks, QL.Months, QL.Years] == [0, 1, 2, 3]
    assert [QL.Simple, QL.Compounded, QL.Continuous, QL.SimpleThenCompounded, QL.CompoundedThenSimple] == \
        [0, 1, 2, 3, 4]
    assert [QL.NoFrequency, QL.Once, QL.Annual, QL.Semiannual, QL.Quarterly, QL.Monthly] == [-1, 0, 1, 2, 4, 12]
    assert (QL.DateGeneration.Backward, QL.DateGeneration.Zero) == (0, 2)


# --------------------------------------------------------------------------- testCachedZero on 1.41
def test_cached_zero_on_quantlib(models, tmp_path):
    """``bonds.cpp`` testCachedZero: QuantLib 1.41 at the upstream tolerance, the model at T2 against it."""
    rows = [{"bond_key": k, "bond_type": "ZeroCoupon", "face_amount": "1000000", "settlement_days": "1",
             "calendar": "UnitedStates.GovernmentBond", "issue_date": "2004-11-30", "redemption": "100",
             "maturity_date": mat, "payment_convention": "ModifiedFollowing"}
            for k, mat in (("ZCB_2008", "2008-11-30"), ("ZCB_2007", "2007-11-30"), ("ZCB_2006", "2006-11-30"))]
    gen.write_tables(tmp_path, {
        "bonds.csv": (gen.BOND_COLUMNS, rows),
        "valuation_dates.csv": (gen.VAL_DATE_COLUMNS, [{"t": "0", "val_date": "2004-11-22"}]),
        "curve_params.csv": (gen.CURVE_PARAM_COLUMNS, [{
            "scen_id": "1", "t": "0", "curve_type": "FlatForward", "day_counter": "Actual360",
            "compounding": "Continuous", "frequency": "Annual", "extrapolate": "0", "flat_rate": "0.03"}]),
    })
    m = models("cached_zero", tmp_path)
    item = m.Valuation[1, 0]
    cached = (88.551726, 91.278949, 94.098006)
    with ql_settings(QL.Date(22, QL.November, 2004).serialNumber()):
        today = QL.Date(22, QL.November, 2004)
        engine = QL.DiscountingBondEngine(QL.YieldTermStructureHandle(
            QL.FlatForward(today, QL.QuoteHandle(QL.SimpleQuote(0.03)), QL.Actual360())))
        for b, (y, price) in enumerate(zip((2008, 2007, 2006), cached)):
            bond = QL.ZeroCouponBond(1, QL.UnitedStates(QL.UnitedStates.GovernmentBond), 1000000.0,
                                     QL.Date(30, QL.November, y), QL.ModifiedFollowing, 100.0,
                                     QL.Date(30, QL.November, 2004))
            bond.setPricingEngine(engine)
            q = bond.cleanPrice()
            assert math.fabs(q - price) <= 1.0e-6, (y, q, price)
            assert_t2(pv.model_cells(item, "clean_price")(b), q, f"testCachedZero {y}: model vs QuantLib 1.41")
    bad, n = compare_with_quantlib(m, 1, 0, range(3))
    assert n == 3
    report(bad, "testCachedZero vs QuantLib 1.41")


# --------------------------------------------------------------------------- demo and coverage
@pytest.mark.parametrize("name", list(SETS))
def test_input_sets_against_quantlib(models, name):
    m = models(name, SETS[name])
    bad, n = [], 0
    for s in range(1, m.Data.n_scen() + 1):
        for t in range(m.Data.n_times()):
            got, k = compare_with_quantlib(m, s, t, range(m.Data.n_bonds()))
            bad += got
            n += k
    assert n > 0
    report(bad, f"{name} vs QuantLib 1.41")


# --------------------------------------------------------------------------- a generated portfolio, sampled
@pytest.fixture(scope="module")
def gen_inputs(tmp_path_factory):
    out = tmp_path_factory.mktemp("pv_oracle_gen")
    gen.write_tables(out, gen.generate(GEN_BONDS, GEN_SCEN, GEN_TIMES, GEN_SEED))
    return out


@pytest.mark.parametrize("scen_id,t", [(1, 0), (2, 0), (1, GEN_TIMES - 1), (2, GEN_TIMES - 1)])
def test_generated_sample_against_quantlib(models, gen_inputs, scen_id, t):
    m = models("gen", gen_inputs)
    bad, n = compare_with_quantlib(m, scen_id, t, range(0, m.Data.n_bonds(), GEN_STRIDE))
    assert n > 100
    report(bad, f"generated sample ({scen_id}, {t}) vs QuantLib 1.41")


# --------------------------------------------------------------------------- frozen 1.41 goldens (tracer zcb-10y)
@pytest.mark.parametrize("scen_id,case", [(1, "bonds/zerocouponbond[zcb-10y,flat]"),
                                          (2, "bonds/zerocouponbond[zcb-10y,zero]")])
def test_tracer_zcb_10y_goldens(models, scen_id, case):
    """The demo's ZCB_10Y at (scen_id, 0) is the tracer's zcb-10y on its curve: replay the 1.41 goldens.

    Each key at the tier the golden file records for it (``exact`` or
    ``value`` = T2). ``cleanPriceFromZSpread`` is QuantLib's clean price at
    its own solved ``zSpread`` (Compounded, Annual): the model's
    ``clean_from_z`` at that same z, at T2.
    """
    tracer = json.loads(TRACER.read_text(encoding="utf-8"))
    golden = tracer["cases"][case]
    m = models("demo", DEMO)
    b = list(m.Data.bond_keys()).index("ZCB_10Y")
    c = pv.curve_inputs(m, scen_id, 0)
    p = golden["params"]
    # the demo really is the tracer case
    assert c["vdate"] == QL.DateParser.parseISO(tracer["evaluationDate"]).serialNumber()
    if p["curve"].get("rate") is not None:
        assert (c["type"], c["flat"]) == (pv.CURVE_FLAT, p["curve"]["rate"])
    else:
        assert c["node_rates"] == p["curve"]["rates"]
        assert [QL.Date(d).ISO() for d in c["node_dates"]] == p["curve"]["dates"]
    assert (c["sp_comp"], c["sp_freq"]) == (QL.Compounded, QL.Annual)
    item = m.Valuation[scen_id, 0]
    r, tiers = golden["result"], golden["tiers"]

    def iso(serial):
        return QL.Date(int(serial)).ISO()

    checks = {
        "settlementDate": iso(pv.model_cells(item, "settle")(b)),
        "isExpired": pv.model_cells(item, "is_expired")(b),
        "isTradable": pv.model_cells(item, "is_tradable")(b),
        "notional": pv.model_cells(item, "notional_s")(b),
        "accruedAmount": pv.model_cells(item, "accrued_amount")(b),
        "NPV": pv.model_cells(item, "npv")(b),
        "settlementValue": pv.model_cells(item, "settlement_value")(b),
        "cleanPriceFromCurve": pv.model_cells(item, "clean_price")(b),
        "dirtyPriceFromCurve": pv.model_cells(item, "dirty_price")(b),
        "cleanPriceFromZSpread": pv.model_cells(item, "clean_from_z")(b, float(r["zSpread"])),
    }
    with soft(f"tracer {case}") as s:
        for key, got in checks.items():
            if tiers[key] == "exact":
                s.check(got == r[key], f"{key}: model {got!r} vs golden {r[key]!r}")
            else:
                s.t2(got, r[key], f"{key}: model vs QuantLib 1.41 golden")
