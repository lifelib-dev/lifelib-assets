"""Unit tests of the Lib Space (docs/model-contract.md 4.1) against pureql.

Every comparison is EXACT: floats are compared bit for bit (NaN matches NaN),
bools and ints with ``==`` and the same type, and an error raised by pureql
(``ql.Error``) must come out of the model as ``ValueError`` with the same
message text. modelx wraps an exception raised inside a formula in a
``FormulaError``; the original exception is ``mx.get_error()``.

The full sweeps are marked ``slow``; the default run keeps representative
subsets of the same grids.
"""

import itertools
import math
import struct

import modelx as mx
import pytest
from modelx.core.errors import FormulaError

from helpers.model import MODEL_DIR, load_model
from helpers.pureql_ref import ql, pq_comp, pq_date, pq_daycounter, pq_freq
from pureql import _cxx, _state
from pureql.math.comparison import close as pq_close
from pureql.math.comparison import close_enough as pq_close_enough

EPS = 2.220446049250313e-16
INF = math.inf
NAN = math.nan
NULL_DATE = 0
DC_ACT360, DC_ACT365F = 1, 2

COMPS = [0, 1, 2, 3, 4]
FREQS_ALL = [-1, 0, 1, 2, 3, 4, 6, 12, 13, 26, 52, 365, 999]
FREQS_FAST = [-1, 0, 1, 2, 12, 365]


# --------------------------------------------------------------------------- helpers
@pytest.fixture(scope="module")
def lib():
    return load_model().Lib


_PRIVATE_COUNT = itertools.count()


@pytest.fixture
def private_model():
    """A private model instance, closed afterwards (for sweeps and model edits)."""
    m = mx.read_model(MODEL_DIR, name=f"LibTest{next(_PRIVATE_COUNT)}")
    yield m
    m.close()


def run_model(fn, *args):
    """("ok", value) or ("err", type, message) with the ORIGINAL exception."""
    try:
        return ("ok", fn(*args))
    except FormulaError:
        e = mx.get_error()
        return ("err", type(e), str(e))


def run_pq(fn, *args):
    """("ok", value) or ("err", type, message); pureql's Error maps to ValueError."""
    try:
        return ("ok", fn(*args))
    except ql.Error as e:
        return ("err", ValueError, str(e))
    except Exception as e:  # e.g. OverflowError of lround, ZeroDivisionError of idiv
        return ("err", type(e), str(e))


def bits(x):
    return struct.pack("<d", x)


def same(mv, pv):
    """Exact equality with the same Python type; floats bit for bit, NaN-aware."""
    if type(mv) is not type(pv):
        return False
    if isinstance(pv, float):
        if math.isnan(pv):
            return math.isnan(mv)
        return bits(mv) == bits(pv)
    return mv == pv


def assert_same(mo, po, ctx):
    assert mo[0] == po[0], f"{ctx}: model {mo} vs pureql {po}"
    if mo[0] == "err":
        assert mo[1] is po[1] and mo[2] == po[2], f"{ctx}: model {mo} vs pureql {po}"
    else:
        assert same(mo[1], po[1]), f"{ctx}: model {mo[1]!r} ({type(mo[1]).__name__}) vs pureql {po[1]!r}"


def pq_rate(r, comp, freq):
    return ql.InterestRate(r, ql.Actual365Fixed(), pq_comp(comp), pq_freq(freq))


# --------------------------------------------------------------------------- _cxx (port rider)
SPECIAL = [0.0, -0.0, INF, -INF, NAN, 5e-324, -5e-324, 1e-308, -1e-308, 1e308, -1e308]

EXP_X = [0.0, -0.0, 1.0, -1.0, 0.5, 709.0, 709.78, 709.79, 710.0, 1000.0, 1e308,
         -745.0, -745.2, -746.0, -1e308, INF, -INF, NAN, 5e-324, -5e-324]

POW_X = SPECIAL + [1.0, -1.0, 2.0, -2.0, 0.5, -0.5, 10.0, -10.0, 1.05, 0.95, -1.05]
POW_Y = SPECIAL + [1.0, -1.0, 2.0, -2.0, 3.0, -3.0, 0.5, -0.5, 1.5, -1.5,
                   400.0, -400.0, 401.0, -401.0, 1023.0, 1025.0, -1075.0, 1e300, -1e300,
                   9007199254740992.0, 9007199254740991.0, 1e20, -1e20, 1.0 / 3.0]

DIV_XY = SPECIAL + [1.0, -1.0, 3.0, -3.0, 0.1, 1e-300, -1e-300]


def test_cxx_exp(lib):
    for x in EXP_X:
        assert_same(run_model(lib.cxx_exp, x), run_pq(_cxx.exp, x), f"exp({x!r})")


def test_cxx_pow(lib):
    for x, y in itertools.product(POW_X, POW_Y):
        assert_same(run_model(lib.cxx_pow, x, y), run_pq(_cxx.pow, x, y), f"pow({x!r}, {y!r})")


def test_cxx_pow_edge_values(lib):
    """The IEEE results the grid is meant to reach, spelled out."""
    assert lib.cxx_pow(10.0, 400.0) == INF
    assert lib.cxx_pow(-10.0, 401.0) == -INF          # overflow keeps the sign of an odd power
    assert lib.cxx_pow(-10.0, 400.0) == INF
    assert math.isnan(lib.cxx_pow(-2.0, 0.5))         # negative base, fractional exponent
    assert lib.cxx_pow(0.0, -3.0) == INF              # zero to a negative power
    assert lib.cxx_pow(-0.0, -3.0) == -INF
    assert lib.cxx_pow(-0.0, -2.0) == INF
    assert lib.cxx_pow(-0.0, -0.5) == INF
    assert bits(lib.cxx_pow(-10.0, -401.0)) == bits(-0.0)


def test_cxx_div(lib):
    for x, y in itertools.product(DIV_XY, DIV_XY):
        assert_same(run_model(lib.cxx_div, x, y), run_pq(_cxx.div, x, y), f"div({x!r}, {y!r})")
    assert lib.cxx_div(1.0, -0.0) == -INF
    assert lib.cxx_div(-1.0, -0.0) == INF
    assert math.isnan(lib.cxx_div(0.0, 0.0))
    assert math.isnan(lib.cxx_div(NAN, 0.0))


def test_is_odd_integer(lib):
    for y in POW_Y + [5.0, -5.0, 7.0000000000000001, 2.5, 1e16 + 1.0, 2.0 ** 53 - 1.0]:
        assert_same(run_model(lib.is_odd_integer, y), run_pq(_cxx._is_odd_integer, y), f"odd({y!r})")


def test_cxx_lround(lib):
    xs = [0.0, -0.0, 0.5, -0.5, 1.5, -1.5, 2.5, -2.5, 0.49999999999999994, -0.49999999999999994,
          1.4999999999999998, 2.0, -2.0, 1e15 + 0.5, -1e15 - 0.5, 4503599627370495.5, 1e300,
          0.25, -0.75, 364.5, 365.49999999, INF, -INF, NAN]
    for x in xs:
        assert_same(run_model(lib.cxx_lround, x), run_pq(_cxx.lround, x), f"lround({x!r})")


def test_cxx_idiv_irem(lib):
    for a, c in itertools.product(range(-13, 14), [-7, -3, -2, -1, 0, 1, 2, 3, 7, 12]):
        assert_same(run_model(lib.cxx_idiv, a, c), run_pq(_cxx.idiv, a, c), f"idiv({a}, {c})")
        assert_same(run_model(lib.cxx_irem, a, c), run_pq(_cxx.irem, a, c), f"irem({a}, {c})")
    assert lib.cxx_idiv(-7, 2) == -3 and lib.cxx_irem(-7, 2) == -1


# --------------------------------------------------------------------------- close / close_enough
def _close_grid():
    tol = 42 * EPS
    base = [0.0, -0.0, 1.0, -1.0, 100.0, 1e-300, -1e-300, 5e-324, 1e308, -1e308, INF, -INF, NAN,
            tol * tol, -tol * tol, math.nextafter(tol * tol, 0.0), math.nextafter(tol * tol, 1.0)]
    near = []
    for x in (1.0, 100.0, 1e-300, 1e300):
        for k in (1, 41, 42, 43, 84, 85):
            near += [x * (1.0 + k * EPS), x * (1.0 - k * EPS)]
        near += [math.nextafter(x, INF), math.nextafter(x, 0.0)]
    return base + near


def test_close_and_close_enough(lib):
    grid = _close_grid()
    for x, y in itertools.product(grid, grid):
        assert_same(run_model(lib.close, x, y), run_pq(pq_close, x, y), f"close({x!r}, {y!r})")
        assert_same(run_model(lib.close_enough, x, y), run_pq(pq_close_enough, x, y),
                    f"close_enough({x!r}, {y!r})")


def test_close_differs_from_close_enough(lib):
    """The AND / OR difference is reached (one argument much larger than the other)."""
    assert lib.close_enough(1.0, INF) is pq_close_enough(1.0, INF)
    x, y = 1.0, 1.0 + 42 * EPS
    assert lib.close(x, y) is pq_close(x, y)
    assert lib.close_enough(x, y) is pq_close_enough(x, y)
    hits = [(x, y) for x, y in itertools.product(_close_grid(), repeat=2)
            if pq_close(x, y) != pq_close_enough(x, y)]
    assert hits, "the grid never separates close from close_enough"


# --------------------------------------------------------------------------- InterestRate
RATES = [-3.0, -2.0, -1.0, -0.5, -0.01, -0.0, 0.0, 1e-12, 0.01, 0.05, 0.123456789, 1.0, 5.0, 100.0, 1e300]
TIMES = [-1.0, -1e-300, NAN, -0.0, 0.0, 1e-300, 1e-12, 1.0 / 365.0, 0.25, 0.5, 1.0 / 3.0, 1.0, 2.0,
         30.0, 184.0, 1e6, INF]
COMPOUNDS = [NAN, -INF, -1.0, -0.0, 0.0, 5e-324, 1e-300, 0.5, math.nextafter(1.0, 0.0), 1.0,
             math.nextafter(1.0, 2.0), 1.05, 2.0, 1e300, INF]


def test_check_rate(lib):
    for comp, freq in itertools.product(COMPS, FREQS_ALL):
        mo = run_model(lib.check_rate, comp, freq)
        po = run_pq(lambda: (pq_rate(0.05, comp, freq), True)[1])
        assert_same(mo, po, f"check_rate({comp}, {freq})")


def _cf_sweep(lib, freqs):
    for comp, freq in itertools.product(COMPS, freqs):
        rates = RATES + ([-float(freq)] if freq > 0 else [])  # 1 + r/f == 0 exactly
        for r, t in itertools.product(rates, TIMES):
            ctx = f"(r={r!r}, comp={comp}, freq={freq}, t={t!r})"
            assert_same(run_model(lib.compound_factor, r, comp, freq, t),
                        run_pq(lambda: pq_rate(r, comp, freq).compoundFactor(t)), "compound_factor" + ctx)
            assert_same(run_model(lib.discount_factor, r, comp, freq, t),
                        run_pq(lambda: pq_rate(r, comp, freq).discountFactor(t)), "discount_factor" + ctx)


def test_compound_and_discount_factor(lib):
    _cf_sweep(lib, FREQS_FAST)


@pytest.mark.slow
def test_compound_and_discount_factor_full(private_model):
    _cf_sweep(private_model.Lib, FREQS_ALL)


def test_compound_factor_edge_values(lib):
    """IEEE-05 outcomes through the model."""
    assert math.isnan(lib.compound_factor(-3.0, 1, 2, 0.25))  # negative base, fractional exponent
    assert lib.compound_factor(-2.0, 1, 2, 0.5) == 0.0         # base exactly zero
    assert lib.discount_factor(-2.0, 1, 2, 0.5) == INF
    assert lib.compound_factor(5.0, 2, -1, 184.0) == INF       # exp overflow
    assert lib.compound_factor(100.0, 1, 1, 184.0) == INF      # pow overflow
    # t == 1/f sits on the SIMPLE side of SimpleThenCompounded and the COMPOUNDED side of the other
    assert lib.compound_factor(0.05, 3, 2, 0.5) == 1.025
    assert lib.compound_factor(0.05, 4, 2, 0.5) == pq_rate(0.05, 4, 2).compoundFactor(0.5)


def _implied_sweep(lib, freqs):
    for comp, freq in itertools.product(COMPS, freqs):
        for c, t in itertools.product(COMPOUNDS, TIMES):
            assert_same(run_model(lib.implied_rate, c, comp, freq, t),
                        run_pq(lambda: ql.InterestRate.impliedRate(
                            c, ql.Actual365Fixed(), pq_comp(comp), pq_freq(freq), t).rate()),
                        f"implied_rate(c={c!r}, comp={comp}, freq={freq}, t={t!r})")


def test_implied_rate(lib):
    _implied_sweep(lib, FREQS_FAST)


@pytest.mark.slow
def test_implied_rate_full(private_model):
    _implied_sweep(private_model.Lib, FREQS_ALL)


def test_implied_rate_edge_values(lib):
    # IEEE-08: a vanishing t overflows the power to inf
    assert lib.implied_rate(2.0, 1, 1, 1e-300) == INF
    # Once: the inner divisions are by zero and the constructor's message wins
    mo = run_model(lib.implied_rate, 2.0, 1, 0, 1.0)
    assert mo == ("err", ValueError, "frequency not allowed for this interest rate")
    # compound == 1.0 short-circuits before the positive-time check
    assert lib.implied_rate(1.0, 1, 2, 0.0) == 0.0
    assert run_model(lib.implied_rate, 1.0, 1, 2, -1.0) == ("err", ValueError, "non negative time (-1) required")


def _equivalent_sweep(lib, rates, freqs, times, freqs2):
    for comp, freq, comp2, freq2 in itertools.product(COMPS, freqs, COMPS, freqs2):
        for r, t in itertools.product(rates, times):
            assert_same(run_model(lib.equivalent_rate, r, comp, freq, t, comp2, freq2),
                        run_pq(lambda: pq_rate(r, comp, freq).equivalentRate(
                            pq_comp(comp2), pq_freq(freq2), t).rate()),
                        f"equivalent_rate(r={r!r}, {comp}, {freq}, t={t!r}, {comp2}, {freq2})")


def test_equivalent_rate(lib):
    _equivalent_sweep(lib, [-3.0, -0.5, 0.0, 0.05, 1.0], [-1, 0, 1, 2, 12],
                      [-1.0, 0.0, 1e-300, 0.5, 1.0, 30.0], [-1, 0, 1, 4, 365])


@pytest.mark.slow
def test_equivalent_rate_full(private_model):
    _equivalent_sweep(private_model.Lib, RATES, FREQS_ALL, TIMES, FREQS_ALL)


# --------------------------------------------------------------------------- date forms
def stub_year_fraction(dc, d1, d2, r1, r2):
    """Actual/365 (Fixed) and Actual/360, as pureql computes them (daysBetween = float(d2 - d1))."""
    if dc == 2:
        return float(d2 - d1) / 365.0
    if dc == 1:
        return (float(d2 - d1) + 0.0) / 360.0
    raise ValueError("stub: day counter not supported")


DATE_PAIRS = [(45000, 45000), (45000, 45001), (45000, 45182), (45000, 45365), (45000, 46000),
              (45000, 56000), (45000, 44999), (45001, 45000), (367, 109574), (109574, 367)]
REF_PAIRS = [(NULL_DATE, NULL_DATE), (44900, 45100)]


def _dates_sweep(lib, dcs):
    rates = [-2.0, -0.5, 0.0, 0.05, 1.0]
    compounds = [0.5, 1.0, 1.05]
    for dc, (d1, d2), (r1, r2) in itertools.product(dcs, DATE_PAIRS, REF_PAIRS):
        pdc = pq_daycounter(dc)
        pd1, pd2, pr1, pr2 = pq_date(d1), pq_date(d2), pq_date(r1), pq_date(r2)
        for comp, freq in itertools.product(COMPS, [-1, 0, 2, 12]):
            for r in rates:
                ctx = f"(r={r}, comp={comp}, freq={freq}, dc={dc}, {d1}, {d2}, {r1}, {r2})"
                assert_same(
                    run_model(lib.compound_factor_dates, r, comp, freq, dc, d1, d2, r1, r2),
                    run_pq(lambda: ql.InterestRate(r, pdc, pq_comp(comp), pq_freq(freq))
                           .compoundFactor(pd1, pd2, pr1, pr2)),
                    "compound_factor_dates" + ctx)
                for comp2, freq2 in [(0, -1), (1, 1), (2, -1), (3, 2), (4, 4), (1, 0)]:
                    assert_same(
                        run_model(lib.equivalent_rate_dates, r, comp, freq, dc, d1, d2, r1, r2, comp2, freq2),
                        run_pq(lambda: ql.InterestRate(r, pdc, pq_comp(comp), pq_freq(freq))
                               .equivalentRate(pdc, pq_comp(comp2), pq_freq(freq2), pd1, pd2, pr1, pr2).rate()),
                        f"equivalent_rate_dates{ctx} -> ({comp2}, {freq2})")
            for c in compounds:
                assert_same(
                    run_model(lib.implied_rate_dates, c, dc, comp, freq, d1, d2, r1, r2),
                    run_pq(lambda: ql.InterestRate.impliedRate(
                        c, pdc, pq_comp(comp), pq_freq(freq), pd1, pd2, pr1, pr2).rate()),
                    f"implied_rate_dates(c={c}, dc={dc}, {comp}, {freq}, {d1}, {d2}, {r1}, {r2})")


def test_date_forms_with_stub_year_fraction(private_model):
    """The Lib wiring of the date forms, with Dates.year_fraction replaced in a private model."""
    dates = private_model.Dates
    if "year_fraction" in dates.cells:
        dates.cells["year_fraction"].formula = stub_year_fraction
        dates.cells["year_fraction"].is_cached = False
    else:
        dates.new_cells("year_fraction", formula=stub_year_fraction, is_cached=False)
    _dates_sweep(private_model.Lib, [DC_ACT360, DC_ACT365F])


def test_date_forms_with_dates_space(private_model):
    """Integration with the Dates Space's own year_fraction (Actual/360, Actual/365 Fixed)."""
    if "year_fraction" not in private_model.Dates.cells:
        pytest.skip("Dates.year_fraction is not implemented yet")
    _dates_sweep(private_model.Lib, [DC_ACT360, DC_ACT365F])


def test_date_form_error_message(lib):
    """d1 > d2 is checked before any year fraction is taken, with pureql's text."""
    po = run_pq(lambda: ql.InterestRate(0.05, ql.Actual365Fixed(), pq_comp(0), pq_freq(1))
                .compoundFactor(pq_date(45001), pq_date(45000)))
    assert po == ("err", ValueError, "d1 (March 16th, 2023) later than d2 (March 15th, 2023)")
    assert run_model(lib.compound_factor_dates, 0.05, 0, 1, DC_ACT365F, 45001, 45000, 0, 0) == po
    assert run_model(lib.implied_rate_dates, 1.05, DC_ACT365F, 0, 1, 45001, 45000, 0, 0) == po
    assert run_model(lib.equivalent_rate_dates, 0.05, 0, 1, DC_ACT365F, 45001, 45000, 0, 0, 1, 1) == po
    # the constructor guard comes before the date check
    assert run_model(lib.compound_factor_dates, 0.05, 1, 0, DC_ACT365F, 45001, 45000, 0, 0) == \
        ("err", ValueError, "frequency not allowed for this interest rate")


def test_long_date(lib):
    serials = [NULL_DATE] + list(range(367, 109575, 251)) + list(range(45000, 45070)) + [109574]
    for d in serials:
        assert lib.long_date(d) == str(pq_date(d)), d


# --------------------------------------------------------------------------- has_occurred
@pytest.fixture
def pq_settings():
    """pureql Settings, restored EXACTLY afterwards (SavedSettings alone anchors an unset date, Q-08)."""
    before = _state.snapshot_all()
    yield ql.Settings.instance()
    _state.restore_all(before)


TRI = {-1: None, 0: False, 1: True}


def test_has_occurred_full_matrix(lib, pq_settings):
    E = 45000
    n = 0
    for ref in (E, E - 5, E + 5, NULL_DATE):
        base = ref if ref != NULL_DATE else E
        for d in (base - 1, base, base + 1):
            for include, todays, ref_events in itertools.product((-1, 0, 1), (-1, 0, 1), (0, 1)):
                with ql.SavedSettings():
                    s = ql.Settings.instance()
                    s.setEvaluationDate(pq_date(E))
                    s.setIncludeReferenceDateEvents(bool(ref_events))
                    s.setIncludeTodaysCashFlows(TRI[todays])
                    po = run_pq(lambda: ql.SimpleCashFlow(1.0, pq_date(d)).hasOccurred(pq_date(ref), TRI[include]))
                mo = run_model(lib.has_occurred, d, ref, include, E, todays, ref_events)
                assert_same(mo, po, f"has_occurred(d={d}, ref={ref}, include={include}, E={E}, "
                                    f"todays={todays}, ref_events={ref_events})")
                n += 1
    assert n == 4 * 3 * 18


def test_has_occurred_todays_override(lib):
    """includeTodaysCashFlows overrides the flag only when ref is the evaluation date (or null)."""
    E = 45000
    # ref == eval: todays=1 includes today's flow although include=0 would exclude it
    assert lib.has_occurred(E, E, 0, E, 1, 0) is False
    assert lib.has_occurred(E, E, 1, E, 0, 0) is True
    # ref != eval: the flag stands
    assert lib.has_occurred(E + 5, E + 5, 0, E, 1, 0) is True
    # null ref: the evaluation date is used and the override applies
    assert lib.has_occurred(E, NULL_DATE, -1, E, -1, 1) is False


# --------------------------------------------------------------------------- trading_ex_coupon
class _ExCouponFlow(ql.SimpleCashFlow):
    """A pureql cash flow with a given ex-coupon date (test double)."""

    def __init__(self, pay, ex):
        super().__init__(1.0, pay)
        self._ex = ex

    def exCouponDate(self):
        return self._ex


def test_trading_ex_coupon(lib):
    for ref in (45000, 45100):
        for ex in (NULL_DATE, ref - 1, ref, ref + 1):
            pq_flow = _ExCouponFlow(pq_date(ref + 30), pq_date(ex))
            assert_same(run_model(lib.trading_ex_coupon, ex, ref),
                        run_pq(pq_flow.tradingExCoupon, pq_date(ref)),
                        f"trading_ex_coupon({ex}, {ref})")
    assert lib.trading_ex_coupon(NULL_DATE, 45000) is False
    assert lib.trading_ex_coupon(45000, 45000) is True
    assert lib.trading_ex_coupon(45001, 45000) is False


# --------------------------------------------------------------------------- structure
def test_lib_cells_are_uncached(lib):
    names = ["cxx_exp", "cxx_pow", "cxx_div", "is_odd_integer", "cxx_lround", "cxx_idiv", "cxx_irem",
             "close", "close_enough", "check_rate", "compound_factor", "discount_factor", "implied_rate",
             "equivalent_rate", "compound_factor_dates", "implied_rate_dates", "equivalent_rate_dates",
             "has_occurred", "trading_ex_coupon", "long_date"]
    for name in names:
        assert not lib.cells[name].is_cached, name
    assert lib.nan_value() != lib.nan_value() and lib.inf_value() == INF
