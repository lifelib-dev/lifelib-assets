"""Phase 4 analytics against QuantLib 1.41 (the SWIG oracle), at tier T2 (DECISIONS.md D-2, plan "Fidelity policy").

The bit-exact reference is pureql (the other files of this directory). Here
the model is compared with the installed QuantLib 1.41 binding at T2
(``helpers/approx.py``: relative 1e-12 with an absolute floor of 1e-14 for
closed forms, absolute 1e-11 for a solver output). Every test restores
QuantLib's Settings.

Oracle skew OS-10 shapes what is compared (quantlib-migration
``tests/helpers/oracle_skew.py``, README "How good is it?"): QuantLib 1.41
predates the v1.43 ``IrrFinder`` fix (#2589), whose derivative the model's
NewtonSafe uses and whose objective sign 1.41 has flipped. So:

1. the model's NewtonSafe ``ytm`` is NOT compared with a 1.41 yield. At the
   model's yield, 1.41's own pricer is asked instead: ``CashFlows.npv`` /
   ``BondFunctions.cleanPrice`` / ``duration`` / ``convexity`` /
   ``basisPointValue`` / ``yieldValueBasisPoint`` at
   ``InterestRate(ytm, ydc, ycomp, yfreq)`` against the model's [D] Cells at
   the same yield (T2), and 1.41's npv at that yield reproduces the model's
   target ``y_target(b)`` to the price error the solver accuracy allows;
2. the model's Brent option (``yield_solver = 1``, accuracy 1e-12) against
   1.41's ``BondFunctions.yieldBrent`` (call shape M-13) at the same price
   and accuracy: T2 solver, and the same error/no-error outcome;
3. the model's ``zspread`` (accuracy 1e-12) against 1.41's
   ``BondFunctions.zSpread`` - the deprecated day-counter overload, the only
   one 1.41 binds (call shape M-15; its day counter is ignored) - at the same
   price: input prices, and the round-trip mode (``zspread_price_source = 1``,
   the engine clean price), at absolute 1e-11.

Known gaps of the oracle, by design (as in ``tests/pv/test_pv_oracle.py``):
bonds with a ``first_period_day_counter`` are port-only (1.41 binds none);
only the default flow-inclusion flags are compared; 1.41 has no
``CashFlows.yieldValueBasisPoint``, so the bond-level function is used.
"""

import contextlib
import importlib.util
import math

import pytest

from helpers import pureql_val as pv
from helpers.approx import T2_ABSOLUTE, T2_RELATIVE, soft
from helpers.model import MODEL_DIR

QL = pytest.importorskip("QuantLib")

pytestmark = pytest.mark.oracle

ROOT = MODEL_DIR.parents[1]
DEMO = ROOT / "bond_portfolio"
COVERAGE = ROOT / "tools" / "cy" / "sample_inputs"
SETS = {"demo": DEMO, "coverage": COVERAGE}
POINTS = [(s, t) for s in (1, 2) for t in range(4)]


def _load_pv_oracle():
    """The QuantLib 1.41 builders of tests/pv/test_pv_oracle.py (bond, curve, Settings), reused as they are."""
    spec = importlib.util.spec_from_file_location("analytics_pv_oracle", ROOT / "tests" / "pv" / "test_pv_oracle.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


PVO = _load_pv_oracle()


@pytest.fixture(autouse=True)
def quantlib_settings_restored():
    s = QL.Settings.instance()
    before = (s.evaluationDate, s.includeReferenceDateEvents, s.includeTodaysCashFlows)
    yield
    after = (s.evaluationDate, s.includeReferenceDateEvents, s.includeTodaysCashFlows)
    assert after == before, f"QuantLib Settings changed by the test: {before} -> {after}"


@contextlib.contextmanager
def ql_point(model, scen_id, t, b):
    """QuantLib's bond (None if 1.41 cannot build it), plain curve and settlement date of a bond-point."""
    c = pv.curve_inputs(model, scen_id, t)
    with PVO.ql_settings(c["vdate"]):
        bond = PVO.ql_bond(model, b)
        if bond is None:
            yield None, None, None, c
            return
        yield bond, PVO.ql_curve(c), bond.settlementDate(QL.Date(c["vdate"])), c


def ql_rate(model, b, y):
    ydc, ycomp, yfreq = pv.bond_inputs_of(model, b)
    return QL.InterestRate(float(y), PVO.ql_daycounter(ydc), ycomp, yfreq)


def ql_price(amount, ptype):
    return QL.BondPrice(float(amount), QL.BondPrice.Clean if ptype == pv.PRICE_CLEAN else QL.BondPrice.Dirty)


def t2_close(a, b, rel=T2_RELATIVE, floor=T2_ABSOLUTE):
    if math.isnan(a) or math.isnan(b):
        return math.isnan(a) and math.isnan(b)
    if math.isinf(a) or math.isinf(b):
        return a == b
    return abs(a - b) <= max(floor, rel * max(abs(a), abs(b)))


# --------------------------------------------------------------------------- 1. QuantLib's pricer at the model's yield
@pytest.mark.parametrize("scen_id,t", POINTS)
@pytest.mark.parametrize("name", list(SETS))
def test_quantlib_at_the_model_yield(set_model, name, scen_id, t):
    """1.41's npv, clean price and risk at the model's NewtonSafe ytm == the model's [D] Cells there (T2)."""
    m = set_model(name, SETS[name])
    item = m.Valuation[scen_id, t]
    keys = list(m.Data.bond_keys())
    compared = 0
    with soft(f"QuantLib at the model yield, {name} ({scen_id}, {t})") as s:
        for b in range(m.Data.n_bonds()):
            if not item.is_tradable(b):
                continue
            g = pv.run_model(item.cells["ytm"], b)
            if g[0] != "ok" or math.isnan(g[1]):
                continue
            y = g[1]
            with ql_point(m, scen_id, t, b) as (bond, _, st, _c):
                if bond is None:
                    continue
                ir = ql_rate(m, b, y)
                ycomp = pv.bond_inputs_of(m, b)[1]
                want = {
                    "npv_yield": QL.CashFlows.npv(bond.cashflows(), ir, False, st, st),
                    "clean_from_yield": QL.BondFunctions.cleanPrice(bond, ir, st),
                    "simple_duration_y": QL.BondFunctions.duration(bond, ir, QL.Duration.Simple, st),
                    "modified_duration_y": QL.BondFunctions.duration(bond, ir, QL.Duration.Modified, st),
                    "convexity_y": QL.BondFunctions.convexity(bond, ir, st),
                    "bpv_y": QL.BondFunctions.basisPointValue(bond, ir, st),
                    "yvbp_y": QL.BondFunctions.yieldValueBasisPoint(bond, ir, st),
                }
                if ycomp == pv.COMP_COMPOUNDED:
                    want["macaulay_duration_y"] = QL.BondFunctions.duration(bond, ir, QL.Duration.Macaulay, st)
            for k, w in want.items():
                got = item.cells[k](b, y)
                s.check(t2_close(got, w), f"{keys[b]} {k}({y!r}): model {got!r} vs QuantLib {w!r}")
            # the root is a root of 1.41's pricer too, to the price error the accuracy allows
            target = item.cells["y_target"](b)
            slope = abs(item.cells["modified_duration_y"](b, y) * item.cells["npv_yield"](b, y))
            bound = max(T2_ABSOLUTE, T2_RELATIVE * abs(target), 10.0 * m.Data.yield_accuracy * slope)
            s.check(abs(want["npv_yield"] - target) <= bound,
                    f"{keys[b]}: 1.41 npv at the model ytm {want['npv_yield']!r} vs target {target!r} "
                    f"(bound {bound:g})")
            compared += 1
    assert compared > 0


# --------------------------------------------------------------------------- 2. Brent vs yieldBrent
@pytest.mark.parametrize("scen_id,t", POINTS)
@pytest.mark.parametrize("name", list(SETS))
def test_brent_yield_vs_yieldBrent(set_model, name, scen_id, t):
    """The model's Brent ytm (accuracy 1e-12) vs 1.41 ``yieldBrent`` at the same price: T2 solver, same outcome."""
    m = set_model(f"{name}_brent", SETS[name], yield_solver=pv.YIELD_BRENT, yield_accuracy=1e-12)
    item = m.Valuation[scen_id, t]
    keys = list(m.Data.bond_keys())
    compared = 0
    with soft(f"Brent vs yieldBrent, {name} ({scen_id}, {t})") as s:
        for b in range(m.Data.n_bonds()):
            if not item.is_tradable(b):
                continue
            g = pv.run_model(item.cells["ytm"], b)
            with ql_point(m, scen_id, t, b) as (bond, _, st, _c):
                if bond is None:
                    continue
                ydc, ycomp, yfreq = pv.bond_inputs_of(m, b)
                w = PVO.ql_run(QL.BondFunctions.yieldBrent, QL.Brent(), bond,
                               ql_price(item.cells["y_price"](b), item.cells["y_price_type"](b)),
                               PVO.ql_daycounter(ydc), ycomp, yfreq, st, 1e-12, m.Data.yield_guess)
            if not s.check((g[0] == "ok") == (w[0] == "ok"), f"{keys[b]}: model {pv.show(g)} vs QuantLib {w}"):
                continue
            if w[0] == "ok":
                s.t2_solver(g[1], w[1], f"{keys[b]} ytm (Brent)")
                compared += 1
    assert compared > 0


# --------------------------------------------------------------------------- 3. zspread vs zSpread
@pytest.mark.parametrize("source", [0, 1], ids=["input_prices", "roundtrip"])
@pytest.mark.parametrize("name", list(SETS))
def test_zspread_vs_quantlib(set_model, name, source):
    """The model's zspread (accuracy 1e-12) vs 1.41 ``BondFunctions.zSpread`` (M-15) at the same price: abs 1e-11."""
    m = set_model(f"{name}_z{source}", SETS[name], zspread_accuracy=1e-12, zspread_price_source=source)
    keys = list(m.Data.bond_keys())
    q = pv.quote_inputs(m)
    compared = 0
    with soft(f"zspread vs QuantLib, {name} source={source}") as s:
        for scen_id, t in POINTS:
            item = m.Valuation[scen_id, t]
            for b in range(m.Data.n_bonds()):
                if not item.is_tradable(b):
                    continue
                px = q["price"].get((scen_id, t, keys[b]))
                if px is None:
                    if source == 0:
                        continue
                    px = (item.clean_price(b), pv.PRICE_CLEAN)
                g = pv.run_model(item.cells["zspread"], b)
                with ql_point(m, scen_id, t, b) as (bond, curve, st, c):
                    if bond is None:
                        continue
                    w = PVO.ql_run(QL.BondFunctions.zSpread, bond, ql_price(*px), curve, curve.dayCounter(),
                                   c["sp_comp"], c["sp_freq"], st, 1e-12, 100, 0.0)
                if not s.check((g[0] == "ok") == (w[0] == "ok"),
                               f"({scen_id}, {t}) {keys[b]}: model {pv.show(g)} vs QuantLib {w}"):
                    continue
                if w[0] == "ok":
                    s.t2_solver(g[1], w[1], f"({scen_id}, {t}) {keys[b]} zspread")
                    compared += 1
    assert compared >= (6 if name == "coverage" and source == 0 else 1)
