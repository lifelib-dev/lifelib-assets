"""Smoke tests of the Valuation space (docs/model-contract.md 4.7, Phase 2 core).

The implementer's own quick checks; the independent pureql-oracle suite is
``tests/pv/test_pv_*.py``. pureql is the reference, built here from the
model's parsed inputs (the Data arrays), and every comparison is EXACT (bit
for bit, NaN-aware; an error is a result too, compared by message):

* the README headline bond: NPV ``108.36776235612268`` and clean price
  ``108.34563953853349``;
* every bond of the demo and coverage inputs at every (scen_id, t): NPV,
  settlement value, dirty and clean price, accrued, settlement date,
  notional, expiry and the prices from a few z-spreads;
* the curve Cells against the pureql curves;
* an edge input set (valuation and settlement dates on coupon and redemption
  dates, T+0 on a null calendar, a redemption inside (v, s]) under the whole
  R/T/F flag matrix;
* ``first_live`` (bisection) against the linear scan of
  ``CashFlows.nextCashFlow``;
* QUIRK Q-04 at a matured bond, under both NT policies;
* ``Lib.coupon_accrued_amount`` against ``FixedRateCoupon.accruedAmount``,
  ex-coupon branch included.
"""

import datetime
import importlib.util
import itertools
import math
import pathlib
import struct

import modelx as mx
import pytest
from modelx.core.errors import FormulaError

from helpers import pureql_ref as pq
from helpers.model import MODEL_DIR

ql = pq.ql
from pureql import _state  # noqa: E402
from pureql.cashflows.fixedratecoupon import FixedRateCoupon  # noqa: E402
from pureql.math.interpolations.linearinterpolation import Linear  # noqa: E402
from pureql.termstructures.yield_.zerocurve import ZeroCurve  # noqa: E402

ROOT = MODEL_DIR.parents[1]
DEMO = ROOT / "bond_portfolio"
COVERAGE = ROOT / "tools" / "cy" / "sample_inputs"

_spec = importlib.util.spec_from_file_location("generate_inputs_smoke", DEMO / "generate_inputs.py")
gen = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gen)

_COUNT = itertools.count()
ROLE_ENGINE, ROLE_SETTLE, ROLE_EXPIRY = 0, 1, 2
ZS = (-0.0125, 0.0, 0.004, 0.03)
FLAGS = [(r, tt, f) for r in (0, 1) for tt in (-1, 0, 1) for f in (-1, 0, 1)]


# --------------------------------------------------------------------------- helpers
def bits(x):
    if isinstance(x, bool):
        return ("b", x)
    if isinstance(x, int):
        return ("i", x)
    if isinstance(x, float):
        return ("f", "nan") if math.isnan(x) else ("f", struct.pack("<d", x))
    return ("?", repr(x))


def mrun(fn, *args):
    """The model's outcome: ("ok", bits) or ("raise", message of the ORIGINAL error)."""
    try:
        return ("ok", bits(fn(*args)))
    except FormulaError:
        return ("raise", str(mx.get_error()))


def prun(fn, *args):
    """pureql's outcome: ("ok", bits) or ("raise", message); pureql's Error is the model's ValueError."""
    try:
        return ("ok", bits(fn(*args)))
    except ql.Error as e:
        return ("raise", str(e))


@pytest.fixture(scope="module")
def m():
    model = mx.read_model(MODEL_DIR, name=f"ValSmoke{next(_COUNT)}")
    yield model
    model.close()


@pytest.fixture(autouse=True)
def pureql_state():
    """Put pureql's process-global state (Settings) back exactly after each test."""
    before = _state.snapshot_all()
    yield
    _state.restore_all(before)


def set_inputs(m, d, R=0, T=-1, F=-1, nt=0):
    m.Data.input_dir = str(d)
    m.Data.include_reference_date_events = R
    m.Data.include_todays_cashflows = T
    m.Data.engine_include_settlement_flows = F
    m.Data.nontradable_policy = nt


def items(m):
    return [(s, t) for s in range(1, m.Data.n_scen() + 1) for t in range(m.Data.n_times())]


def pq_curve(m, s, t):
    """The pureql curve of (scen_id, t), built from the Data arrays."""
    d = m.Data
    row = s - 1
    v = int(d.val_date_arr()[t])
    dc = pq.pq_daycounter(int(d.c_dc_arr()[row, t]))
    comp = pq.pq_comp(int(d.c_comp_arr()[row, t]))
    freq = pq.pq_freq(int(d.c_freq_arr()[row, t]))
    if int(d.c_type_arr()[row, t]) == 1:
        c = ql.FlatForward(pq.pq_date(v), float(d.c_flat_arr()[row, t]), dc, comp, freq)
    else:
        lo, cnt = int(d.n_lo_arr()[row, t]), int(d.n_cnt_arr()[row, t])
        nds = [pq.pq_date(int(d.n_date_arr()[lo + k])) for k in range(cnt)]
        rates = [float(d.n_rate_arr()[lo + k]) for k in range(cnt)]
        c = ZeroCurve(nds, rates, dc, Linear(), comp, freq)
    if int(d.c_extrap_arr()[row, t]):
        c.enableExtrapolation()
    return c


def pq_settings(m, v):
    S = ql.Settings.instance()
    S.setEvaluationDate(pq.pq_date(v))
    S.setIncludeReferenceDateEvents(bool(m.Data.include_reference_date_events))
    T = m.Data.include_todays_cashflows
    S.setIncludeTodaysCashFlows(None if T == -1 else bool(T))


def pq_spread_conv(m, s, t):
    row = s - 1
    return (pq.pq_comp(int(m.Data.c_sp_comp_arr()[row, t])),
            pq.pq_freq(int(m.Data.c_sp_freq_arr()[row, t])))


def pq_bond_outcomes(m, s, t, b, curve, zs=ZS):
    """{quantity: outcome} of bond ``b`` at (scen_id, t) in pureql (the evaluation date must be set)."""
    d = m.Data
    row = s - 1
    bond = pq.pq_bond(m, b)
    spid = int(d.b_spread_idx_arr()[b])
    spc, spf = pq_spread_conv(m, s, t)
    if spid >= 0:
        disc = ql.ZeroSpreadedTermStructure(
            ql.Handle(curve), ql.Handle(ql.SimpleQuote(float(d.sp_arr()[row, t, spid]))), spc, spf)
    else:
        disc = curve
    F = d.engine_include_settlement_flows
    bond.setPricingEngine(ql.DiscountingBondEngine(ql.Handle(disc), None if F == -1 else bool(F)))
    sd = bond.settlementDate()
    out = {
        "settle": ("ok", bits(pq.serial(sd))),
        "notional_s": prun(bond.notional, sd),
        "is_tradable": prun(lambda: bool(ql.BondFunctions.isTradable(bond, sd))),
        "is_expired": prun(lambda: bool(bond.isExpired())),
        "npv": prun(bond.NPV),
        "settlement_value": prun(bond.settlementValue),
        "dirty_price": prun(bond.dirtyPrice),
        "clean_price": prun(bond.cleanPrice),
        "accrued_amount": prun(bond.accruedAmount, sd),
    }
    for z in zs:
        out[("pv_z", z)] = prun(ql.CashFlows.npv, bond.cashflows(), curve, z, spc, spf, False, sd, sd)
        out[("dirty_from_z", z)] = prun(ql.BondFunctions.dirtyPrice, bond, curve, z, spc, spf, sd)
        out[("clean_from_z", z)] = prun(ql.BondFunctions.cleanPrice, bond, curve, z, spc, spf, sd)
    return out


def model_bond_outcomes(v, b, zs=ZS):
    out = {name: mrun(getattr(v, name), b) for name in (
        "settle", "notional_s", "is_tradable", "is_expired", "npv", "settlement_value",
        "dirty_price", "clean_price", "accrued_amount")}
    for z in zs:
        for name in ("pv_z", "dirty_from_z", "clean_from_z"):
            out[(name, z)] = mrun(getattr(v, name), b, z)
    return out


def compare_item(m, s, t, zs=ZS):
    """Mismatches between the model and pureql over every bond at (scen_id, t)."""
    v = m.Valuation[s, t]
    vd = int(m.Data.val_date_arr()[t])
    bad = []
    pq_settings(m, vd)
    curve = pq_curve(m, s, t)
    for b in range(m.Data.n_bonds()):
        exp = pq_bond_outcomes(m, s, t, b, curve, zs)
        got = model_bond_outcomes(v, b, zs)
        for k in exp:
            if exp[k] != got[k]:
                bad.append((m.Data.bond_keys()[b], (s, t), k, got[k], exp[k]))
    return bad


# --------------------------------------------------------------------------- the headline bond
def test_headline_bond(m):
    set_inputs(m, DEMO)
    b = m.Data.bond_keys().index("HEADLINE_10Y")
    v = m.Valuation[1, 0]
    # the flat 3% Actual365Fixed (Continuous) curve at 16-Sep-2015
    assert v.vdate() == pq.serial(ql.Date(16, ql.September, 2015))
    assert (v.curve_type(), v.curve_dc(), v.curve_comp(), v.flat_rate()) == (1, 2, 2, 0.03)
    assert not v.has_spread(b)
    assert repr(v.npv(b)) == "108.36776235612268"
    assert repr(v.clean_price(b)) == "108.34563953853349"
    assert v.npv(b) == 108.36776235612268 and v.clean_price(b) == 108.34563953853349


# --------------------------------------------------------------------------- every bond == pureql
@pytest.mark.parametrize("inputs", [DEMO, COVERAGE], ids=["demo", "coverage"])
def test_every_bond_equals_pureql(m, inputs):
    set_inputs(m, inputs, nt=1)  # NT_RAISE reproduces pureql at non-tradable bonds
    bad = []
    for s, t in items(m):
        bad += compare_item(m, s, t)
    assert not bad, f"{len(bad)} mismatches, e.g. {bad[:4]}"


@pytest.mark.parametrize("inputs", [DEMO, COVERAGE], ids=["demo", "coverage"])
def test_curve_cells_equal_pureql(m, inputs):
    """discount(kd), zs_discount_kd(kd, z) and the ZeroCurve nodes against the pureql curves."""
    set_inputs(m, inputs)
    bad = []
    for s, t in items(m):
        v = m.Valuation[s, t]
        vd = v.vdate()
        pq_settings(m, vd)
        curve = pq_curve(m, s, t)
        spc, spf = pq_spread_conv(m, s, t)
        if v.curve_type() == 0:
            n = v.n_nodes()
            assert [v.node_time(k) for k in range(n)] == list(curve.times())
            assert [bits(v.node_zc(k)) for k in range(n)] == [bits(x) for x in curve.zeroRates()]
        assert bits(v.max_time()) == bits(curve.maxTime())
        for kd in list(range(0, 400, 13)) + list(range(400, 40000, 487)):
            if vd + kd > 109574:
                break
            d = pq.pq_date(vd + kd)
            if mrun(v.discount, kd) != prun(curve.discount, d):
                bad.append(((s, t), "discount", kd, mrun(v.discount, kd), prun(curve.discount, d)))
            for z in (-0.02, 0.0, 0.015):
                zc = ql.ZeroSpreadedTermStructure(ql.Handle(curve), ql.Handle(ql.SimpleQuote(z)), spc, spf)
                if mrun(v.zs_discount_kd, kd, z) != prun(zc.discount, d):
                    bad.append(((s, t), "zs_discount_kd", kd, z, mrun(v.zs_discount_kd, kd, z),
                                prun(zc.discount, d)))
    assert not bad, f"{len(bad)} mismatches, e.g. {bad[:4]}"


# --------------------------------------------------------------------------- the edge set
EDGE_BONDS = [
    # the headline bond; t1 settles on its coupon date, t2 values on it
    dict(bond_key="E1_HEADLINE", bond_type="FixedRate", face_amount="100", settlement_days="3",
         calendar="TARGET", issue_date="2015-09-15", effective_date="2015-09-15",
         termination_date="2025-09-15", tenor="6M", convention="Unadjusted",
         termination_convention="Unadjusted", coupon_rate="0.04",
         accrual_day_counter="Thirty360.BondBasis", payment_convention="Following"),
    # T+0 on a null calendar: settle == vdate
    dict(bond_key="E2_T0_NULL", bond_type="FixedRate", face_amount="100", settlement_days="0",
         calendar="NullCalendar", issue_date="2015-09-15", spread_id="SP", effective_date="2015-09-15",
         termination_date="2020-09-15", tenor="6M", convention="Unadjusted",
         termination_convention="Unadjusted", coupon_rate="0.03",
         accrual_day_counter="Actual365Fixed", payment_convention="Unadjusted"),
    # a zero-coupon bond redeemed on the last valuation date, with a spread
    dict(bond_key="E3_ZCB", bond_type="ZeroCoupon", face_amount="1000", settlement_days="2",
         calendar="TARGET", issue_date="2015-03-16", spread_id="SP", maturity_date="2016-09-15",
         payment_convention="Following"),
    # one coupon, redeemed on 2016-03-15: at t1 (2016-03-10, T+3 = 2016-03-15) notional(s) == 0
    # while the bond has not expired
    dict(bond_key="E4_REDEEMED_IN_V_S", bond_type="FixedRate", face_amount="100", settlement_days="3",
         calendar="TARGET", issue_date="2015-09-15", spread_id="SP", effective_date="2015-09-15",
         termination_date="2016-03-15", tenor="6M", convention="Unadjusted",
         termination_convention="Unadjusted", coupon_rate="0.05",
         accrual_day_counter="Actual360", payment_convention="Following"),
]
EDGE_DATES = ["2015-09-16", "2016-03-10", "2016-03-15", "2016-09-15"]


def write_edge_inputs(out):
    out = pathlib.Path(out)
    tables = {
        "bonds.csv": (gen.BOND_COLUMNS, EDGE_BONDS),
        "coupon_rates.csv": (gen.COUPON_RATE_COLUMNS, []),
        "valuation_dates.csv": (gen.VAL_DATE_COLUMNS,
                                [{"t": str(t), "val_date": d} for t, d in enumerate(EDGE_DATES)]),
        "curve_params.csv": (gen.CURVE_PARAM_COLUMNS,
                             [{"scen_id": "1", "t": str(t), "curve_type": "FlatForward",
                               "day_counter": "Actual365Fixed", "flat_rate": "0.03"}
                              for t in range(4)]
                             + [{"scen_id": "2", "t": str(t), "curve_type": "ZeroCurve",
                                 "day_counter": "Thirty360.BondBasis", "compounding": "Compounded",
                                 "frequency": "Semiannual", "extrapolate": str(t % 2),
                                 "spread_compounding": "Compounded", "spread_frequency": "Annual"}
                                for t in range(4)]),
        "curve_nodes.csv": (gen.CURVE_NODE_COLUMNS,
                            [{"scen_id": "2", "t": str(t), "node": str(k), "tenor": tn, "rate": r}
                             for t in range(4)
                             for k, (tn, r) in enumerate((("0D", "0.01"), ("6M", "0.012"), ("1Y", "0.015"),
                                                          ("5Y", "0.02"), ("15Y", "0.028")))]),
        "spreads.csv": (gen.SPREAD_COLUMNS,
                        [{"scen_id": str(s), "t": str(t), "spread_id": "SP", "spread": "0.0075"}
                         for s in (1, 2) for t in range(4)]),
    }
    gen.write_tables(out, tables)
    return out


@pytest.fixture(scope="module")
def edge_dir(tmp_path_factory):
    return write_edge_inputs(tmp_path_factory.mktemp("edge"))


@pytest.mark.parametrize("R,T,F", FLAGS)
def test_edge_set_equals_pureql_under_the_flag_matrix(m, edge_dir, R, T, F):
    set_inputs(m, edge_dir, R, T, F, nt=1)
    m.Data.check_inputs()
    bad = []
    for s, t in items(m):
        bad += compare_item(m, s, t, zs=(0.0, 0.01))
    assert not bad, f"{len(bad)} mismatches, e.g. {bad[:4]}"


def test_edge_set_reaches_its_corners(m, edge_dir):
    set_inputs(m, edge_dir)
    keys = m.Data.bond_keys()
    v1 = m.Valuation[1, 1]
    e4 = keys.index("E4_REDEEMED_IN_V_S")
    assert not v1.is_expired(e4) and not v1.is_tradable(e4) and v1.npv(e4) > 0.0
    assert v1.dirty_price(e4) == 0.0 and v1.clean_price(e4) == 0.0
    e2 = keys.index("E2_T0_NULL")
    assert v1.settle(e2) == v1.vdate()
    e1 = keys.index("E1_HEADLINE")
    assert v1.settle(e1) == m.Valuation[1, 2].vdate()


# --------------------------------------------------------------------------- first_live
def linear_first_live(m, v, b, role):
    """``CashFlows.nextCashFlow`` as upstream writes it: the first flow, scanning forward, that has not occurred."""
    lo, hi = int(m.Legs.cf_lo_arr()[b]), int(m.Legs.cf_lo_arr()[b + 1])
    ref = v.settle(b) if role == ROLE_SETTLE else v.vdate()
    inc = v.engine_flag() if role == ROLE_ENGINE else (0 if role == ROLE_SETTLE else -1)
    for p in range(lo, hi):
        if not m.Lib.has_occurred(int(m.Legs.cf_date_arr()[p]), ref, inc, v.vdate(), v.todays(), v.ref_events()):
            return p
    return hi


@pytest.mark.parametrize("which", ["demo", "coverage", "generated", "edge"])
def test_first_live_bisection_equals_the_linear_scan(m, which, edge_dir, tmp_path):
    if which == "demo":
        d = DEMO
    elif which == "coverage":
        d = COVERAGE
    elif which == "edge":
        d = edge_dir
    else:
        d = tmp_path / "gen"
        gen.write_tables(d, gen.generate(40, 1, 13, 11, step="1M"))
    checked = 0
    for R, T, F in FLAGS:
        set_inputs(m, d, R, T, F)
        for s, t in items(m):
            v = m.Valuation[s, t]
            for b in range(m.Data.n_bonds()):
                for role in (ROLE_ENGINE, ROLE_SETTLE, ROLE_EXPIRY):
                    assert v.first_live(b, role) == linear_first_live(m, v, b, role), (which, R, T, F, s, t, b, role)
                    checked += 1
                hi = int(m.Legs.cf_lo_arr()[b + 1])
                assert v.is_expired(b) == (linear_first_live(m, v, b, ROLE_EXPIRY) == hi)
    assert checked > 0


# --------------------------------------------------------------------------- QUIRK Q-04
def test_q04_at_a_matured_bond(m):
    set_inputs(m, DEMO)
    b = m.Data.bond_keys().index("ZCB_2008")
    v = m.Valuation[1, 0]
    assert v.is_expired(b) and not v.is_tradable(b) and v.notional_s(b) == 0.0
    for name in ("npv", "settlement_value", "dirty_price", "clean_price", "accrued_amount", "market_value"):
        x = getattr(v, name)(b)
        assert bits(x) == bits(0.0), name
    # NT_ENGINE (the default): prices from a z-spread are 0.0
    assert bits(v.dirty_from_z(b, 0.01)) == bits(0.0) and bits(v.clean_from_z(b, 0.01)) == bits(0.0)
    # pureql agrees on the engine figures
    pq_settings(m, v.vdate())
    curve = pq_curve(m, 1, 0)
    exp = pq_bond_outcomes(m, 1, 0, b, curve, zs=(0.01,))
    for name in ("npv", "settlement_value", "dirty_price", "clean_price", "accrued_amount"):
        assert mrun(getattr(v, name), b) == exp[name], name
    assert exp[("dirty_from_z", 0.01)][0] == "raise"
    # NT_RAISE reproduces pureql's error, message and all
    m.Data.nontradable_policy = 1
    try:
        v = m.Valuation[1, 0]
        assert mrun(v.dirty_from_z, b, 0.01) == exp[("dirty_from_z", 0.01)]
        assert mrun(v.clean_from_z, b, 0.01) == exp[("clean_from_z", 0.01)]
        assert "non tradable at" in exp[("dirty_from_z", 0.01)][1]
    finally:
        m.Data.nontradable_policy = 0


# --------------------------------------------------------------------------- aggregates
def test_aggregates_and_result_frame(m):
    set_inputs(m, COVERAGE)
    v = m.Valuation[2, 1]
    N = m.Data.n_bonds()
    for agg, cell in (("npv_total", "npv"), ("mv_total", "market_value"),
                      ("sv_total", "settlement_value"), ("accrued_total", "accrued_cash")):
        total = 0.0
        for b in range(N):
            total += getattr(v, cell)(b)
        assert bits(getattr(v, agg)()) == bits(total), agg
    assert v.n_expired() == len([b for b in range(N) if v.is_expired(b)])
    assert v.n_tradable() == len([b for b in range(N) if v.is_tradable(b)])
    df = v.result_frame()
    assert list(df.columns) == ["bond_key", "settlement_date", "notional", "npv", "settlement_value",
                                "dirty_price", "clean_price", "accrued_amount", "market_value",
                                "tradable", "expired"]
    assert len(df) == N and list(df["bond_key"]) == list(m.Data.bond_keys())
    for b in range(N):
        assert bits(float(df["npv"][b])) == bits(v.npv(b))
        assert bits(float(df["clean_price"][b])) == bits(v.clean_price(b))
        iso = (datetime.date(1899, 12, 30) + datetime.timedelta(days=v.settle(b))).isoformat()
        assert df["settlement_date"][b] == iso


# --------------------------------------------------------------------------- Lib.coupon_accrued_amount
@pytest.mark.parametrize("dc", [1, 2, 10, 11, 12])
def test_coupon_accrued_amount_equals_fixedratecoupon(m, dc):
    lib = m.Lib
    S = pq.serial
    start, end = S(ql.Date(15, ql.March, 2016)), S(ql.Date(15, ql.September, 2016))
    pay = S(ql.Date(16, ql.September, 2016))
    rstart, rend = S(ql.Date(15, ql.February, 2016)), S(ql.Date(15, ql.September, 2016))
    for ex in (0, S(ql.Date(8, ql.September, 2016))):
        cp = FixedRateCoupon(pq.pq_date(pay), 1000.0, 0.0425, pq.pq_daycounter(dc), pq.pq_date(start),
                             pq.pq_date(end), pq.pq_date(rstart), pq.pq_date(rend), pq.pq_date(ex))
        ir = cp.interestRate()
        comp, freq = int(ir.compounding()), int(ir.frequency())
        for d in range(start - 3, pay + 3):
            exp = prun(cp.accruedAmount, pq.pq_date(d))
            got = mrun(lib.coupon_accrued_amount, 1000.0, 0.0425, comp, freq, dc, start, end,
                       rstart, rend, pay, ex, d)
            assert got == exp, (dc, ex, d, got, exp)


# --------------------------------------------------------------------------- curve_ok
BAD_CURVES = {
    "one_node": ["2015-09-16"],
    "unsorted": ["2015-09-16", "2017-01-01", "2016-06-01"],
    "same_time": ["2015-09-16", "2016-01-30", "2016-01-31", "2017-01-31"],
}


@pytest.mark.parametrize("case", list(BAD_CURVES))
def test_curve_ok_raises_like_the_zerocurve_constructor(m, tmp_path, case):
    nodes = BAD_CURVES[case]
    gen.write_tables(tmp_path, {
        "bonds.csv": (gen.BOND_COLUMNS, EDGE_BONDS[:1]),
        "coupon_rates.csv": (gen.COUPON_RATE_COLUMNS, []),
        "valuation_dates.csv": (gen.VAL_DATE_COLUMNS, [{"t": "0", "val_date": "2015-09-16"}]),
        "curve_params.csv": (gen.CURVE_PARAM_COLUMNS,
                             [{"scen_id": "1", "t": "0", "curve_type": "ZeroCurve",
                               "day_counter": "Thirty360.European"}]),
        "curve_nodes.csv": (gen.CURVE_NODE_COLUMNS,
                            [{"scen_id": "1", "t": "0", "node": str(k), "date": d, "rate": "0.02"}
                             for k, d in enumerate(nodes)]),
        "spreads.csv": (gen.SPREAD_COLUMNS, []),
    })
    set_inputs(m, tmp_path)
    v = m.Valuation[1, 0]
    exp = prun(lambda: pq_curve(m, 1, 0) and True)
    assert exp[0] == "raise"
    assert mrun(v.curve_ok) == exp
    assert mrun(v.npv, 0) == exp
