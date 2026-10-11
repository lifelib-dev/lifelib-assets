"""Smoke tests of the Phase 4 analytics (docs/model-contract.md 4.8).

The implementer's own quick checks; the independent suite is
``tests/analytics``. pureql is the reference, built from the model's parsed
inputs, and every comparison with it is EXACT (bit for bit, NaN-aware; an
error is a result too, compared by message):

* the README headline: ``Bond.bondYield`` parity (engine clean price,
  ``yield_accuracy = 1e-8``) gives ``0.030250400779423203``;
* every bond of the demo and coverage inputs at every (scen_id, t), under
  ``NT_RAISE`` / ``ERR_RAISE`` so that every pureql error is the model's
  error: the yield family at a grid of yields and at the quoted yields
  (stepwise npv, the three durations, convexity, BPV, YVBP, prices from a
  yield), the solved yield with NewtonSafe and with Brent, the z-spread
  where a price is quoted, and the risk measures at the risk yield;
* the z-spread and yield round trips: a price made by the model from a
  z-spread (a yield) is solved back to it within the solver accuracy, and
  equals pureql's solve exactly;
* the policies: QUIRK Q-04 under ``NT_ENGINE`` (NaN / 0.0) and ``NT_RAISE``
  (pureql's raise); the ERR policy on a sign-check failure, a bracketing
  failure and the Macaulay rule; ``result_frame`` by ``output_level``;
* ``tools/calibrate_spreads.py`` on the demo inputs.
"""

import csv
import importlib.util
import itertools
import math
import shutil
import struct

import modelx as mx
import pytest
from modelx.core.errors import FormulaError

from helpers import pureql_ref as pq
from helpers.model import MODEL_DIR
from helpers.pureql_val import TRI, bond_spread, curve_inputs, flags, pq_curve, pq_settings, pq_spreaded

ql = pq.ql
from pureql.cashflows.cashflows import CashFlows  # noqa: E402
from pureql.cashflows.duration import Duration  # noqa: E402
from pureql.handle import Handle  # noqa: E402
from pureql.instruments.bond import Price  # noqa: E402
from pureql.math.solvers1d.brent import Brent  # noqa: E402
from pureql.pricingengines.bond.bondfunctions import BondFunctions  # noqa: E402
from pureql.pricingengines.bond.discountingbondengine import DiscountingBondEngine  # noqa: E402
from pureql.termstructures.yieldtermstructure import YieldTermStructure  # noqa: E402

ROOT = MODEL_DIR.parents[1]
DEMO = ROOT / "bond_portfolio"
COVERAGE = ROOT / "tools" / "cy" / "sample_inputs"
INPUT_SETS = {"demo": DEMO, "coverage": COVERAGE}

HEADLINE_YIELD = 0.030250400779423203
YS = (-0.01, 0.0, 0.03, 0.1)
Y_CELLS = ("npv_yield", "simple_duration_y", "modified_duration_y", "macaulay_duration_y", "convexity_y",
           "bpv_y", "yvbp_y", "dirty_from_yield", "clean_from_yield")
RISK_CELLS = ("duration_simple", "duration_modified", "duration_macaulay", "convexity", "bpv", "yvbp")
_COUNT = itertools.count()


# --------------------------------------------------------------------------- outcomes
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


def value(outcome):
    assert outcome[0] == "ok", outcome
    kind, raw = outcome[1]
    return math.nan if raw == "nan" else struct.unpack("<d", raw)[0]


@pytest.fixture
def new_model():
    made = []

    def make(input_dir, **refs):
        m = mx.read_model(MODEL_DIR, name=f"AnSmoke{next(_COUNT)}")
        m.Data.input_dir = str(input_dir)
        for k, v in refs.items():
            setattr(m.Data, k, v)
        made.append(m)
        return m

    yield make
    for m in made:
        m.close()


def items(m):
    return [(s, t) for s in range(1, m.Data.n_scen() + 1) for t in range(m.Data.n_times())]


def read_quotes(input_dir):
    """{(scen_id, t, bond_key): (price, PRICE_*)} and {(scen_id, t, bond_key): yield}, read from the CSV files."""
    prices, ylds = {}, {}
    p = input_dir / "prices.csv"
    if p.exists():
        with open(p, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                typ = 0 if r.get("price_type", "").strip() == "Dirty" else 1
                prices[(int(r["scen_id"]), int(r["t"]), r["bond_key"])] = (float(r["price"]), typ)
    p = input_dir / "yields.csv"
    if p.exists():
        with open(p, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                ylds[(int(r["scen_id"]), int(r["t"]), r["bond_key"])] = float(r["yield"])
    return prices, ylds


# --------------------------------------------------------------------------- the pureql side
def pq_analytics(m, s, t, b, ys, prices, ylds, brent_too=True):
    """{key: outcome} of pureql for bond ``b`` at (scen_id, t): the yield family at ``ys``, the solves, the risk measures."""
    d = m.Data
    R, T, F = flags(m)
    c = curve_inputs(m, s, t)
    spread = bond_spread(m, s, t, b)
    key = d.bond_keys()[b]
    dc, comp, freq = (int(m.Legs.bk_ydc_arr()[b]), int(m.Legs.bk_ycomp_arr()[b]),
                      int(m.Legs.bk_yfreq_arr()[b]))
    acc, maxev, guess = float(d.yield_accuracy), int(d.yield_max_evaluations), float(d.yield_guess)
    zacc, zmax, zguess = float(d.zspread_accuracy), int(d.zspread_max_evaluations), float(d.zspread_guess)
    out = {}
    with pq_settings(c["vdate"], R, T):
        bond = pq.pq_bond(m, b)
        leg = bond.cashflows()
        s_date = bond.settlementDate(pq.pq_date(c["vdate"]))
        pdc, pcomp, pfreq = pq.pq_daycounter(dc), pq.pq_comp(comp), pq.pq_freq(freq)
        ys = list(ys)
        if (s, t, key) in ylds:
            ys.append(ylds[(s, t, key)])
        for y in ys:
            ir = ql.InterestRate(y, pdc, pcomp, pfreq)
            out[("npv_yield", y)] = prun(CashFlows.npv, leg, ir, False, s_date, s_date)
            out[("simple_duration_y", y)] = prun(CashFlows.duration, leg, ir, Duration.Simple, False, s_date, s_date)
            out[("modified_duration_y", y)] = prun(CashFlows.duration, leg, ir, Duration.Modified, False,
                                                   s_date, s_date)
            out[("macaulay_duration_y", y)] = prun(CashFlows.duration, leg, ir, Duration.Macaulay, False,
                                                   s_date, s_date)
            out[("convexity_y", y)] = prun(CashFlows.convexity, leg, ir, False, s_date, s_date)
            out[("bpv_y", y)] = prun(CashFlows.basisPointValue, leg, ir, False, s_date, s_date)
            out[("yvbp_y", y)] = prun(CashFlows.yieldValueBasisPoint, leg, ir, False, s_date, s_date)
            out[("dirty_from_yield", y)] = prun(BondFunctions.dirtyPrice, bond, y, pdc, pcomp, pfreq, s_date)
            out[("clean_from_yield", y)] = prun(BondFunctions.cleanPrice, bond, y, pdc, pcomp, pfreq, s_date)

        curve = pq_curve(m, s, t, c)
        engine_curve = curve if spread is None else pq_spreaded(curve, spread, c["sp_comp"], c["sp_freq"])
        bond.setPricingEngine(DiscountingBondEngine(Handle[YieldTermStructure](engine_curve), TRI[F]))
        quote = prices.get((s, t, key))
        price = Price(quote[0], Price.Type(quote[1])) if quote else Price(bond.cleanPrice(), Price.Clean)
        out["ytm"] = prun(BondFunctions.bondYield, bond, price, pdc, pcomp, pfreq, s_date, acc, maxev, guess)
        if brent_too:
            brent = Brent()
            brent.setMaxEvaluations(maxev)
            out["ytm_brent"] = prun(BondFunctions.bondYield, brent, bond, price, pdc, pcomp, pfreq, s_date, acc, guess)
        if quote:
            out["zspread"] = prun(BondFunctions.zSpread, bond, price, curve, pq.pq_comp(c["sp_comp"]),
                                  pq.pq_freq(c["sp_freq"]), s_date, zacc, zmax, zguess)
        if (s, t, key) in ylds:
            ry = ("ok", bits(ylds[(s, t, key)]))
        else:
            ry = out["ytm"]
        if not BondFunctions.isTradable(bond, s_date):
            nt = prun(BondFunctions.duration, bond, 0.03, pdc, pcomp, pfreq, Duration.Simple, s_date)
            ry = nt
        out["risk_yield"] = ry
        if ry[0] != "ok":
            for k in RISK_CELLS:
                out[k] = ry
        else:
            y = value(ry)
            out["duration_simple"] = prun(BondFunctions.duration, bond, y, pdc, pcomp, pfreq, Duration.Simple, s_date)
            out["duration_modified"] = prun(BondFunctions.duration, bond, y, pdc, pcomp, pfreq, Duration.Modified,
                                            s_date)
            out["duration_macaulay"] = prun(BondFunctions.duration, bond, y, pdc, pcomp, pfreq, Duration.Macaulay,
                                            s_date)
            out["convexity"] = prun(BondFunctions.convexity, bond, y, pdc, pcomp, pfreq, s_date)
            out["bpv"] = prun(BondFunctions.basisPointValue, bond, y, pdc, pcomp, pfreq, s_date)
            out["yvbp"] = prun(BondFunctions.yieldValueBasisPoint, bond, y, pdc, pcomp, pfreq, s_date)
    return out


def model_analytics(v, vb, b, expected):
    """The model's outcomes for every key of ``expected`` (``vb``: the item of a Brent-yield model, or None)."""
    out = {}
    for k in expected:
        if isinstance(k, tuple):
            out[k] = mrun(getattr(v, k[0]), b, float(k[1]))
        elif k == "ytm_brent":
            out[k] = mrun(vb.ytm, b)
        else:
            out[k] = mrun(getattr(v, k), b)
    return out


def mismatches(got, expected, ctx):
    return [f"{ctx} {k}: model {got[k]} vs pureql {e}" for k, e in expected.items() if got[k] != e]


# --------------------------------------------------------------------------- tests
def test_headline_yield_is_bond_bond_yield(new_model):
    """``Bond.bondYield(Thirty360(BondBasis), Compounded, Semiannual)``: engine clean price, accuracy 1e-8."""
    m = new_model(DEMO, yield_accuracy=1e-8)
    assert m.Data.bond_keys()[0] == "HEADLINE_10Y"
    got = m.Valuation[1, 0].ytm(0)
    assert repr(got) == repr(HEADLINE_YIELD)
    # and pureql's own Bond.bondYield, built from the model's inputs
    c = curve_inputs(m, 1, 0)
    with pq_settings(c["vdate"], 0, -1):
        bond = pq.pq_bond(m, 0)
        bond.setPricingEngine(DiscountingBondEngine(Handle[YieldTermStructure](pq_curve(m, 1, 0, c))))
        expected = bond.bondYield(pq.pq_daycounter(11), ql.Compounded, ql.Semiannual)
    assert bits(got) == bits(expected)


@pytest.mark.parametrize("label", list(INPUT_SETS))
def test_analytics_equal_pureql(label, new_model):
    """Every bond at every (scen_id, t), NT_RAISE / ERR_RAISE: the model's outcome is pureql's, bit for bit."""
    inputs = INPUT_SETS[label]
    m = new_model(inputs, nontradable_policy=1, solver_error_policy=0)
    mb = new_model(inputs, nontradable_policy=1, solver_error_policy=0, yield_solver=1)
    prices, ylds = read_quotes(inputs)
    bad = []
    n = n_values = n_ytm = 0
    for s, t in items(m):
        v, vb = m.Valuation[s, t], mb.Valuation[s, t]
        for b in range(m.Data.n_bonds()):
            exp = pq_analytics(m, s, t, b, YS, prices, ylds)
            got = model_analytics(v, vb, b, exp)
            bad += mismatches(got, exp, f"{label} ({s}, {t}) b={b}")
            n += len(exp)
            n_values += sum(1 for o in exp.values() if o[0] == "ok" and o[1] != ("f", "nan"))
            n_ytm += exp["ytm"][0] == "ok"
    assert not bad, f"{len(bad)} mismatches:\n  " + "\n  ".join(bad[:30])
    # most outcomes are numbers, not errors both sides agree on
    assert n > 1000 and n_values > 0.75 * n, (n, n_values)
    assert n_ytm > 0.6 * len(items(m)) * m.Data.n_bonds(), n_ytm


def write_inputs_with_prices(src, dst, rows):
    """A copy of the input set ``src`` in ``dst`` whose prices.csv holds ``rows`` (scen_id, t, key, price, type)."""
    shutil.copytree(src, dst)
    with open(dst / "prices.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["scen_id", "t", "bond_key", "price", "price_type"])
        for r in rows:
            w.writerow([r[0], r[1], r[2], repr(r[3]), r[4]])


@pytest.mark.parametrize("what", ["zspread", "ytm"])
def test_round_trip(what, new_model, tmp_path):
    """A price made by the model from a z-spread (or a yield) is solved back within the accuracy, and == pureql."""
    m0 = new_model(COVERAGE)
    rows, sources = [], {}
    grid = (-0.004, 0.0, 0.0125, 0.03) if what == "zspread" else (0.005, 0.02, 0.045, 0.08)
    for k, (s, t) in enumerate(items(m0)):
        v = m0.Valuation[s, t]
        for b in range(m0.Data.n_bonds()):
            if not v.is_tradable(b):
                continue
            x0 = grid[(b + k) % len(grid)]
            clean = (b + k) % 2 == 0
            if what == "zspread":
                px = v.clean_from_z(b, x0) if clean else v.dirty_from_z(b, x0)
            else:
                px = v.clean_from_yield(b, x0) if clean else v.dirty_from_yield(b, x0)
            key = m0.Data.bond_keys()[b]
            rows.append((s, t, key, px, "Clean" if clean else "Dirty"))
            sources[(s, t, b)] = x0
    d = tmp_path / "inputs"
    write_inputs_with_prices(COVERAGE, d, rows)
    m = new_model(d, nontradable_policy=1, solver_error_policy=0)
    prices, ylds = read_quotes(d)
    worst = 0.0
    bad = []
    for (s, t, b), x0 in sources.items():
        got = mrun(getattr(m.Valuation[s, t], what), b)
        exp = pq_analytics(m, s, t, b, (), prices, ylds, brent_too=False)[what]
        if got != exp:
            bad.append(f"({s}, {t}) b={b}: model {got} vs pureql {exp}")
            continue
        worst = max(worst, abs(value(got) - x0))
    assert not bad, "\n".join(bad[:20])
    assert len(sources) > 60
    assert worst < 1e-9, worst


def test_nontradable_policies(new_model):
    """QUIRK Q-04: a matured bond under NT_ENGINE (NaN / 0.0) and NT_RAISE (pureql's message)."""
    me = new_model(DEMO, output_level=3)
    mr = new_model(DEMO, nontradable_policy=1)
    b = me.Data.bond_keys().index("ZCB_2006")
    ve, vr = me.Valuation[1, 0], mr.Valuation[1, 0]
    assert not ve.is_tradable(b)
    for name in ("ytm", "risk_yield", "zspread") + RISK_CELLS:
        assert math.isnan(getattr(ve, name)(b)), name
    assert ve.dirty_from_yield(b, 0.03) == 0.0 and ve.clean_from_yield(b, 0.03) == 0.0
    c = curve_inputs(mr, 1, 0)
    with pq_settings(c["vdate"], 0, -1):
        bond = pq.pq_bond(mr, b)
        s_date = bond.settlementDate(pq.pq_date(c["vdate"]))
        exp = prun(BondFunctions.bondYield, bond, Price(80.0, Price.Clean), pq.pq_daycounter(2), ql.Compounded,
                   ql.Annual, s_date)
    assert exp[0] == "raise" and exp[1].startswith("non tradable at ")
    for name in ("ytm", "risk_yield") + RISK_CELLS:
        assert mrun(getattr(vr, name), b) == exp, name
    assert mrun(vr.dirty_from_yield, b, 0.03) == exp


def test_error_policies(new_model, tmp_path):
    """ERR_RAISE gives pureql's messages; ERR_NAN gives NaN exactly there and the same values elsewhere."""
    rows = [(1, 0, "C01_HEADLINE", -5.0, "Clean"),  # no sign change: checkSign fails
            (1, 0, "C12_ZCB_TARGET_10Y", 72.0, "Clean")]
    d = tmp_path / "inputs"
    write_inputs_with_prices(COVERAGE, d, rows)
    refs = dict(yield_max_evaluations=4, zspread_max_evaluations=4, nontradable_policy=1)
    mr = new_model(d, solver_error_policy=0, **refs)
    mn = new_model(d, solver_error_policy=1, **refs)
    prices, ylds = read_quotes(d)
    seen = set()
    for s, t in items(mr):
        vr, vn = mr.Valuation[s, t], mn.Valuation[s, t]
        for b in range(mr.Data.n_bonds()):
            exp = pq_analytics(mr, s, t, b, (), prices, ylds, brent_too=False)
            for k in ("ytm", "zspread") + RISK_CELLS:
                if k not in exp:
                    continue
                gr, gn = mrun(getattr(vr, k), b), mrun(getattr(vn, k), b)
                assert gr == exp[k], (s, t, b, k, gr, exp[k])
                if gr[0] == "raise" and gr[1].startswith("non tradable at "):
                    assert gn == gr  # the NT policy, not the ERR policy
                elif gr[0] == "raise":
                    seen.add(gr[1].split(" ")[0])
                    assert gn == ("ok", ("f", "nan")), (s, t, b, k, gn)
                else:
                    assert gn == gr, (s, t, b, k)
    # a sign-check failure, a bracketing or evaluation-budget failure and the Macaulay rule all occurred
    assert {"the", "compounded"} <= seen, seen
    assert seen & {"unable", "maximum"}, seen


def test_result_frame_levels(new_model):
    m1 = new_model(COVERAGE, solver_error_policy=1)
    m3 = new_model(COVERAGE, solver_error_policy=1, output_level=3)
    base = list(m1.Valuation[1, 0].result_frame().columns)
    assert base[-2:] == ["tradable", "expired"]
    df = m3.Valuation[1, 0].result_frame()
    assert list(df.columns) == base + ["ytm", "risk_yield", "duration_simple", "duration_modified",
                                       "duration_macaulay", "convexity", "bpv", "yvbp", "zspread"]
    v = m3.Valuation[1, 0]
    for b in range(m3.Data.n_bonds()):
        assert bits(float(df["ytm"][b])) == bits(v.ytm(b))
        assert bits(float(df["zspread"][b])) == bits(v.zspread(b))


def test_calibrate_spreads(tmp_path):
    """The tool's spreads reproduce the quoted prices at t = 0 and are fed to every t."""
    spec = importlib.util.spec_from_file_location("calibrate_spreads", ROOT / "tools" / "calibrate_spreads.py")
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)
    out = tmp_path / "calibrated"
    result = tool.calibrate(DEMO, out)
    assert set(result) == {(1, "ZCB_10Y"), (2, "ZCB_10Y")}
    m = mx.read_model(MODEL_DIR, name=f"AnSmokeCal{next(_COUNT)}")
    try:
        m.Data.input_dir = str(out)
        m.Data.check_inputs()
        b = m.Data.bond_keys().index("ZCB_10Y")
        for (s, key), z in result.items():
            v = m.Valuation[s, 0]
            assert v.has_spread(b) and v.spread(b) == z
            assert bits(v.clean_price(b)) == bits(v.clean_from_z(b, z))
            assert abs(v.clean_price(b) - 80.0) < 1e-6
            for t in range(m.Data.n_times()):
                assert m.Valuation[s, t].spread(b) == z
    finally:
        m.close()
