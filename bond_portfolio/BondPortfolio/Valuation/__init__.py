# modelx: pseudo-python
# This file is part of a modelx model.
# It can be imported as a Python module, but functions defined herein
# are model formulas and may not be executable as standard Python.

"""Valuation of every bond at valuation date ``t`` under scenario ``scen_id``.

One item ``Valuation[scen_id, t]`` stands in for QuantLib's
``Settings.evaluationDate = v`` (``v = vdate()``, the ``t``-th valuation
date) together with the curve, the spreads and the pricing engines of that
date: a ZeroCurve (linear in the zero rate, flat-forward extrapolation) or a
FlatForward curve with reference date ``v``, a ZeroSpreadedTermStructure on
top of it for the bonds that have a spread, and a DiscountingBondEngine.
Every date is explicit; nothing is global.

Every bond quantity is a Cells over the bond index ``b`` and reads the
portfolio leg of :mod:`~.BondPortfolio.Legs` (the flows of ``b`` are ``p`` in
``[cf_lo[b], cf_lo[b+1])``, in leg order). Curve quantities are Cells over
the day offset ``kd = d - vdate()``, shared by all bonds of the item.

**Occurrence roles** (``role``; one predicate, ``lib.has_occurred``, with
evaluation date ``vdate()``):

* ``ROLE_ENGINE`` (0): reference ``vdate()``, include flag
  :func:`engine_flag` (NPV);
* ``ROLE_SETTLE`` (1): reference ``settle(b)``, include flag False
  (settlement value, accrued, prices);
* ``ROLE_EXPIRY`` (2): reference ``vdate()``, include flag None
  (``Bond.isExpired``).

Bonds without a spread are valued on the plain curve
(``ZeroSpreaded(curve, 0)`` is not bit-identical to ``curve``).

**Analytics** (docs/model-contract.md 4.8), all at ``settle(b)`` like
pureql's BondFunctions: the yield family over ``(b, y)`` in the bond's yield
conventions (the stepwise :func:`npv_yield` and the accumulated-time
durations and convexity of QUIRK Q-09, BPV, YVBP, prices from a yield); the
solved yield :func:`ytm` and z-spread :func:`zspread` (:func:`solve`:
Solver1D bracketing, then NewtonSafe or Brent); the risk measures at
:func:`risk_yield`. ``data.nontradable_policy`` and
``data.solver_error_policy`` decide what a non-tradable bond and a failed
solve give (NaN, 0.0 or pureql's error).

Derived from QuantLib (BSD-3-Clause); see NOTICE.md."""

from modelx.serialize.jsonvalues import *

_formula = lambda scen_id, t: None

_bases = []

_allow_none = None

_spaces = []

# ---------------------------------------------------------------------------
# Cells

def vdate():
    """The valuation date ``v`` (int serial): ``Settings.evaluationDate`` and the curve's reference date."""
    return int(data.val_date_arr()[t])


def srow():
    """The row of the [S, T] input arrays: ``scen_id - 1``."""
    return scen_id - 1


def curve_type():
    """The curve type of (scen_id, t): ``CURVE_ZERO`` or ``CURVE_FLAT``."""
    row = srow()
    return int(data.c_type_arr()[row, t])


def curve_dc():
    """The curve's day-counter code."""
    row = srow()
    return int(data.c_dc_arr()[row, t])


def curve_comp():
    """The compounding the curve rates are quoted in (zero rates or the flat forward)."""
    row = srow()
    return int(data.c_comp_arr()[row, t])


def curve_freq():
    """The frequency the curve rates are quoted with."""
    row = srow()
    return int(data.c_freq_arr()[row, t])


def spread_comp():
    """The compounding of the zero spreads (``ZeroSpreadedTermStructure``'s ``comp``)."""
    row = srow()
    return int(data.c_sp_comp_arr()[row, t])


def spread_freq():
    """The frequency of the zero spreads (``ZeroSpreadedTermStructure``'s ``freq``)."""
    row = srow()
    return int(data.c_sp_freq_arr()[row, t])


def node_lo():
    """Index of node 0 of this curve in ``data.n_date_arr()`` / ``data.n_rate_arr()``."""
    row = srow()
    return int(data.n_lo_arr()[row, t])


def n_nodes():
    """The number of curve nodes (0 for a FlatForward curve)."""
    row = srow()
    return int(data.n_cnt_arr()[row, t])


def curve_extrapolate():
    """Whether the curve allows extrapolation (``enableExtrapolation()``)."""
    row = srow()
    return int(data.c_extrap_arr()[row, t]) != 0


def flat_rate():
    """The FlatForward rate (NaN for a ZeroCurve)."""
    row = srow()
    return float(data.c_flat_arr()[row, t])


def engine_flag():
    """The engine's include flag (0/1): F if F != -1 else R (``Proj.engine_include``)."""
    return int(proj.engine_include())


def todays():
    """``includeTodaysCashFlows`` T (tri-state: -1 None, 0, 1)."""
    return int(data.include_todays_cashflows)


def ref_events():
    """``includeReferenceDateEvents`` R (0/1)."""
    return int(data.include_reference_date_events)


def curve_ok():
    """True if the curve inputs of (scen_id, t) are usable; raises ``ValueError`` otherwise.

    ZeroCurve: at least 2 and at most ``MAX_NODES`` nodes, node 0 on the
    valuation date (the reference date), strictly increasing node dates
    whose times are not ``close`` (``setupTimes``), and the InterestRate
    guard of the quoted convention when it is converted. FlatForward: the
    InterestRate guard of the flat rate. Other curve types raise.

    Derived from QuantLib (BSD-3-Clause); see NOTICE.md.
    """
    # ported from pureql/termstructures/yield_/zerocurve.py (ql/zerocurve.hpp:249-276), QuantLib v1.43, BSD-3-Clause
    # ported from pureql/termstructures/interpolatedcurve.py (ql/interpolatedcurve.hpp:100-115), QuantLib v1.43, BSD-3-Clause
    # ported from pureql/termstructures/yield_/flatforward.py (ql/flatforward.hpp:107-110), QuantLib v1.43, BSD-3-Clause
    ct = curve_type()
    if ct == CURVE_ZERO:
        n = n_nodes()
        if not (n >= 2):
            raise ValueError("not enough input dates given")
        if n > MAX_NODES:
            raise ValueError("the ZeroCurve has " + str(n) + " nodes, more than MAX_NODES ("
                             + str(MAX_NODES) + ")")
        v = vdate()
        d0 = node_date(0)
        if d0 != v:
            raise ValueError("node 0 of the ZeroCurve (" + lib.long_date(d0)
                             + ") is not the valuation date (" + lib.long_date(v) + ")")
        dp = d0
        tp = node_time(0)
        for nd in range(1, n):
            dn = node_date(nd)
            if not (dn > dp):
                raise ValueError(f"dates not sorted: {lib.long_date(dn)} passed after {lib.long_date(dp)}")
            tn = node_time(nd)
            if not (not lib.close(float(tn), float(tp))):
                raise ValueError(
                    f"two passed dates ({lib.long_date(dp)} and {lib.long_date(dn)}) correspond to the same time "
                    f"under this curve's day count convention ({dates.daycounter_name(curve_dc())})"
                )
            if not (tn > tp):
                raise ValueError("node times must be strictly increasing (node " + str(nd) + ")")
            dp = dn
            tp = tn
        if curve_comp() != COMP_CONTINUOUS:
            lib.check_rate(curve_comp(), curve_freq())
    elif ct == CURVE_FLAT:
        lib.check_rate(curve_comp(), curve_freq())
    else:
        raise ValueError("curve type " + str(ct) + " not supported in this model version")
    return True


def max_time():
    """``maxTime()``: the time of the last node (ZeroCurve), or of ``Date::maxDate()`` (FlatForward).

    Derived from QuantLib (BSD-3-Clause); see NOTICE.md.
    """
    # ported from pureql/termstructure.py (ql/termstructure.hpp:119-121), QuantLib v1.43, BSD-3-Clause
    # ported from pureql/termstructures/yield_/zerocurve.py (ql/zerocurve.hpp:117-122), QuantLib v1.43, BSD-3-Clause
    # ported from pureql/termstructures/yield_/flatforward.py (ql/flatforward.hpp:71), QuantLib v1.43, BSD-3-Clause
    curve_ok()
    if curve_type() == CURVE_ZERO:
        n = n_nodes()
        return node_time(n - 1)
    v = vdate()
    return float(dates.year_fraction(curve_dc(), v, MAX_SERIAL, 0, 0))


def node_date(nd):
    """The date serial of curve node ``nd``."""
    lo = node_lo()
    return int(data.n_date_arr()[lo + nd])


def node_rate_in(nd):
    """The zero rate of curve node ``nd`` as given (in the curve's quoted convention)."""
    lo = node_lo()
    return float(data.n_rate_arr()[lo + nd])


def node_time(nd):
    """``times_[nd]``: ``dayCounter.yearFraction(referenceDate, dates[nd])`` (``setupTimes``).

    Derived from QuantLib (BSD-3-Clause); see NOTICE.md.
    """
    # ported from pureql/termstructures/interpolatedcurve.py (ql/interpolatedcurve.hpp:100-115), QuantLib v1.43, BSD-3-Clause
    v = vdate()
    dn = node_date(nd)
    return float(dates.year_fraction(curve_dc(), v, dn, 0, 0))


def node_zc(nd):
    """``data_[nd]`` after ``ZeroCurve._initialize``: the node's continuous zero rate.

    Converted only if the curve's compounding is not Continuous: node 0 over
    ``dt = 1.0/365`` (its own time is 0.0), the others over ``node_time(nd)``,
    through ``InterestRate(r, dc, comp, freq).equivalentRate(Continuous,
    NoFrequency, t)``.

    Derived from QuantLib (BSD-3-Clause); see NOTICE.md.
    """
    # ported from pureql/termstructures/yield_/zerocurve.py (ql/zerocurve.hpp:249-276), QuantLib v1.43, BSD-3-Clause
    # ported from pureql/interestrate.py (ql/interestrate.hpp:155-159), QuantLib v1.43, BSD-3-Clause
    r = node_rate_in(nd)
    compounding = curve_comp()
    if compounding != COMP_CONTINUOUS:
        # adjusting zero rates to match continuous compounding
        if nd == 0:
            # The first time is 0.0, so we can't use it.
            # We fall back to about one day.
            dt = 1.0 / 365
            return float(lib.equivalent_rate(float(r), compounding, curve_freq(), float(dt),
                                             COMP_CONTINUOUS, FREQ_NO_FREQUENCY))
        tn = node_time(nd)
        return float(lib.equivalent_rate(float(r), compounding, curve_freq(), float(tn),
                                         COMP_CONTINUOUS, FREQ_NO_FREQUENCY))
    return r


def node_slope(nd):
    """``s_[nd]``: the slope of the segment from node ``nd`` to ``nd + 1`` (``nd`` in 0..n-2).

    Derived from QuantLib (BSD-3-Clause); see NOTICE.md.
    """
    # ported from pureql/math/interpolations/linearinterpolation.py (ql/linearinterpolation.hpp:80-88), QuantLib v1.43, BSD-3-Clause
    x1 = node_time(nd + 1)
    x0 = node_time(nd)
    dx = x1 - x0
    y1 = node_zc(nd + 1)
    y0 = node_zc(nd)
    return (y1 - y0) / dx


def node_locate(x):
    """``locate(x)``: the index ``i`` of the node interval ``[x[i], x[i+1])`` holding time ``x``.

    Clamped to the first interval below node 0 and to the last above the
    last node; in between, ``std::upper_bound`` over the first n-1 node times
    (a ``bisect_right``), minus one.

    Derived from QuantLib (BSD-3-Clause); see NOTICE.md.
    """
    # ported from pureql/math/interpolation.py (ql/interpolation.hpp:104-115), QuantLib v1.43, BSD-3-Clause
    n = n_nodes()
    x0 = node_time(0)
    xl = node_time(n - 1)
    if x < x0:
        return 0
    elif x > xl:
        return n - 2
    else:
        lo = 0
        hi = n - 1
        while lo < hi:
            mid = (lo + hi) // 2  # int>=0
            xm = node_time(mid)
            if x < xm:
                hi = mid
            else:
                lo = mid + 1
        return lo - 1


def curve_time(kd):
    """``timeFromReference(d)`` for ``d = vdate() + kd``: ``dayCounter().yearFraction(referenceDate(), d)``.

    Runs :func:`curve_ok` first.

    Derived from QuantLib (BSD-3-Clause); see NOTICE.md.
    """
    # ported from pureql/termstructure.py (ql/termstructure.hpp:133-135), QuantLib v1.43, BSD-3-Clause
    curve_ok()
    v = vdate()
    return float(dates.year_fraction(curve_dc(), v, v + kd, 0, 0))


def range_ok(kd):
    """``checkRange(t, false)`` at ``t = curve_time(kd)``; True, or raises pureql's message.

    ``t >= 0``, then the curve's extrapolation flag, ``t <= maxTime()`` or
    ``close_enough(t, maxTime())``.

    Derived from QuantLib (BSD-3-Clause); see NOTICE.md.
    """
    # ported from pureql/termstructure.py (ql/termstructure.cpp:64-72), QuantLib v1.43, BSD-3-Clause
    tt = curve_time(kd)
    if not (tt >= 0.0):
        raise ValueError(f"negative time ({tt:g}) given")
    if not (curve_extrapolate() or tt <= max_time() or lib.close_enough(float(tt), float(max_time()))):
        raise ValueError(f"time ({tt:g}) is past max curve time ({max_time():g})")
    return True


def zero_c(kd):
    """ZeroCurve ``zeroYieldImpl(t)`` at ``t = curve_time(kd)``: the continuous zero rate.

    Up to the last node, the linear interpolation (extrapolation forced on,
    so below node 0 the first segment); past it, the flat instantaneous
    forward of the last node re-expressed as a zero rate.

    Derived from QuantLib (BSD-3-Clause); see NOTICE.md.
    """
    # ported from pureql/termstructures/yield_/zerocurve.py (ql/zerocurve.hpp:159-169), QuantLib v1.43, BSD-3-Clause
    # ported from pureql/math/interpolation.py (ql/interpolation.hpp:122-125), QuantLib v1.43, BSD-3-Clause
    # ported from pureql/math/interpolation.py (ql/interpolation.hpp:130-133), QuantLib v1.43, BSD-3-Clause
    # ported from pureql/math/interpolations/linearinterpolation.py (ql/linearinterpolation.hpp:89-92), QuantLib v1.43, BSD-3-Clause
    # ported from pureql/math/interpolations/linearinterpolation.py (ql/linearinterpolation.hpp:99-102), QuantLib v1.43, BSD-3-Clause
    tt = curve_time(kd)
    n = n_nodes()
    tl = node_time(n - 1)
    if tt <= tl:
        # interpolation_(t, true): y[i] + (x - x[i]) * s[i]
        i = node_locate(float(tt))
        yi = node_zc(i)
        xi = node_time(i)
        si = node_slope(i)
        return yi + (tt - xi) * si

    # flat fwd extrapolation
    tMax = tl
    zMax = node_zc(n - 1)
    # interpolation_.derivative(tMax): s[locate(tMax)]
    im = node_locate(float(tMax))
    dMax = node_slope(im)
    instFwdMax = zMax + tMax * dMax
    return (zMax * tMax + instFwdMax * (tt - tMax)) / tt


def discount_core(kd):
    """``discountImpl(t)`` at ``t = curve_time(kd)``, without the range check.

    ZeroCurve (ZeroYieldStructure): 1.0 at ``t == 0``, else
    ``exp(-zero_c(kd) * t)``. FlatForward: ``InterestRate(rate, dc, comp,
    freq).discountFactor(t)``, i.e. ``1.0/compoundFactor(t)``.

    Derived from QuantLib (BSD-3-Clause); see NOTICE.md.
    """
    # ported from pureql/termstructures/yield_/zeroyieldstructure.py (ql/zeroyieldstructure.hpp:90-96), QuantLib v1.43, BSD-3-Clause
    # ported from pureql/termstructures/yield_/flatforward.py (ql/flatforward.hpp:102-105), QuantLib v1.43, BSD-3-Clause
    tt = curve_time(kd)
    ct = curve_type()
    if ct == CURVE_ZERO:
        if tt == 0.0:  # this acts as a safe guard in cases where
            return 1.0  # zeroYieldImpl(0.0) would throw.

        r = zero_c(kd)
        try:
            return float(math.exp(-r * tt))
        except (OverflowError, ValueError):
            return float(lib.cxx_exp(float(-r * tt)))
    elif ct == CURVE_FLAT:
        fr = flat_rate()
        return float(lib.discount_factor(float(fr), curve_comp(), curve_freq(), float(tt)))
    else:
        raise ValueError("curve type " + str(ct) + " not supported in this model version")


def discount(kd):
    """``YieldTermStructure.discount(d)`` for ``d = vdate() + kd``: :func:`range_ok`, then :func:`discount_core`.

    Derived from QuantLib (BSD-3-Clause); see NOTICE.md.
    """
    # ported from pureql/termstructures/yieldtermstructure.py (ql/yieldtermstructure.hpp:185-189), QuantLib v1.43, BSD-3-Clause
    # ported from pureql/termstructures/yieldtermstructure.py (ql/yieldtermstructure.cpp:76-96), QuantLib v1.43, BSD-3-Clause
    range_ok(kd)
    return discount_core(kd)


def zs_base(kd):
    """``originalCurve.zeroRate(t, spread_comp, spread_freq, true).rate()`` at ``t = curve_time(kd) > 0``.

    The plain curve's zero rate in the spread's convention: ``compound =
    1.0/discount(t, true)`` (the range check with extrapolation forced on
    admits any ``t >= 0``), then ``InterestRate.impliedRate(compound, dc,
    comp, freq, t)``. Only called by :func:`zs_discount_kd`, after the
    ``t == 0`` guard of ``ZeroYieldStructure.discountImpl``; at ``t == 0``
    (the ``t = dt`` branch of upstream) it raises.

    Derived from QuantLib (BSD-3-Clause); see NOTICE.md.
    """
    # ported from pureql/termstructures/yieldtermstructure.py (ql/yieldtermstructure.cpp:118-127), QuantLib v1.43, BSD-3-Clause
    # ported from pureql/termstructure.py (ql/termstructure.cpp:64-72), QuantLib v1.43, BSD-3-Clause
    tt = curve_time(kd)
    if tt == 0.0:
        raise ValueError("zs_base needs a positive time (ZeroYieldStructure answers 1.0 at t == 0)")
    # discount(t, true): checkRange(t, true)
    if not (tt >= 0.0):
        raise ValueError(f"negative time ({tt:g}) given")
    df = discount_core(kd)
    compound = float(lib.cxx_div(1.0, float(df)))
    return float(lib.implied_rate(float(compound), spread_comp(), spread_freq(), float(tt)))


def zs_discount_kd(kd, z):
    """The ZeroSpreadedTermStructure discount factor at ``d = vdate() + kd`` for a zero spread ``z``.

    ``discount(d)`` on ``ZeroSpreaded(curve, z, spread_comp, spread_freq)``:
    the range check (the original curve's flag and max time); 1.0 at
    ``t == 0``; else ``zeroYieldImpl(t)``, the spread added to
    :func:`zs_base` in the spread's convention and converted back with
    ``equivalentRate(Continuous, NoFrequency, t)``, then ``exp(-r t)``. The
    full round trip, with no algebraic shortcut. The spreaded rate is built
    with ``spread_freq()`` in place of ``zeroRate.frequency()``: the two
    differ only for Simple and Continuous, which never read the frequency.

    Derived from QuantLib (BSD-3-Clause); see NOTICE.md.
    """
    # ported from pureql/termstructures/yieldtermstructure.py (ql/yieldtermstructure.hpp:185-189), QuantLib v1.43, BSD-3-Clause
    # ported from pureql/termstructures/yieldtermstructure.py (ql/yieldtermstructure.cpp:76-96), QuantLib v1.43, BSD-3-Clause
    # ported from pureql/termstructures/yield_/zeroyieldstructure.py (ql/zeroyieldstructure.hpp:90-96), QuantLib v1.43, BSD-3-Clause
    # ported from pureql/termstructures/yield_/zerospreadedtermstructure.py (ql/zerospreadedtermstructure.hpp:142-150), QuantLib v1.43, BSD-3-Clause
    tt = curve_time(kd)
    range_ok(kd)
    if tt == 0.0:  # this acts as a safe guard in cases where
        return 1.0  # zeroYieldImpl(0.0) would throw.

    zeroRate = zs_base(kd)
    spreadedRate = zeroRate + z
    r = float(lib.equivalent_rate(float(spreadedRate), spread_comp(), spread_freq(), float(tt),
                                  COMP_CONTINUOUS, FREQ_NO_FREQUENCY))
    try:
        return float(math.exp(-r * tt))
    except (OverflowError, ValueError):
        return float(lib.cxx_exp(float(-r * tt)))


_is_cached = False


def zdisc(p):
    """The ZeroSpreaded discount factor of flow ``p``: ``zs_discount_kd(cf_date[p] - vdate(), spread(owner))``."""
    v = vdate()
    kd = int(legs.cf_date_arr()[p]) - v
    bo = int(legs.cf_owner_arr()[p])
    sp = spread(bo)
    return zs_discount_kd(kd, float(sp))


def settle_cal(cal, nsd):
    """``calendar.advance(vdate(), nsd, Days)`` on calendar ``cal`` (Following, no end-of-month).

    Derived from QuantLib (BSD-3-Clause); see NOTICE.md.
    """
    # ported from pureql/instruments/bond.py (ql/bond.cpp:162-173), QuantLib v1.43, BSD-3-Clause
    v = vdate()
    return int(dates.advance(cal, v, nsd, TU_DAYS, BDC_FOLLOWING, 0))


def settle(b):
    """``Bond.settlementDate(v)``: T+n on the bond's calendar, and never before the issue date.

    Derived from QuantLib (BSD-3-Clause); see NOTICE.md.
    """
    # ported from pureql/instruments/bond.py (ql/bond.cpp:162-173), QuantLib v1.43, BSD-3-Clause
    cal = int(legs.bk_cal_arr()[b])
    nsd = int(legs.bk_settle_days_arr()[b])
    # usually, the settlement is at T+n...
    settlement = settle_cal(cal, nsd)
    # ...but the bond won't be traded until the issue date (if given.)
    issue = int(legs.bk_issue_arr()[b])
    if issue == NULL_DATE:
        return settlement
    else:
        return max(settlement, issue)


def notional_s(b):
    """``Bond.notional(settle(b))``: the notional in force at settlement, 0.0 after the last redemption.

    ``lower_bound`` over the notional schedule from its second date; on a
    redemption date the bond has already changed notional.

    Derived from QuantLib (BSD-3-Clause); see NOTICE.md.
    """
    # ported from pureql/instruments/bond.py (ql/bond.cpp:113-139), QuantLib v1.43, BSD-3-Clause
    d = settle(b)
    lo = int(legs.ns_lo_arr()[b])
    hi = int(legs.ns_lo_arr()[b + 1])

    if hi == lo:
        # DEV-27: `notionalSchedule_.back()` on an empty vector.
        raise ValueError("empty notional schedule")

    if d > int(legs.ns_date_arr()[hi - 1]):
        # after maturity
        return 0.0

    # After the check above, d is between the schedule
    # boundaries.  We search starting from the second notional
    # date, since the first is null.  After the call to
    # lower_bound, *i is the earliest date which is greater or
    # equal than d.  Its index is greater or equal to 1.
    i = lo + 1
    j = hi
    while i < j:
        mid = (i + j) // 2  # int>=0
        if int(legs.ns_date_arr()[mid]) < d:
            i = mid + 1
        else:
            j = mid

    if d < int(legs.ns_date_arr()[i]):
        # no doubt about what to return
        return float(legs.ns_notional_arr()[i - 1])
    else:
        # d is equal to a redemption date.
        # As per bond conventions, the payment has occurred;
        # the bond already changed notional.
        return float(legs.ns_notional_arr()[i])


def is_tradable(b):
    """``BondFunctions.isTradable(bond, settle(b))``: ``notional_s(b) != 0.0`` (exact).

    Derived from QuantLib (BSD-3-Clause); see NOTICE.md.
    """
    # ported from pureql/pricingengines/bond/bondfunctions.py (ql/bondfunctions.cpp:39-45), QuantLib v1.43, BSD-3-Clause
    ns = notional_s(b)
    return ns != 0.0


def ref_date(b, role):
    """The reference (settlement and NPV) date of occurrence role ``role``: ``settle(b)`` for SETTLE, else ``vdate()``."""
    if role == ROLE_SETTLE:
        return settle(b)
    elif role == ROLE_ENGINE or role == ROLE_EXPIRY:
        return vdate()
    else:
        raise ValueError("unknown occurrence role " + str(role))


def first_live(b, role):
    """The first flow ``p`` of bond ``b`` that has not occurred for role ``role`` (the end of the bond's range if none).

    ``not lib.has_occurred(cf_date[p], ref, inc, vdate(), todays(),
    ref_events())`` with ``ref = ref_date(b, role)`` and ``inc`` =
    :func:`engine_flag` (ENGINE), 0 (SETTLE) or -1, None (EXPIRY):
    ``CashFlows.nextCashFlow``, which scans the leg forward.

    Found by bisection, which returns the index of the linear scan: with
    ``ref``, the flags and the evaluation date fixed, ``has_occurred(d, ...)``
    is True for ``d < ref``, False for ``d > ref`` and one fixed value for
    ``d == ref`` (``ref`` is never the null date here), so it is
    non-increasing in ``d``; the dates of a bond's leg are non-decreasing
    (``Bond.leg()`` stable-sorts by date; a zero-coupon leg has one flow).
    The occurred flows are therefore a prefix of the leg, and the first
    False of a monotone predicate is what both searches find
    (tests/pv/test_valuation_smoke.py checks it over the flag matrix).

    Derived from QuantLib (BSD-3-Clause); see NOTICE.md.
    """
    # ported from pureql/cashflows/cashflows.py (ql/cashflows.cpp:101-117), QuantLib v1.43, BSD-3-Clause
    lo = int(legs.cf_lo_arr()[b])
    hi = int(legs.cf_lo_arr()[b + 1])
    ref = ref_date(b, role)
    if role == ROLE_ENGINE:
        inc = engine_flag()
    elif role == ROLE_SETTLE:
        inc = 0
    else:
        inc = -1
    v = vdate()
    tod = todays()
    rev = ref_events()
    while lo < hi:
        mid = (lo + hi) // 2  # int>=0
        if lib.has_occurred(int(legs.cf_date_arr()[mid]), ref, inc, v, tod, rev):
            lo = mid + 1
        else:
            hi = mid
    return lo


def is_expired(b):
    """``Bond.isExpired()``: every flow has occurred at ``vdate()`` (include flag None).

    Derived from QuantLib (BSD-3-Clause); see NOTICE.md.
    """
    # ported from pureql/instruments/bond.py (ql/bond.cpp:104-111), QuantLib v1.43, BSD-3-Clause
    # ported from pureql/cashflows/cashflows.py (ql/cashflows.cpp:66-81), QuantLib v1.43, BSD-3-Clause
    hi = int(legs.cf_lo_arr()[b + 1])
    fl = first_live(b, ROLE_EXPIRY)
    return fl == hi


def has_spread(b):
    """Whether bond ``b`` has a zero spread (``bk_spread_idx[b] >= 0``); otherwise it is valued on the plain curve."""
    return int(legs.bk_spread_idx_arr()[b]) >= 0


def spread(b):
    """The zero spread of bond ``b`` at (scen_id, t); 0.0 for a bond without a spread."""
    idx = int(legs.bk_spread_idx_arr()[b])
    if idx < 0:
        return 0.0
    row = srow()
    return float(data.sp_arr()[row, t, idx])


def pv_base(b, role):
    """``CashFlows.npv(leg, curve, includeFlag, settlementDate, npvDate)`` on the plain curve.

    Role ENGINE: ``(engine_flag(), vdate(), vdate())``; SETTLE: ``(False,
    settle(b), settle(b))``. Sequential ``+=`` of ``amount * discount`` over
    the flows that have not occurred (from :func:`first_live`), skipping
    those trading ex-coupon, then ``totalNPV / discount(npvDate)``.

    Derived from QuantLib (BSD-3-Clause); see NOTICE.md.
    """
    # ported from pureql/cashflows/cashflows.py (ql/cashflows.cpp:424-447), QuantLib v1.43, BSD-3-Clause
    lo = int(legs.cf_lo_arr()[b])
    hi = int(legs.cf_lo_arr()[b + 1])
    if hi == lo:
        return 0.0
    if not (role == ROLE_ENGINE or role == ROLE_SETTLE):
        raise ValueError("pv_base: role must be ROLE_ENGINE or ROLE_SETTLE")
    v = vdate()
    settlementDate = ref_date(b, role)
    npvDate = settlementDate

    totalNPV = 0.0
    for p in range(first_live(b, role), hi):
        if not lib.trading_ex_coupon(int(legs.cf_ex_date_arr()[p]), settlementDate):
            kd = int(legs.cf_date_arr()[p]) - v
            dp = discount(kd)
            totalNPV += float(legs.cf_amount_arr()[p]) * dp

    kn = npvDate - v
    dn = discount(kn)
    return float(lib.cxx_div(float(totalNPV), float(dn)))  # IEEE-12


def zdisc_npv(b, role):
    """The ZeroSpreaded discount factor of bond ``b`` at the npvDate of role ``role`` (``ref_date(b, role)``).

    Derived from QuantLib (BSD-3-Clause); see NOTICE.md.
    """
    # ported from pureql/cashflows/cashflows.py (ql/cashflows.cpp:424-447), QuantLib v1.43, BSD-3-Clause
    v = vdate()
    npvDate = ref_date(b, role)
    sp = spread(b)
    return zs_discount_kd(npvDate - v, float(sp))


def pv_sprd(b, role):
    """:func:`pv_base` on the ZeroSpreaded curve of the bond's spread: the loop on :func:`zdisc`, over :func:`zdisc_npv`.

    Derived from QuantLib (BSD-3-Clause); see NOTICE.md.
    """
    # ported from pureql/cashflows/cashflows.py (ql/cashflows.cpp:424-447), QuantLib v1.43, BSD-3-Clause
    lo = int(legs.cf_lo_arr()[b])
    hi = int(legs.cf_lo_arr()[b + 1])
    if hi == lo:
        return 0.0
    if not (role == ROLE_ENGINE or role == ROLE_SETTLE):
        raise ValueError("pv_sprd: role must be ROLE_ENGINE or ROLE_SETTLE")
    settlementDate = ref_date(b, role)

    totalNPV = 0.0
    for p in range(first_live(b, role), hi):
        if not lib.trading_ex_coupon(int(legs.cf_ex_date_arr()[p]), settlementDate):
            zp = zdisc(p)
            totalNPV += float(legs.cf_amount_arr()[p]) * zp

    dn = zdisc_npv(b, role)
    return float(lib.cxx_div(float(totalNPV), float(dn)))  # IEEE-12


def npv(b):
    """``Bond.NPV()``: 0.0 if expired, else the DiscountingBondEngine value (spreaded curve if the bond has a spread).

    Derived from QuantLib (BSD-3-Clause); see NOTICE.md.
    """
    # ported from pureql/instrument.py (ql/instrument.hpp:130-139), QuantLib v1.43, BSD-3-Clause
    # ported from pureql/instrument.py (ql/instrument.hpp:141-145), QuantLib v1.43, BSD-3-Clause
    # ported from pureql/pricingengines/bond/discountingbondengine.py (ql/discountingbondengine.cpp:36-67), QuantLib v1.43, BSD-3-Clause
    if is_expired(b):
        return 0.0
    if has_spread(b):
        return pv_sprd(b, ROLE_ENGINE)
    return pv_base(b, ROLE_ENGINE)


def npv_base(b):
    """The engine NPV on the plain curve, also for a bond with a spread (diagnostic); 0.0 if expired.

    Derived from QuantLib (BSD-3-Clause); see NOTICE.md.
    """
    # ported from pureql/instrument.py (ql/instrument.hpp:130-139), QuantLib v1.43, BSD-3-Clause
    # ported from pureql/pricingengines/bond/discountingbondengine.py (ql/discountingbondengine.cpp:36-67), QuantLib v1.43, BSD-3-Clause
    if is_expired(b):
        return 0.0
    return pv_base(b, ROLE_ENGINE)


def settlement_value(b):
    """``Bond.settlementValue()``: 0.0 if expired; the NPV when the engine flag is off and ``vdate() == settle(b)``; else the SETTLE-role value.

    Derived from QuantLib (BSD-3-Clause); see NOTICE.md.
    """
    # ported from pureql/instruments/bond.py (ql/bond.cpp:280-283), QuantLib v1.43, BSD-3-Clause
    # ported from pureql/pricingengines/bond/discountingbondengine.py (ql/discountingbondengine.cpp:36-67), QuantLib v1.43, BSD-3-Clause
    if is_expired(b):
        return 0.0
    # a bond's cashflow on settlement date is never taken into
    # account, so we might have to play it safe and recalculate
    if not engine_flag() and vdate() == settle(b):
        # same parameters as above, we can avoid another call
        return npv(b)
    # no such luck
    if has_spread(b):
        return pv_sprd(b, ROLE_SETTLE)
    return pv_base(b, ROLE_SETTLE)


def accrued_cash(b):
    """``CashFlows.accruedAmount(leg, False, settle(b))``: the accrued interest of every coupon paid on the next payment date.

    Sequential ``+=`` of ``lib.coupon_accrued_amount`` over the coupons paid
    on the date of :func:`first_live` ``(b, ROLE_SETTLE)``.

    Derived from QuantLib (BSD-3-Clause); see NOTICE.md.
    """
    # ported from pureql/cashflows/cashflows.py (ql/cashflows.cpp:376-393), QuantLib v1.43, BSD-3-Clause
    hi = int(legs.cf_lo_arr()[b + 1])
    settlementDate = settle(b)
    cf = first_live(b, ROLE_SETTLE)
    if cf == hi:
        return 0.0

    paymentDate = int(legs.cf_date_arr()[cf])
    result = 0.0
    for p in range(cf, hi):
        if int(legs.cf_date_arr()[p]) != paymentDate:
            break
        if int(legs.cf_kind_arr()[p]) == CF_COUPON:
            ac = float(lib.coupon_accrued_amount(
                float(legs.cf_nominal_arr()[p]), float(legs.cf_rate_arr()[p]),
                int(legs.cf_comp_arr()[p]), int(legs.cf_freq_arr()[p]), int(legs.cf_dc_arr()[p]),
                int(legs.cf_acc_start_arr()[p]), int(legs.cf_acc_end_arr()[p]),
                int(legs.cf_ref_start_arr()[p]), int(legs.cf_ref_end_arr()[p]),
                int(legs.cf_date_arr()[p]), int(legs.cf_ex_date_arr()[p]), settlementDate))
            result += ac
    return result


def accrued_amount(b):
    """``Bond.accruedAmount(settle(b))``, per 100 of notional: 0.0 when the notional is 0.0.

    Derived from QuantLib (BSD-3-Clause); see NOTICE.md.
    """
    # ported from pureql/instruments/bond.py (ql/bond.cpp:256-262), QuantLib v1.43, BSD-3-Clause
    # ported from pureql/pricingengines/bond/bondfunctions.py (ql/bondfunctions.cpp:224-235), QuantLib v1.43, BSD-3-Clause
    currentNotional = notional_s(b)
    if currentNotional == 0.0:
        return 0.0
    if not is_tradable(b):
        return 0.0
    ac = accrued_cash(b)
    ns = notional_s(b)
    return ac * 100.0 / ns


def dirty_price(b):
    """``Bond.dirtyPrice()``: ``settlement_value(b) * 100.0 / notional_s(b)``, 0.0 when the notional is 0.0.

    Derived from QuantLib (BSD-3-Clause); see NOTICE.md.
    """
    # ported from pureql/instruments/bond.py (ql/bond.cpp:179-185), QuantLib v1.43, BSD-3-Clause
    currentNotional = notional_s(b)
    if currentNotional == 0.0:
        return 0.0
    else:
        sv = settlement_value(b)
        return sv * 100.0 / currentNotional


def clean_price(b):
    """``Bond.cleanPrice()``: ``dirty_price(b) - accrued_amount(b)``.

    Derived from QuantLib (BSD-3-Clause); see NOTICE.md.
    """
    # ported from pureql/instruments/bond.py (ql/bond.cpp:175-177), QuantLib v1.43, BSD-3-Clause
    dp = dirty_price(b)
    ac = accrued_amount(b)
    return dp - ac


def market_value(b):
    """The market value of bond ``b``: :func:`npv` (DECISIONS.md D-4)."""
    return npv(b)


def pv_z(b, z):
    """``CashFlows.npv(leg, curve, z, spread_comp, spread_freq, False, s, s)`` with ``s = settle(b)``.

    The plain-curve loop of :func:`pv_base` (role SETTLE) on
    ``ZeroSpreaded(curve, z, spread_comp(), spread_freq())``, discounting
    with :func:`zs_discount_kd`.

    Derived from QuantLib (BSD-3-Clause); see NOTICE.md.
    """
    # ported from pureql/cashflows/cashflows.py (ql/cashflows.cpp:1146-1175), QuantLib v1.43, BSD-3-Clause
    # ported from pureql/cashflows/cashflows.py (ql/cashflows.cpp:424-447), QuantLib v1.43, BSD-3-Clause
    lo = int(legs.cf_lo_arr()[b])
    hi = int(legs.cf_lo_arr()[b + 1])
    if hi == lo:
        return 0.0
    v = vdate()
    settlementDate = settle(b)
    npvDate = settlementDate

    totalNPV = 0.0
    for p in range(first_live(b, ROLE_SETTLE), hi):
        if not lib.trading_ex_coupon(int(legs.cf_ex_date_arr()[p]), settlementDate):
            kd = int(legs.cf_date_arr()[p]) - v
            dz = zs_discount_kd(kd, float(z))
            totalNPV += float(legs.cf_amount_arr()[p]) * dz

    kn = npvDate - v
    dn = zs_discount_kd(kn, float(z))
    return float(lib.cxx_div(float(totalNPV), float(dn)))  # IEEE-12


def dirty_from_z(b, z):
    """``BondFunctions.dirtyPrice(bond, curve, z, spread_comp, spread_freq, settle(b))``: ``pv_z * 100.0 / N``.

    A bond with ``notional_s(b) == 0.0`` (QUIRK Q-04): 0.0 under
    ``NT_ENGINE``; pureql's "non tradable" error under ``NT_RAISE``.

    Derived from QuantLib (BSD-3-Clause); see NOTICE.md.
    """
    # ported from pureql/pricingengines/bond/bondfunctions.py (ql/bondfunctions.cpp:510-528), QuantLib v1.43, BSD-3-Clause
    if not nt_ok(b):
        return 0.0
    pz = pv_z(b, float(z))
    ns = notional_s(b)
    return pz * 100.0 / ns


def clean_from_z(b, z):
    """``BondFunctions.cleanPrice(bond, curve, z, spread_comp, spread_freq, settle(b))``: ``dirty_from_z - accrued_amount``.

    Derived from QuantLib (BSD-3-Clause); see NOTICE.md.
    """
    # ported from pureql/pricingengines/bond/bondfunctions.py (ql/bondfunctions.cpp:488-498), QuantLib v1.43, BSD-3-Clause
    dz = dirty_from_z(b, float(z))
    ac = accrued_amount(b)
    return dz - ac


def nt_ok(b):
    """The tradability guard of the BondFunctions members at ``settle(b)``: True if ``notional_s(b) != 0.0``.

    A non-tradable bond (QUIRK Q-04) gives False under ``NT_ENGINE``; under
    ``NT_RAISE`` it raises pureql's "non tradable at <settlement date>
    (maturity being <maturity>)", the message of every BondFunctions member
    the model transcribes (prices from a z-spread or a yield, the yield, the
    z-spread and the risk measures).

    Derived from QuantLib (BSD-3-Clause); see NOTICE.md.
    """
    # ported from pureql/pricingengines/bond/bondfunctions.py (ql/bondfunctions.cpp:39-45), QuantLib v1.43, BSD-3-Clause
    # ported from pureql/pricingengines/bond/bondfunctions.py (ql/bondfunctions.cpp:322-336), QuantLib v1.43, BSD-3-Clause
    if is_tradable(b):
        return True
    if data.nontradable_policy == NT_RAISE:
        sd = settle(b)
        md = int(legs.bk_maturity_arr()[b])
        raise ValueError(f"non tradable at {lib.long_date(sd)} (maturity being {lib.long_date(md)})")
    return False


def price_in(b):
    """The quoted price of bond ``b`` at (scen_id, t) (``prices.csv``); NaN if there is none."""
    row = srow()
    slot = int(data.px_slot_arr()[row, t])
    if slot < 0:
        return lib.nan_value()
    return float(data.px_val_arr()[slot, b])


def price_type_in(b):
    """The type of the quoted price of bond ``b`` (``PRICE_CLEAN`` / ``PRICE_DIRTY``); -1 if there is none."""
    row = srow()
    slot = int(data.px_slot_arr()[row, t])
    if slot < 0:
        return -1
    return int(data.px_type_arr()[slot, b])


def yield_in(b):
    """The quoted yield of bond ``b`` at (scen_id, t) (``yields.csv``); NaN if there is none."""
    row = srow()
    slot = int(data.yl_slot_arr()[row, t])
    if slot < 0:
        return lib.nan_value()
    return float(data.yl_val_arr()[slot, b])


def ydc(b):
    """The day counter of bond ``b``'s yield (``InterestRate(y, ydc, ycomp, yfreq)``)."""
    return int(legs.bk_ydc_arr()[b])


def ycomp(b):
    """The compounding of bond ``b``'s yield."""
    return int(legs.bk_ycomp_arr()[b])


def yfreq(b):
    """The frequency of bond ``b``'s yield."""
    return int(legs.bk_yfreq_arr()[b])


def ystep(p):
    """The stepwise discount time of the live (SETTLE-role) flow ``p``: ``lib.stepwise_time`` at the owner's yield conventions.

    ``npv_date`` is ``settle(owner)``; ``last_date`` is ``settle(owner)`` for
    the owner's first live flow and ``cf_date[p-1]`` otherwise. That is
    pureql's running ``lastDate``: the occurred flows are a prefix of the leg
    (see :func:`first_live`), so the previous live flow is ``p - 1``, and when
    it is dated on ``npvDate`` itself (a live flow on the settlement date,
    the T-override) a following redemption gets the invented reference
    period of the ``last_date == npv_date`` branch. The day counter is
    ``ydc(owner)``. The value does not depend on the yield, so every
    yield-family Cells shares it. Defined only for live flows.

    Derived from QuantLib (BSD-3-Clause); see NOTICE.md.
    """
    # ported from pureql/cashflows/cashflows.py (ql/cashflows.cpp:813-855), QuantLib v1.43, BSD-3-Clause
    bo = int(legs.cf_owner_arr()[p])
    npvDate = settle(bo)
    if p == first_live(bo, ROLE_SETTLE):
        lastDate = npvDate
    else:
        lastDate = int(legs.cf_date_arr()[p - 1])
    is_coupon = 0
    if int(legs.cf_kind_arr()[p]) == CF_COUPON:
        is_coupon = 1
    return float(lib.stepwise_time(is_coupon, int(legs.cf_date_arr()[p]), int(legs.cf_acc_start_arr()[p]),
                                   int(legs.cf_ref_start_arr()[p]), int(legs.cf_ref_end_arr()[p]),
                                   ydc(bo), npvDate, lastDate))


def npv_yield(b, y):
    """``CashFlows.npv(leg, InterestRate(y, ydc, ycomp, yfreq), False, s, s)`` with ``s = settle(b)``: the STEPWISE npv.

    QUIRK Q-09: a running product of one-step discount factors,
    ``y.discountFactor(ystep(p))``, over the live flows. A flow trading
    ex-coupon is zeroed, not skipped: its step still discounts the later
    flows. The InterestRate's constructor guard (``lib.check_rate``) runs
    first, as building the rate precedes the call. pureql's locals ``npv``,
    ``discount`` and ``b`` are ``npvSum``, ``discountProduct`` and ``bf``
    here (the first two are Cells names, ``b`` is the bond).

    Derived from QuantLib (BSD-3-Clause); see NOTICE.md.
    """
    # ported from pureql/cashflows/cashflows.py (ql/cashflows.cpp:754-760), QuantLib v1.43, BSD-3-Clause
    # ported from pureql/cashflows/cashflows.py (ql/cashflows.cpp:813-855), QuantLib v1.43, BSD-3-Clause
    comp = ycomp(b)
    freq = yfreq(b)
    lib.check_rate(comp, freq)
    lo = int(legs.cf_lo_arr()[b])
    hi = int(legs.cf_lo_arr()[b + 1])
    if hi == lo:
        return 0.0
    settlementDate = settle(b)

    npvSum = 0.0
    discountProduct = 1.0
    for p in range(first_live(b, ROLE_SETTLE), hi):
        amount = float(legs.cf_amount_arr()[p])
        if lib.trading_ex_coupon(int(legs.cf_ex_date_arr()[p]), settlementDate):
            amount = 0.0

        # QUIRK(Q-09): ONE step's factor into a running product - the
        # scheme the durations and the convexity do NOT use.
        st = ystep(p)
        bf = float(lib.discount_factor(float(y), comp, freq, float(st)))
        discountProduct *= bf

        npvSum += amount * discountProduct

    return npvSum


def simple_duration_y(b, y):
    """``CashFlows.duration(leg, InterestRate(y, ...), Simple, False, s, s)``: ``sum(t c B) / sum(c B)``.

    QUIRK Q-09: ``t`` is the ACCUMULATED time ``tt += ystep(p)`` and ``B`` is
    ``y.discountFactor(tt)`` over the whole of it (not the stepwise product
    of :func:`npv_yield`). 0.0 for an empty leg or when ``sum(c B)`` is 0.0.
    pureql's local ``t`` is ``tt`` (``t`` is the Space parameter).

    Derived from QuantLib (BSD-3-Clause); see NOTICE.md.
    """
    # ported from pureql/cashflows/cashflows.py (ql/cashflows.cpp:926-958), QuantLib v1.43, BSD-3-Clause
    # ported from pureql/cashflows/cashflows.py (ql/cashflows.cpp:602-640), QuantLib v1.43, BSD-3-Clause
    comp = ycomp(b)
    freq = yfreq(b)
    lib.check_rate(comp, freq)
    lo = int(legs.cf_lo_arr()[b])
    hi = int(legs.cf_lo_arr()[b + 1])
    if hi == lo:
        return 0.0
    settlementDate = settle(b)

    P = 0.0
    dPdy = 0.0
    tt = 0.0
    for p in range(first_live(b, ROLE_SETTLE), hi):
        c = float(legs.cf_amount_arr()[p])
        if lib.trading_ex_coupon(int(legs.cf_ex_date_arr()[p]), settlementDate):
            c = 0.0

        # QUIRK(Q-09): `t` ACCUMULATES and the factor is over the whole of
        # it - the other scheme, not the running product of `CashFlows.npv`.
        st = ystep(p)
        tt += st
        B = float(lib.discount_factor(float(y), comp, freq, float(tt)))
        P += c * B
        dPdy += tt * c * B

    if P == 0.0:  # no cashflows
        return 0.0
    return dPdy / P


def modified_duration_y(b, y):
    """``CashFlows.duration(leg, InterestRate(y, ...), Modified, False, s, s)``: ``-(dP/dy)/P``, a closed form per compounding.

    QUIRK Q-09: the accumulated-time scheme (see :func:`simple_duration_y`).
    The Compounded arms divide by ``1 + r/N`` through ``lib.cxx_div``
    (IEEE-11: a rate of exactly ``-100%*N``).

    Derived from QuantLib (BSD-3-Clause); see NOTICE.md.
    """
    # ported from pureql/cashflows/cashflows.py (ql/cashflows.cpp:926-958), QuantLib v1.43, BSD-3-Clause
    # ported from pureql/cashflows/cashflows.py (ql/cashflows.cpp:642-707), QuantLib v1.43, BSD-3-Clause
    comp = ycomp(b)
    freq = yfreq(b)
    lib.check_rate(comp, freq)
    lo = int(legs.cf_lo_arr()[b])
    hi = int(legs.cf_lo_arr()[b + 1])
    if hi == lo:
        return 0.0
    settlementDate = settle(b)

    P = 0.0
    tt = 0.0
    dPdy = 0.0
    r = float(y)
    N = freq
    for p in range(first_live(b, ROLE_SETTLE), hi):
        c = float(legs.cf_amount_arr()[p])
        if lib.trading_ex_coupon(int(legs.cf_ex_date_arr()[p]), settlementDate):
            c = 0.0

        # QUIRK(Q-09): the accumulated-time scheme again.
        st = ystep(p)
        tt += st
        B = float(lib.discount_factor(float(y), comp, freq, float(tt)))
        P += c * B
        if comp == COMP_SIMPLE:
            dPdy -= c * B * B * tt
        elif comp == COMP_COMPOUNDED:
            dPdy -= float(lib.cxx_div(float(c * tt * B), float(1 + r / N)))  # IEEE-11
        elif comp == COMP_CONTINUOUS:
            dPdy -= c * B * tt
        elif comp == COMP_SIMPLE_THEN_COMPOUNDED:
            if tt <= 1.0 / N:
                dPdy -= c * B * B * tt
            else:
                dPdy -= float(lib.cxx_div(float(c * tt * B), float(1 + r / N)))  # IEEE-11
        elif comp == COMP_COMPOUNDED_THEN_SIMPLE:
            if tt > 1.0 / N:
                dPdy -= c * B * B * tt
            else:
                dPdy -= float(lib.cxx_div(float(c * tt * B), float(1 + r / N)))  # IEEE-11
        else:
            raise ValueError(f"unknown compounding convention ({int(comp)})")

    if P == 0.0:  # no cashflows
        return 0.0
    return -dPdy / P  # reverse derivative sign


def macaulay_duration_y(b, y):
    """``CashFlows.duration(leg, InterestRate(y, ...), Macaulay, False, s, s)``: ``(1 + y/N)`` times :func:`modified_duration_y`.

    Raises "compounded rate required" for a yield that is not Compounded
    (the bond-level :func:`duration_macaulay` gates that before calling).

    Derived from QuantLib (BSD-3-Clause); see NOTICE.md.
    """
    # ported from pureql/cashflows/cashflows.py (ql/cashflows.cpp:926-958), QuantLib v1.43, BSD-3-Clause
    # ported from pureql/cashflows/cashflows.py (ql/cashflows.cpp:709-722), QuantLib v1.43, BSD-3-Clause
    comp = ycomp(b)
    freq = yfreq(b)
    lib.check_rate(comp, freq)
    lo = int(legs.cf_lo_arr()[b])
    hi = int(legs.cf_lo_arr()[b + 1])
    if hi == lo:
        return 0.0
    if not (comp == COMP_COMPOUNDED):
        raise ValueError("compounded rate required")

    N = freq
    md = modified_duration_y(b, float(y))
    return (1.0 + y / N) * md


def convexity_y(b, y):
    """``CashFlows.convexity(leg, InterestRate(y, ...), False, s, s)``: ``(1/P) d2P/dy2``, a closed form per compounding.

    QUIRK Q-09: the accumulated-time scheme, as in the durations. The
    Compounded arms divide by ``N*(1+r/N)*(1+r/N)`` through ``lib.cxx_div``
    (IEEE-13).

    Derived from QuantLib (BSD-3-Clause); see NOTICE.md.
    """
    # ported from pureql/cashflows/cashflows.py (ql/cashflows.cpp:975-1043), QuantLib v1.43, BSD-3-Clause
    comp = ycomp(b)
    freq = yfreq(b)
    lib.check_rate(comp, freq)
    lo = int(legs.cf_lo_arr()[b])
    hi = int(legs.cf_lo_arr()[b + 1])
    if hi == lo:
        return 0.0
    settlementDate = settle(b)

    P = 0.0
    tt = 0.0
    d2Pdy2 = 0.0
    r = float(y)
    N = freq
    for p in range(first_live(b, ROLE_SETTLE), hi):
        c = float(legs.cf_amount_arr()[p])
        if lib.trading_ex_coupon(int(legs.cf_ex_date_arr()[p]), settlementDate):
            c = 0.0

        # QUIRK(Q-09): the accumulated-time scheme, as in the durations.
        st = ystep(p)
        tt += st
        B = float(lib.discount_factor(float(y), comp, freq, float(tt)))
        P += c * B
        if comp == COMP_SIMPLE:
            d2Pdy2 += c * 2.0 * B * B * B * tt * tt
        elif comp == COMP_COMPOUNDED:
            d2Pdy2 += float(lib.cxx_div(float(c * B * tt * (N * tt + 1)),
                                        float(N * (1 + r / N) * (1 + r / N))))  # IEEE-13
        elif comp == COMP_CONTINUOUS:
            d2Pdy2 += c * B * tt * tt
        elif comp == COMP_SIMPLE_THEN_COMPOUNDED:
            if tt <= 1.0 / N:
                d2Pdy2 += c * 2.0 * B * B * B * tt * tt
            else:
                d2Pdy2 += float(lib.cxx_div(float(c * B * tt * (N * tt + 1)),
                                            float(N * (1 + r / N) * (1 + r / N))))  # IEEE-13
        elif comp == COMP_COMPOUNDED_THEN_SIMPLE:
            if tt > 1.0 / N:
                d2Pdy2 += c * 2.0 * B * B * B * tt * tt
            else:
                d2Pdy2 += float(lib.cxx_div(float(c * B * tt * (N * tt + 1)),
                                            float(N * (1 + r / N) * (1 + r / N))))  # IEEE-13
        else:
            raise ValueError(f"unknown compounding convention ({int(comp)})")

    if P == 0.0:
        # no cashflows
        return 0.0

    return d2Pdy2 / P


def bpv_y(b, y):
    """``CashFlows.basisPointValue(leg, InterestRate(y, ...), False, s, s)``: ``delta*shift + 0.5*gamma*shift^2``, shift 0.0001.

    QUIRK Q-09 in its sharpest form: the STEPWISE :func:`npv_yield` with the
    ACCUMULATED-time :func:`modified_duration_y` and :func:`convexity_y`, in
    upstream's order (``convexity/100.0`` included). pureql's locals ``npv``
    and ``convexity`` are ``npvy`` and ``cvx`` here (Cells names).

    Derived from QuantLib (BSD-3-Clause); see NOTICE.md.
    """
    # ported from pureql/cashflows/cashflows.py (ql/cashflows.cpp:1059-1091), QuantLib v1.43, BSD-3-Clause
    lib.check_rate(ycomp(b), yfreq(b))
    lo = int(legs.cf_lo_arr()[b])
    hi = int(legs.cf_lo_arr()[b + 1])
    if hi == lo:
        return 0.0

    npvy = npv_yield(b, float(y))
    modifiedDuration = modified_duration_y(b, float(y))
    cvx = convexity_y(b, float(y))
    delta = -modifiedDuration * npvy
    gamma = (cvx / 100.0) * npvy

    shift = 0.0001
    delta *= shift
    gamma *= shift * shift

    return delta + 0.5 * gamma


def yvbp_y(b, y):
    """``CashFlows.yieldValueBasisPoint(leg, InterestRate(y, ...), False, s, s)``: ``(1/(-P * D_modified)) * 0.01``.

    IEEE-14: the division is ``lib.cxx_div``; with no live flow both the npv
    and the modified duration are 0.0 and the result is ``-inf``.

    Derived from QuantLib (BSD-3-Clause); see NOTICE.md.
    """
    # ported from pureql/cashflows/cashflows.py (ql/cashflows.cpp:1106-1130), QuantLib v1.43, BSD-3-Clause
    lib.check_rate(ycomp(b), yfreq(b))
    lo = int(legs.cf_lo_arr()[b])
    hi = int(legs.cf_lo_arr()[b + 1])
    if hi == lo:
        return 0.0

    npvy = npv_yield(b, float(y))
    modifiedDuration = modified_duration_y(b, float(y))

    shift = 0.01
    return float(lib.cxx_div(1.0, float(-npvy * modifiedDuration))) * shift  # IEEE-14


def dirty_from_yield(b, y):
    """``BondFunctions.dirtyPrice(bond, y, ydc, ycomp, yfreq, settle(b))``: ``npv_yield * 100.0 / N``.

    A non-tradable bond (QUIRK Q-04): 0.0 under ``NT_ENGINE``; pureql's "non
    tradable" error under ``NT_RAISE`` (:func:`nt_ok`).

    Derived from QuantLib (BSD-3-Clause); see NOTICE.md.
    """
    # ported from pureql/pricingengines/bond/bondfunctions.py (ql/bondfunctions.cpp:338-346), QuantLib v1.43, BSD-3-Clause
    # ported from pureql/pricingengines/bond/bondfunctions.py (ql/bondfunctions.cpp:322-336), QuantLib v1.43, BSD-3-Clause
    lib.check_rate(ycomp(b), yfreq(b))
    if not nt_ok(b):
        return 0.0
    pv = npv_yield(b, float(y))
    ns = notional_s(b)
    return pv * 100.0 / ns


def clean_from_yield(b, y):
    """``BondFunctions.cleanPrice(bond, y, ydc, ycomp, yfreq, settle(b))``: ``dirty_from_yield - accrued_amount``.

    Derived from QuantLib (BSD-3-Clause); see NOTICE.md.
    """
    # ported from pureql/pricingengines/bond/bondfunctions.py (ql/bondfunctions.cpp:312-320), QuantLib v1.43, BSD-3-Clause
    # ported from pureql/pricingengines/bond/bondfunctions.py (ql/bondfunctions.cpp:306-310), QuantLib v1.43, BSD-3-Clause
    dy = dirty_from_yield(b, float(y))
    ac = accrued_amount(b)
    return dy - ac


def y_price(b):
    """The price the yield is solved for: the quoted price (:func:`price_in`), else the engine clean price.

    ``Bond.bondYield(dc, comp, freq)`` prices the bond with its engine and
    solves for its clean price (``Price(cleanPrice(), Clean)``).

    Derived from QuantLib (BSD-3-Clause); see NOTICE.md.
    """
    # ported from pureql/instruments/bond.py (ql/bond.cpp:199-216), QuantLib v1.43, BSD-3-Clause
    px = price_in(b)
    if not math.isnan(px):
        return px
    return clean_price(b)


def y_price_type(b):
    """The type of :func:`y_price`: the quoted price's type, else ``PRICE_CLEAN``.

    Derived from QuantLib (BSD-3-Clause); see NOTICE.md.
    """
    # ported from pureql/instruments/bond.py (ql/bond.cpp:199-216), QuantLib v1.43, BSD-3-Clause
    px = price_in(b)
    if not math.isnan(px):
        return price_type_in(b)
    return PRICE_CLEAN


def y_target(b):
    """The npv the yield solve aims at (``BondFunctions.bondYield``): ``A = price (+ accrued if Clean); A /= 100.0/N``.

    The rescaling is a division BY a division, as upstream writes it. NaN for
    a non-tradable bond under ``NT_ENGINE`` (``BondFunctions`` raises before
    computing the target; :func:`nt_ok`).

    Derived from QuantLib (BSD-3-Clause); see NOTICE.md.
    """
    # ported from pureql/pricingengines/bond/bondfunctions.py (ql/bondfunctions.hpp:167-195), QuantLib v1.43, BSD-3-Clause
    if not nt_ok(b):
        return lib.nan_value()
    amount = y_price(b)

    if y_price_type(b) == PRICE_CLEAN:
        amount += accrued_amount(b)

    ns = notional_s(b)
    amount /= 100.0 / ns
    return amount


def sign_ok(b):
    """``IrrFinder.checkSign``: whether the live, non-ex-coupon flows change sign against ``-y_target(b)``.

    The yield is nonsensical (pureql raises "the given cash flows cannot
    result in the given market price due to their sign") when they do not;
    :func:`ytm` applies the ERR policy to a False.

    Derived from QuantLib (BSD-3-Clause); see NOTICE.md.
    """
    # ported from pureql/cashflows/cashflows.py (ql/cashflows.cpp:771-811), QuantLib v1.43, BSD-3-Clause
    hi = int(legs.cf_lo_arr()[b + 1])
    settlementDate = settle(b)
    target = y_target(b)
    lastSign = int(lib.sign(float(-target)))
    signChanges = 0
    for p in range(first_live(b, ROLE_SETTLE), hi):
        if not lib.trading_ex_coupon(int(legs.cf_ex_date_arr()[p]), settlementDate):
            thisSign = int(lib.sign(float(legs.cf_amount_arr()[p])))
            if lastSign * thisSign < 0:  # sign change
                signChanges += 1

            if thisSign != 0:
                lastSign = thisSign

    return bool(signChanges > 0)


def z_price(b):
    """The price the z-spread is solved for: the quoted price; else, with ``zspread_price_source = 1``, the engine clean price; else NaN."""
    px = price_in(b)
    if not math.isnan(px):
        return px
    if data.zspread_price_source == 1:
        return clean_price(b)
    return lib.nan_value()


def z_price_type(b):
    """The type of :func:`z_price`: the quoted price's type, ``PRICE_CLEAN`` for the engine clean price, else -1."""
    px = price_in(b)
    if not math.isnan(px):
        return price_type_in(b)
    if data.zspread_price_source == 1:
        return PRICE_CLEAN
    return -1


def z_target(b):
    """The npv the z-spread solve aims at (``BondFunctions.zSpread``): ``price + (accrued if Clean else 0)``, then ``/= 100.0/N``.

    NaN when there is no price (:func:`z_price`) and for a non-tradable bond
    under ``NT_ENGINE`` (:func:`nt_ok`).

    Derived from QuantLib (BSD-3-Clause); see NOTICE.md.
    """
    # ported from pureql/pricingengines/bond/bondfunctions.py (ql/bondfunctions.cpp:540-568), QuantLib v1.43, BSD-3-Clause
    if not nt_ok(b):
        return lib.nan_value()
    price = z_price(b)
    ac = 0.0
    if z_price_type(b) == PRICE_CLEAN:
        ac = accrued_amount(b)
    dirtyPrice = price + ac

    ns = notional_s(b)
    dirtyPrice /= 100.0 / ns
    return dirtyPrice


def solve(b, kind):
    """The root of the yield (``kind`` = ``SOLVE_YIELD``) or z-spread (``SOLVE_ZSPREAD``) objective of bond ``b``.

    One formula: ``Solver1D.solve(f, accuracy, guess, step)``'s bracketing
    walk (growth factor 1.6, the flip-flop branch counting one extra
    evaluation), then ``NewtonSafe.solveImpl`` (``data.yield_solver`` 0, the
    ``BondFunctions.bondYield`` default) or ``Brent.solveImpl`` (yield solver
    1, and always for the z-spread, as ``CashFlows.zSpread``), each with its
    final ``f(root)`` call. The objectives are inlined:

    * YIELD: ``IrrFinder``: ``f(x) = npv_yield(b, x) - y_target(b)``, and
      v1.43's derivative ``-modified_duration_y(b, x) * npv_yield(b, x)``;
      accuracy, max evaluations and guess from ``data.yield_*``, step
      ``guess/10``;
    * ZSPREAD: ``f(x) = z_target(b) - pv_z(b, x)``; ``data.zspread_*``, step
      ``ZSPREAD_STEP`` (0.01).

    The solver state is held in double locals and the evaluation counter is
    a double (``maxEvaluations`` is compared as one). No caller sets solver
    bounds, so ``enforceBounds`` is the identity and is left out. A failure
    to bracket the root and running out of evaluations follow the ERR
    policy: pureql's message under ``ERR_RAISE``, NaN under ``ERR_NAN``. A
    non-positive accuracy always raises. Model guard: a NaN target (no price,
    or a non-tradable bond under ``NT_ENGINE``) gives NaN at once;
    :func:`ytm` and :func:`zspread` gate those cases before calling.

    Derived from QuantLib (BSD-3-Clause); see NOTICE.md.
    """
    # ported from pureql/pricingengines/bond/bondfunctions.py (ql/bondfunctions.cpp:373-387), QuantLib v1.43, BSD-3-Clause
    # ported from pureql/cashflows/cashflows.py (ql/cashflows.hpp:276-292), QuantLib v1.43, BSD-3-Clause
    # ported from pureql/cashflows/cashflows.py (ql/cashflows.cpp:1190-1225), QuantLib v1.43, BSD-3-Clause
    # ported from pureql/cashflows/cashflows.py (ql/cashflows.cpp:754-760), QuantLib v1.43, BSD-3-Clause
    # ported from pureql/cashflows/cashflows.py (ql/cashflows.cpp:762-769), QuantLib v1.43, BSD-3-Clause
    # ported from pureql/math/solver1d.py (ql/solver1d.hpp:83-147), QuantLib v1.43, BSD-3-Clause
    # ported from pureql/math/solvers1d/newtonsafe.py (ql/newtonsafe.hpp:42-109), QuantLib v1.43, BSD-3-Clause
    # ported from pureql/math/solvers1d/brent.py (ql/brent.hpp:39-133), QuantLib v1.43, BSD-3-Clause
    # ported from pureql/math/solvers1d/brent.py (ql/brent.hpp:135-137), QuantLib v1.43, BSD-3-Clause
    if kind == SOLVE_YIELD:
        target = y_target(b)
        accuracy = float(data.yield_accuracy)
        maxEvalN = int(data.yield_max_evaluations)
        guess = float(data.yield_guess)
        step = guess / 10.0
        ysolver = int(data.yield_solver)
        if ysolver == 0:
            newton = True
        elif ysolver == 1:
            newton = False
        else:
            raise ValueError("unknown yield solver " + str(ysolver) + " (0 = NewtonSafe, 1 = Brent)")
    elif kind == SOLVE_ZSPREAD:
        target = z_target(b)
        accuracy = float(data.zspread_accuracy)
        maxEvalN = int(data.zspread_max_evaluations)
        guess = float(data.zspread_guess)
        step = float(ZSPREAD_STEP)
        newton = False
    else:
        raise ValueError("unknown solve kind " + str(kind))
    if math.isnan(target):
        return lib.nan_value()
    maxEvaluations = float(maxEvalN)

    # ---- Solver1D.solve(f, accuracy, guess, step): bracket the root
    if not accuracy > 0.0:
        raise ValueError(f"accuracy ({accuracy:g}) must be positive")
    # check whether we really want to use epsilon
    accuracy = max(accuracy, QL_EPSILON)

    growthFactor = 1.6
    flipflop = -1.0

    root = guess
    if kind == SOLVE_YIELD:
        fxMax = npv_yield(b, float(root)) - target
    else:
        fxMax = target - pv_z(b, float(root))

    # monotonically crescent bias, as in optionValue(volatility)
    if lib.close(float(fxMax), 0.0):
        return float(root)
    elif fxMax > 0.0:
        xMin = root - step
        if kind == SOLVE_YIELD:
            fxMin = npv_yield(b, float(xMin)) - target
        else:
            fxMin = target - pv_z(b, float(xMin))
        xMax = root
    else:
        xMin = root
        fxMin = fxMax
        xMax = root + step
        if kind == SOLVE_YIELD:
            fxMax = npv_yield(b, float(xMax)) - target
        else:
            fxMax = target - pv_z(b, float(xMax))

    evaluationNumber = 2.0
    bracketed = False
    while evaluationNumber <= maxEvaluations:
        if fxMin * fxMax <= 0.0:
            if lib.close(float(fxMin), 0.0):
                return float(xMin)
            if lib.close(float(fxMax), 0.0):
                return float(xMax)
            root = (xMax + xMin) / 2.0
            bracketed = True
            break
        if math.fabs(fxMin) < math.fabs(fxMax):
            xMin = xMin + growthFactor * (xMin - xMax)
            if kind == SOLVE_YIELD:
                fxMin = npv_yield(b, float(xMin)) - target
            else:
                fxMin = target - pv_z(b, float(xMin))
        elif math.fabs(fxMin) > math.fabs(fxMax):
            xMax = xMax + growthFactor * (xMax - xMin)
            if kind == SOLVE_YIELD:
                fxMax = npv_yield(b, float(xMax)) - target
            else:
                fxMax = target - pv_z(b, float(xMax))
        elif flipflop == -1.0:
            xMin = xMin + growthFactor * (xMin - xMax)
            if kind == SOLVE_YIELD:
                fxMin = npv_yield(b, float(xMin)) - target
            else:
                fxMin = target - pv_z(b, float(xMin))
            evaluationNumber += 1.0
            flipflop = 1.0
        elif flipflop == 1.0:
            xMax = xMax + growthFactor * (xMax - xMin)
            if kind == SOLVE_YIELD:
                fxMax = npv_yield(b, float(xMax)) - target
            else:
                fxMax = target - pv_z(b, float(xMax))
            flipflop = -1.0
        evaluationNumber += 1.0

    if not bracketed:
        if data.solver_error_policy == ERR_RAISE:
            raise ValueError(f"unable to bracket root in {maxEvalN} function evaluations "
                             f"(last bracket attempt: f[{xMin:g},{xMax:g}] "
                             f"-> [{fxMin:g},{fxMax:g}])")
        return lib.nan_value()

    if newton:
        # ---- NewtonSafe.solveImpl(f, accuracy); f is IrrFinder (YIELD only)
        # Orient the search so that f(xl) < 0
        if fxMin < 0.0:
            xl = xMin
            xh = xMax
        else:
            xh = xMin
            xl = xMax

        # the "stepsize before last"
        dxold = xMax - xMin
        # it was dxold=std::fabs(xMax_-xMin_); in Numerical Recipes
        # here (xMax_-xMin_ > 0) is verified in the constructor

        # and the last step
        dx = dxold

        froot = npv_yield(b, float(root)) - target
        # IrrFinder.derivative (v1.43): -modifiedDuration(y) * npv(y)
        py = npv_yield(b, float(root))
        dfroot = -modified_duration_y(b, float(root)) * py
        evaluationNumber += 1.0

        while evaluationNumber <= maxEvaluations:
            # Bisect if (out of range || not decreasing fast enough)
            if ((root - xh) * dfroot - froot) * ((root - xl) * dfroot - froot) > 0.0 \
                    or math.fabs(2.0 * froot) > math.fabs(dxold * dfroot):
                dxold = dx
                dx = (xh - xl) / 2.0
                root = xl + dx
            else:
                dxold = dx
                dx = float(lib.cxx_div(float(froot), float(dfroot)))  # IEEE site: 0.0/0.0 is nan
                root -= dx
            # Convergence criterion
            if math.fabs(dx) < accuracy:
                npv_yield(b, float(root))  # f(root_): the objective is left at the root
                evaluationNumber += 1.0
                return float(root)
            froot = npv_yield(b, float(root)) - target
            py = npv_yield(b, float(root))
            dfroot = -modified_duration_y(b, float(root)) * py
            evaluationNumber += 1.0
            if froot < 0.0:
                xl = root
            else:
                xh = root
    else:
        # ---- Brent.solveImpl(f, accuracy)
        # we want to start with root_ (which equals the guess) on
        # one side of the bracket and both xMin_ and xMax_ on the
        # other.
        if kind == SOLVE_YIELD:
            froot = npv_yield(b, float(root)) - target
        else:
            froot = target - pv_z(b, float(root))
        evaluationNumber += 1.0
        if froot * fxMin < 0:
            xMax = xMin
            fxMax = fxMin
        else:
            xMin = xMax
            fxMin = fxMax
        d = root - xMax
        e = d

        while evaluationNumber <= maxEvaluations:
            if (froot > 0.0 and fxMax > 0.0) or (froot < 0.0 and fxMax < 0.0):
                # Rename xMin_, root_, xMax_ and adjust bounds
                xMax = xMin
                fxMax = fxMin
                d = root - xMin
                e = d
            if math.fabs(fxMax) < math.fabs(froot):
                xMin = root
                root = xMax
                xMax = xMin
                fxMin = froot
                froot = fxMax
                fxMax = fxMin
            # Convergence check
            xAcc1 = 2.0 * QL_EPSILON * math.fabs(root) + 0.5 * accuracy
            xMid = (xMax - root) / 2.0
            if math.fabs(xMid) <= xAcc1 or lib.close(float(froot), 0.0):
                # f(root_): the objective is left at the root
                if kind == SOLVE_YIELD:
                    npv_yield(b, float(root))
                else:
                    pv_z(b, float(root))
                evaluationNumber += 1.0
                return float(root)
            if math.fabs(e) >= xAcc1 and math.fabs(fxMin) > math.fabs(froot):
                # Attempt inverse quadratic interpolation
                s = froot / fxMin
                if lib.close(float(xMin), float(xMax)):
                    p = 2.0 * xMid * s
                    q = 1.0 - s
                else:
                    q = fxMin / fxMax
                    r = froot / fxMax
                    p = s * (2.0 * xMid * q * (q - r) - (root - xMin) * (r - 1.0))
                    q = (q - 1.0) * (r - 1.0) * (s - 1.0)
                if p > 0.0:
                    q = -q  # Check whether in bounds
                p = math.fabs(p)
                min1 = 3.0 * xMid * q - math.fabs(xAcc1 * q)
                min2 = math.fabs(e * q)
                if 2.0 * p < (min1 if min1 < min2 else min2):
                    e = d  # Accept interpolation
                    d = p / q
                else:
                    d = xMid  # Interpolation failed, use bisection
                    e = d
            else:
                # Bounds decreasing too slowly, use bisection
                d = xMid
                e = d
            xMin = root
            fxMin = froot
            if math.fabs(d) > xAcc1:
                root += d
            else:
                # sign(xAcc1, xMid): |xAcc1| with the sign of xMid
                root += math.fabs(xAcc1) if xMid >= 0.0 else -math.fabs(xAcc1)
            if kind == SOLVE_YIELD:
                froot = npv_yield(b, float(root)) - target
            else:
                froot = target - pv_z(b, float(root))
            evaluationNumber += 1.0

    if data.solver_error_policy == ERR_RAISE:
        raise ValueError(f"maximum number of function evaluations ({maxEvalN}) exceeded")
    return lib.nan_value()


def ytm(b):
    """The yield to maturity of bond ``b`` (``BondFunctions.bondYield``), in its yield conventions, at ``settle(b)``.

    Solved for :func:`y_price` (the quoted price, else the engine clean
    price). In order: the tradability guard (:func:`nt_ok`: NaN under
    ``NT_ENGINE``), the sign check (:func:`sign_ok`; pureql's message under
    ``ERR_RAISE``, NaN under ``ERR_NAN``), then :func:`solve` ``(b,
    SOLVE_YIELD)``. ``Bond.bondYield`` parity needs ``yield_accuracy = 1e-8``.

    Derived from QuantLib (BSD-3-Clause); see NOTICE.md.
    """
    # ported from pureql/pricingengines/bond/bondfunctions.py (ql/bondfunctions.hpp:167-195), QuantLib v1.43, BSD-3-Clause
    # ported from pureql/cashflows/cashflows.py (ql/cashflows.cpp:733-752), QuantLib v1.43, BSD-3-Clause
    if not nt_ok(b):
        return lib.nan_value()
    if not sign_ok(b):
        if data.solver_error_policy == ERR_RAISE:
            raise ValueError("the given cash flows cannot result in the given market price due to their sign")
        return lib.nan_value()
    return solve(b, SOLVE_YIELD)


def zspread(b):
    """The z-spread of bond ``b`` over the (scen_id, t) curve (``BondFunctions.zSpread``), in the spread conventions.

    NaN without a price (:func:`z_price`: a quoted price, or the engine clean
    price when ``data.zspread_price_source`` is 1). Then the tradability
    guard (:func:`nt_ok`) and :func:`solve` ``(b, SOLVE_ZSPREAD)`` (Brent).

    Derived from QuantLib (BSD-3-Clause); see NOTICE.md.
    """
    # ported from pureql/pricingengines/bond/bondfunctions.py (ql/bondfunctions.cpp:540-568), QuantLib v1.43, BSD-3-Clause
    zp = z_price(b)
    if math.isnan(zp):
        return lib.nan_value()
    if not nt_ok(b):
        return lib.nan_value()
    return solve(b, SOLVE_ZSPREAD)


def risk_yield(b):
    """The yield the risk measures are taken at: the quoted yield (:func:`yield_in`) if any, else :func:`ytm`.

    NaN for a non-tradable bond under ``NT_ENGINE`` (raises under ``NT_RAISE``).
    """
    if not nt_ok(b):
        return lib.nan_value()
    yl = yield_in(b)
    if not math.isnan(yl):
        return yl
    return ytm(b)


def duration_simple(b):
    """``BondFunctions.duration(bond, risk_yield, Simple, settle(b))`` (not rescaled); NaN when the yield is NaN.

    Derived from QuantLib (BSD-3-Clause); see NOTICE.md.
    """
    # ported from pureql/pricingengines/bond/bondfunctions.py (ql/bondfunctions.cpp:389-403), QuantLib v1.43, BSD-3-Clause
    if not nt_ok(b):
        return lib.nan_value()
    yy = risk_yield(b)
    if math.isnan(yy):
        return lib.nan_value()
    return simple_duration_y(b, float(yy))


def duration_modified(b):
    """``BondFunctions.duration(bond, risk_yield, Modified, settle(b))`` (not rescaled); NaN when the yield is NaN.

    Derived from QuantLib (BSD-3-Clause); see NOTICE.md.
    """
    # ported from pureql/pricingengines/bond/bondfunctions.py (ql/bondfunctions.cpp:389-403), QuantLib v1.43, BSD-3-Clause
    if not nt_ok(b):
        return lib.nan_value()
    yy = risk_yield(b)
    if math.isnan(yy):
        return lib.nan_value()
    return modified_duration_y(b, float(yy))


def duration_macaulay(b):
    """``BondFunctions.duration(bond, risk_yield, Macaulay, settle(b))`` (not rescaled); NaN when the yield is NaN.

    A yield that is not Compounded is gated here, before the call (pureql
    raises "compounded rate required"): the message under ``ERR_RAISE``,
    NaN under ``ERR_NAN``.

    Derived from QuantLib (BSD-3-Clause); see NOTICE.md.
    """
    # ported from pureql/pricingengines/bond/bondfunctions.py (ql/bondfunctions.cpp:389-403), QuantLib v1.43, BSD-3-Clause
    # ported from pureql/cashflows/cashflows.py (ql/cashflows.cpp:709-722), QuantLib v1.43, BSD-3-Clause
    if not nt_ok(b):
        return lib.nan_value()
    yy = risk_yield(b)
    if math.isnan(yy):
        return lib.nan_value()
    if not (ycomp(b) == COMP_COMPOUNDED):
        if data.solver_error_policy == ERR_RAISE:
            raise ValueError("compounded rate required")
        return lib.nan_value()
    return macaulay_duration_y(b, float(yy))


def convexity(b):
    """``BondFunctions.convexity(bond, risk_yield, settle(b))`` (not rescaled); NaN when the yield is NaN.

    Derived from QuantLib (BSD-3-Clause); see NOTICE.md.
    """
    # ported from pureql/pricingengines/bond/bondfunctions.py (ql/bondfunctions.cpp:416-428), QuantLib v1.43, BSD-3-Clause
    if not nt_ok(b):
        return lib.nan_value()
    yy = risk_yield(b)
    if math.isnan(yy):
        return lib.nan_value()
    return convexity_y(b, float(yy))


def bpv(b):
    """``BondFunctions.basisPointValue(bond, risk_yield, settle(b))`` (not rescaled); NaN when the yield is NaN.

    Derived from QuantLib (BSD-3-Clause); see NOTICE.md.
    """
    # ported from pureql/pricingengines/bond/bondfunctions.py (ql/bondfunctions.cpp:440-452), QuantLib v1.43, BSD-3-Clause
    if not nt_ok(b):
        return lib.nan_value()
    yy = risk_yield(b)
    if math.isnan(yy):
        return lib.nan_value()
    return bpv_y(b, float(yy))


def yvbp(b):
    """``BondFunctions.yieldValueBasisPoint(bond, risk_yield, settle(b))`` (not rescaled); NaN when the yield is NaN.

    Derived from QuantLib (BSD-3-Clause); see NOTICE.md.
    """
    # ported from pureql/pricingengines/bond/bondfunctions.py (ql/bondfunctions.cpp:464-476), QuantLib v1.43, BSD-3-Clause
    if not nt_ok(b):
        return lib.nan_value()
    yy = risk_yield(b)
    if math.isnan(yy):
        return lib.nan_value()
    return yvbp_y(b, float(yy))


def dirty_at_yield_in(b):
    """The dirty price at the quoted yield, :func:`dirty_from_yield` ``(b, yield_in(b))``; NaN without a quoted yield."""
    yl = yield_in(b)
    if math.isnan(yl):
        return lib.nan_value()
    return dirty_from_yield(b, float(yl))


def clean_at_yield_in(b):
    """The clean price at the quoted yield, :func:`clean_from_yield` ``(b, yield_in(b))``; NaN without a quoted yield."""
    yl = yield_in(b)
    if math.isnan(yl):
        return lib.nan_value()
    return clean_from_yield(b, float(yl))


def npv_total():
    """The sum of :func:`npv` over the bonds, sequentially in bond order."""
    total = 0.0
    for b in range(data.n_bonds()):
        x = npv(b)
        total += x
    return total


def mv_total():
    """The sum of :func:`market_value` over the bonds, sequentially in bond order."""
    total = 0.0
    for b in range(data.n_bonds()):
        x = market_value(b)
        total += x
    return total


def sv_total():
    """The sum of :func:`settlement_value` over the bonds, sequentially in bond order."""
    total = 0.0
    for b in range(data.n_bonds()):
        x = settlement_value(b)
        total += x
    return total


def accrued_total():
    """The sum of the accrued interest in currency, :func:`accrued_cash`, over the bonds, sequentially in bond order."""
    total = 0.0
    for b in range(data.n_bonds()):
        x = accrued_cash(b)
        total += x
    return total


def n_expired():
    """The number of expired bonds (:func:`is_expired`)."""
    count = 0
    for b in range(data.n_bonds()):
        if is_expired(b):
            count += 1
    return count


def n_tradable():
    """The number of tradable bonds (:func:`is_tradable`)."""
    count = 0
    for b in range(data.n_bonds()):
        if is_tradable(b):
            count += 1
    return count


def result_frame():
    """The valuation of every bond at (scen_id, t), one row per bond in bond order.

    Columns by ``data.output_level``:

    * 1 (and above): ``bond_key``, ``settlement_date`` (ISO), ``notional``
      (:func:`notional_s`), ``npv``, ``settlement_value``, ``dirty_price``,
      ``clean_price``, ``accrued_amount``, ``market_value``, ``tradable``,
      ``expired``;
    * 2 adds the yield analytics: ``ytm``, ``risk_yield``,
      ``duration_simple``, ``duration_modified``, ``duration_macaulay``,
      ``convexity``, ``bpv``, ``yvbp``;
    * 3 also adds ``zspread``.

    A solver failure raises under ``ERR_RAISE`` (``data.solver_error_policy``)
    and gives NaN under ``ERR_NAN``.
    """
    level = int(data.output_level)
    keys = data.bond_keys()
    base = datetime.date(1899, 12, 30)
    bond_key = []
    settlement_date = []
    notional = []
    npvs = []
    svs = []
    dirty = []
    clean = []
    accrued = []
    mvs = []
    tradable = []
    expired = []
    ytms = []
    rys = []
    dss = []
    dms = []
    dmcs = []
    cvxs = []
    bpvs = []
    yvbps = []
    zss = []
    for b in range(data.n_bonds()):
        bond_key.append(keys[b])
        settlement_date.append((base + datetime.timedelta(days=settle(b))).isoformat())
        notional.append(notional_s(b))
        npvs.append(npv(b))
        svs.append(settlement_value(b))
        dirty.append(dirty_price(b))
        clean.append(clean_price(b))
        accrued.append(accrued_amount(b))
        mvs.append(market_value(b))
        tradable.append(bool(is_tradable(b)))
        expired.append(bool(is_expired(b)))
        if level >= 2:
            ytms.append(ytm(b))
            rys.append(risk_yield(b))
            dss.append(duration_simple(b))
            dms.append(duration_modified(b))
            dmcs.append(duration_macaulay(b))
            cvxs.append(convexity(b))
            bpvs.append(bpv(b))
            yvbps.append(yvbp(b))
        if level >= 3:
            zss.append(zspread(b))
    cols = {
        "bond_key": bond_key,
        "settlement_date": settlement_date,
        "notional": np.array(notional, dtype=np.float64),
        "npv": np.array(npvs, dtype=np.float64),
        "settlement_value": np.array(svs, dtype=np.float64),
        "dirty_price": np.array(dirty, dtype=np.float64),
        "clean_price": np.array(clean, dtype=np.float64),
        "accrued_amount": np.array(accrued, dtype=np.float64),
        "market_value": np.array(mvs, dtype=np.float64),
        "tradable": np.array(tradable, dtype=bool),
        "expired": np.array(expired, dtype=bool),
    }
    if level >= 2:
        cols["ytm"] = np.array(ytms, dtype=np.float64)
        cols["risk_yield"] = np.array(rys, dtype=np.float64)
        cols["duration_simple"] = np.array(dss, dtype=np.float64)
        cols["duration_modified"] = np.array(dms, dtype=np.float64)
        cols["duration_macaulay"] = np.array(dmcs, dtype=np.float64)
        cols["convexity"] = np.array(cvxs, dtype=np.float64)
        cols["bpv"] = np.array(bpvs, dtype=np.float64)
        cols["yvbp"] = np.array(yvbps, dtype=np.float64)
    if level >= 3:
        cols["zspread"] = np.array(zss, dtype=np.float64)
    return pd.DataFrame(cols)


# ---------------------------------------------------------------------------
# References

scen_id = 1

t = 0

data = ("Interface", ("..", "Data"), "auto")

lib = ("Interface", ("..", "Lib"), "auto")

dates = ("Interface", ("..", "Dates"), "auto")

legs = ("Interface", ("..", "Legs"), "auto")

proj = ("Interface", ("..", "Proj"), "auto")
