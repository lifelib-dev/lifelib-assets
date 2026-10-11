# modelx: pseudo-python
# This file is part of a modelx model.
# It can be imported as a Python module, but functions defined herein
# are model formulas and may not be executable as standard Python.

"""Canonical numerics transcribed from pureql.

IEEE helpers, floating-point comparison, InterestRate compounding,
and the cash-flow occurrence predicates with QuantLib's Settings made
explicit arguments.

Derived from QuantLib (BSD-3-Clause); see NOTICE.md."""

from modelx.serialize.jsonvalues import *

_formula = None

_bases = []

_allow_none = None

_spaces = []

# ---------------------------------------------------------------------------
# Cells

def nan_value():
    """A quiet NaN.

    A Cells rather than a Reference: a NaN Reference would be exported as the
    bare name ``nan``.
    """
    return float("nan")


def inf_value():
    """Positive infinity (a Cells for the same reason as :func:`nan_value`)."""
    return float("inf")


def cxx_exp(x):
    """``std::exp(x)``: ``+inf`` on overflow rather than an ``OverflowError``.

    Underflow already agrees (``math.exp(-800.0)`` is ``0.0``), and so do
    ``exp(nan)``, ``exp(+inf)`` and ``exp(-inf)``.

    Derived from QuantLib (BSD-3-Clause); see NOTICE.md.
    """
    # ported from pureql/_cxx.py (port rider), QuantLib v1.43, BSD-3-Clause
    try:
        return math.exp(x)
    except OverflowError:
        return math.inf


_is_cached = False


def cxx_pow(x, y):
    """``std::pow(x, y)``: the IEEE 754 result where ``math.pow`` raises.

    Overflow gives ``+-inf``; a negative base with a non-integral exponent
    gives ``nan``; a zero base with a negative exponent gives ``+-inf``.

    Derived from QuantLib (BSD-3-Clause); see NOTICE.md.
    """
    # ported from pureql/_cxx.py (port rider), QuantLib v1.43, BSD-3-Clause
    try:
        return math.pow(x, y)
    except OverflowError:
        return -math.inf if is_odd_integer(y) and x < 0.0 else math.inf
    except ValueError:
        if x != 0.0:
            # A negative base with a non-integral exponent.
            return math.nan
        # A zero base with a negative exponent: pow(-0, y) is -inf for an odd
        # integer y, +inf otherwise.
        if is_odd_integer(y) and math.copysign(1.0, x) < 0.0:
            return -math.inf
        return math.inf


_is_cached = False


def cxx_div(x, y):
    """``x / y`` on C++ doubles: ``+-inf`` or ``nan`` where Python raises.

    A finite non-zero numerator over zero is an infinity with the sign of the
    two operands; ``0/0`` and ``nan/0`` are ``nan``.

    Derived from QuantLib (BSD-3-Clause); see NOTICE.md.
    """
    # ported from pureql/_cxx.py (port rider), QuantLib v1.43, BSD-3-Clause
    try:
        return x / y
    except ZeroDivisionError:
        if x == 0.0 or math.isnan(x):
            return math.nan
        return math.copysign(math.inf, x) * math.copysign(1.0, y)


_is_cached = False


def is_odd_integer(y):
    """Whether ``y`` is an odd integral double (what IEEE 754 ``pow`` branches on).

    Derived from QuantLib (BSD-3-Clause); see NOTICE.md.
    """
    # ported from pureql/_cxx.py (port rider), QuantLib v1.43, BSD-3-Clause
    if math.isinf(y) or math.isnan(y) or y != math.floor(y):
        return False
    return abs(int(y)) % 2 == 1  # int>=0: abs() makes the operand non-negative


_is_cached = False


def cxx_lround(x):
    """``std::lround(x)``: round to nearest, ties away from zero.

    The split is ``math.modf``, which is exact and keeps the sign on the
    fractional part. A non-finite ``x`` raises.

    Derived from QuantLib (BSD-3-Clause); see NOTICE.md.
    """
    # ported from pureql/_cxx.py (port rider), QuantLib v1.43, BSD-3-Clause
    frac, integral = math.modf(x)
    nearest = int(integral)
    if frac >= 0.5:
        return nearest + 1
    if frac <= -0.5:
        return nearest - 1
    return nearest


_is_cached = False


def cxx_idiv(a, c):
    """``a / c`` on C++ integers: the quotient truncated towards zero.

    Division by zero raises ``ZeroDivisionError`` (undefined in C++).

    Derived from QuantLib (BSD-3-Clause); see NOTICE.md.
    """
    # ported from pureql/_cxx.py (port rider), QuantLib v1.43, BSD-3-Clause
    q = abs(a) // abs(c)  # int>=0: both operands are made non-negative first
    if (a < 0) != (c < 0):
        return -q
    return q


_is_cached = False


def cxx_irem(a, c):
    """``a % c`` on C++ integers: the remainder, with the sign of the dividend.

    Derived from QuantLib (BSD-3-Clause); see NOTICE.md.
    """
    # ported from pureql/_cxx.py (port rider), QuantLib v1.43, BSD-3-Clause
    r = abs(a) % abs(c)  # int>=0: both operands are made non-negative first
    if a < 0:
        return -r
    return r


_is_cached = False


def close(x, y):
    """``|x-y| <= eps|x|`` AND ``|x-y| <= eps|y|``, with ``eps`` = ``CLOSE_N`` machine epsilons.

    ``x == y`` comes first (it makes ``inf == inf`` close); when either
    argument is exactly zero the test is the absolute ``diff < tol*tol``.

    Derived from QuantLib (BSD-3-Clause); see NOTICE.md.
    """
    # ported from pureql/math/comparison.py (ql/comparison.hpp:41-42, comparison.hpp:59-90), QuantLib v1.43, BSD-3-Clause
    # Deals with +infinity and -infinity representations etc.
    if x == y:
        return True

    diff = math.fabs(x - y)
    tolerance = CLOSE_N * QL_EPSILON

    if x == 0.0 or y == 0.0:
        return diff < (tolerance * tolerance)

    return diff <= tolerance * math.fabs(x) and diff <= tolerance * math.fabs(y)


_is_cached = False


def close_enough(x, y):
    """``|x-y| <= eps|x|`` OR ``|x-y| <= eps|y|``: the looser of the two relations.

    Identical to :func:`close` except for the final operator.

    Derived from QuantLib (BSD-3-Clause); see NOTICE.md.
    """
    # ported from pureql/math/comparison.py (ql/comparison.hpp:53-54, comparison.hpp:92-121), QuantLib v1.43, BSD-3-Clause
    # see close() for a note on duplication

    # Deals with +infinity and -infinity representations etc.
    if x == y:
        return True

    diff = math.fabs(x - y)
    tolerance = CLOSE_N * QL_EPSILON

    if x == 0.0 or y == 0.0:  # x or y = 0.0
        return diff < (tolerance * tolerance)

    return diff <= tolerance * math.fabs(x) or diff <= tolerance * math.fabs(y)


_is_cached = False


def check_rate(comp, freq):
    """The guard of the ``InterestRate(r, dc, comp, freq)`` constructor.

    Compounded, SimpleThenCompounded and CompoundedThenSimple need a
    frequency other than Once and NoFrequency. Raises like pureql, else
    returns True. The rate and the day counter are not checked (the model
    never has a null rate).

    Derived from QuantLib (BSD-3-Clause); see NOTICE.md.
    """
    # ported from pureql/interestrate.py (ql/interestrate.cpp:33-42), QuantLib v1.43, BSD-3-Clause
    if comp == COMP_COMPOUNDED or comp == COMP_SIMPLE_THEN_COMPOUNDED or comp == COMP_COMPOUNDED_THEN_SIMPLE:
        if not (freq != FREQ_ONCE and freq != FREQ_NO_FREQUENCY):
            raise ValueError("frequency not allowed for this interest rate")
    return True


_is_cached = False


def compound_factor(r, comp, freq, tt):
    """``InterestRate(r, dc, comp, freq).compoundFactor(tt)``: the five branches.

    The constructor guard (:func:`check_rate`) runs first, as constructing
    the rate precedes using it in pureql. ``freq`` is read only by the three
    conventions that store it, as ``float(freq)``. The IEEE sites are
    :func:`cxx_pow` and :func:`cxx_exp`.

    Derived from QuantLib (BSD-3-Clause); see NOTICE.md.
    """
    # ported from pureql/interestrate.py (ql/interestrate.cpp:44-68), QuantLib v1.43, BSD-3-Clause
    check_rate(comp, freq)
    if not (tt >= 0.0):
        raise ValueError(f"negative time ({tt:g}) not allowed")
    if comp == COMP_SIMPLE:
        return 1.0 + r * tt
    elif comp == COMP_COMPOUNDED:
        return cxx_pow(1.0 + r / float(freq), float(freq) * tt)
    elif comp == COMP_CONTINUOUS:
        return cxx_exp(r * tt)
    elif comp == COMP_SIMPLE_THEN_COMPOUNDED:
        if tt <= 1.0 / float(freq):
            return 1.0 + r * tt
        else:
            return cxx_pow(1.0 + r / float(freq), float(freq) * tt)
    elif comp == COMP_COMPOUNDED_THEN_SIMPLE:
        if tt > 1.0 / float(freq):
            return 1.0 + r * tt
        else:
            return cxx_pow(1.0 + r / float(freq), float(freq) * tt)
    else:
        raise ValueError("unknown compounding convention")


_is_cached = False


def discount_factor(r, comp, freq, tt):
    """``1.0/compoundFactor(tt)`` through :func:`cxx_div` (``inf`` where the factor is 0).

    Derived from QuantLib (BSD-3-Clause); see NOTICE.md.
    """
    # ported from pureql/interestrate.py (ql/interestrate.hpp:69-71), QuantLib v1.43, BSD-3-Clause
    return cxx_div(1.0, compound_factor(r, comp, freq, tt))


_is_cached = False


def implied_rate(compound, comp, freq, tt):
    """``InterestRate.impliedRate(compound, dc, comp, freq, tt).rate()``.

    The exact ``compound == 1.0`` test comes first; elsewhere ``tt > 0`` is
    required. The IEEE sites are :func:`cxx_pow` and :func:`cxx_div`. The
    result's constructor guard (:func:`check_rate`) runs last, so a ``Once``
    frequency fails with the constructor's message, as in pureql.

    Derived from QuantLib (BSD-3-Clause); see NOTICE.md.
    """
    # ported from pureql/interestrate.py (ql/interestrate.cpp:70-112), QuantLib v1.43, BSD-3-Clause
    if not (compound > 0.0):
        raise ValueError("positive compound factor required")

    if compound == 1.0:
        if not (tt >= 0.0):
            raise ValueError(f"non negative time ({tt:g}) required")
        r = 0.0
    else:
        if not (tt > 0.0):
            raise ValueError(f"positive time ({tt:g}) required")
        if comp == COMP_SIMPLE:
            r = (compound - 1.0) / tt
        elif comp == COMP_COMPOUNDED:
            r = (cxx_pow(compound, cxx_div(1.0, float(freq) * tt)) - 1.0) * float(freq)
        elif comp == COMP_CONTINUOUS:
            r = math.log(compound) / tt
        elif comp == COMP_SIMPLE_THEN_COMPOUNDED:
            if tt <= cxx_div(1.0, float(freq)):
                r = (compound - 1.0) / tt
            else:
                r = (cxx_pow(compound, cxx_div(1.0, float(freq) * tt)) - 1.0) * float(freq)
        elif comp == COMP_COMPOUNDED_THEN_SIMPLE:
            if tt > cxx_div(1.0, float(freq)):
                r = (compound - 1.0) / tt
            else:
                r = (cxx_pow(compound, cxx_div(1.0, float(freq) * tt)) - 1.0) * float(freq)
        else:
            raise ValueError(f"unknown compounding convention ({int(comp)})")
    # return InterestRate(r, resultDC, comp, freq): the constructor guard
    check_rate(comp, freq)
    return r


_is_cached = False


def equivalent_rate(r, comp, freq, tt, comp2, freq2):
    """``InterestRate(r, dc, comp, freq).equivalentRate(comp2, freq2, tt).rate()``.

    Derived from QuantLib (BSD-3-Clause); see NOTICE.md.
    """
    # ported from pureql/interestrate.py (ql/interestrate.hpp:155-159), QuantLib v1.43, BSD-3-Clause
    return implied_rate(compound_factor(r, comp, freq, tt), comp2, freq2, tt)


_is_cached = False


def compound_factor_dates(r, comp, freq, dc, d1, d2, r1, r2):
    """``InterestRate(r, dc, comp, freq).compoundFactor(d1, d2, r1, r2)``.

    The constructor guard first, then the ``d2 >= d1`` check, then
    ``dates.year_fraction(dc, d1, d2, r1, r2)`` (``r1``/``r2`` are the
    reference dates, 0 for the null date) and :func:`compound_factor`.

    Derived from QuantLib (BSD-3-Clause); see NOTICE.md.
    """
    # ported from pureql/interestrate.py (ql/interestrate.hpp:98-107), QuantLib v1.43, BSD-3-Clause
    check_rate(comp, freq)
    if not (d2 >= d1):
        raise ValueError(f"d1 ({long_date(d1)}) later than d2 ({long_date(d2)})")
    tt = dates.year_fraction(dc, d1, d2, r1, r2)
    return compound_factor(r, comp, freq, tt)


_is_cached = False


def implied_rate_dates(compound, dc, comp, freq, d1, d2, r1, r2):
    """``InterestRate.impliedRate(compound, dc, comp, freq, d1, d2, r1, r2).rate()``.

    Derived from QuantLib (BSD-3-Clause); see NOTICE.md.
    """
    # ported from pureql/interestrate.py (ql/interestrate.hpp:129-142), QuantLib v1.43, BSD-3-Clause
    if not (d2 >= d1):
        raise ValueError(f"d1 ({long_date(d1)}) later than d2 ({long_date(d2)})")
    tt = dates.year_fraction(dc, d1, d2, r1, r2)
    return implied_rate(compound, comp, freq, tt)


_is_cached = False


def equivalent_rate_dates(r, comp, freq, dc, d1, d2, r1, r2, comp2, freq2):
    """``InterestRate(r, dc, comp, freq).equivalentRate(dc, comp2, freq2, d1, d2, r1, r2).rate()``.

    The result day counter is the rate's own ``dc``, so ``t1`` (the rate's
    year fraction) and ``t2`` (the result's) are the same number here.

    Derived from QuantLib (BSD-3-Clause); see NOTICE.md.
    """
    # ported from pureql/interestrate.py (ql/interestrate.hpp:165-178), QuantLib v1.43, BSD-3-Clause
    check_rate(comp, freq)
    if not (d2 >= d1):
        raise ValueError(f"d1 ({long_date(d1)}) later than d2 ({long_date(d2)})")
    t1 = dates.year_fraction(dc, d1, d2, r1, r2)
    t2 = dates.year_fraction(dc, d1, d2, r1, r2)
    return implied_rate(compound_factor(r, comp, freq, t1), comp2, freq2, t2)


_is_cached = False


def long_date(d):
    """Date serial ``d`` as text, e.g. ``'January 15th, 2006'``; ``'null date'`` for 0.

    The text ``str(Date)`` gives in pureql, used only in error messages.

    Derived from QuantLib (BSD-3-Clause); see NOTICE.md.
    """
    # ported from pureql/time/date.py (ql/date.hpp:358, date.cpp:912-924,987-989 (io::long_date + its holder's inserter)), QuantLib v1.43, BSD-3-Clause
    if d == NULL_DATE:
        return "null date"
    dt = datetime.date(1899, 12, 30) + datetime.timedelta(int(d))
    dd = dt.day
    if dd == 11 or dd == 12 or dd == 13:
        suffix = "th"
    else:
        last = dd % 10
        if last == 1:
            suffix = "st"
        elif last == 2:
            suffix = "nd"
        elif last == 3:
            suffix = "rd"
        else:
            suffix = "th"
    names = ("January", "February", "March", "April", "May", "June", "July",
             "August", "September", "October", "November", "December")
    return names[dt.month - 1] + " " + str(dd) + suffix + ", " + str(dt.year)


_is_cached = False


def has_occurred(d, ref, include_flag, eval_date, todays, ref_events):
    """Whether a cash flow dated ``d`` has occurred at ``ref``.

    ``CashFlow.hasOccurred(ref, include_flag)`` followed by ``Event.hasOccurred``,
    with QuantLib's Settings as arguments: ``eval_date`` is the evaluation
    date, ``todays`` is ``includeTodaysCashFlows`` and ``ref_events`` is
    ``includeReferenceDateEvents``. ``include_flag`` and ``todays`` are tri-states
    (-1 None, 0 False, 1 True); ``ref_events`` is 0/1; ``ref`` 0 is the null
    date. When ``ref`` is null or equals ``eval_date``, a set ``todays``
    overrides ``include_flag``.

    Derived from QuantLib (BSD-3-Clause); see NOTICE.md.
    """
    # ported from pureql/cashflow.py (ql/cashflow.cpp:27-49), QuantLib v1.43, BSD-3-Clause
    # ported from pureql/event.py (ql/event.cpp:28-39), QuantLib v1.43, BSD-3-Clause
    includeRefDate = include_flag

    # easy and quick handling of most cases
    if ref != NULL_DATE:
        cf = d
        if ref < cf:
            return False
        if cf < ref:
            return True

    if ref == NULL_DATE or ref == eval_date:
        # today's date; we override the bool with the one
        # specified in the settings (if any)
        includeToday = todays
        if includeToday != -1:
            includeRefDate = includeToday

    # Event.hasOccurred(ref, includeRefDate)
    refDate = ref if ref != NULL_DATE else eval_date
    includeRefDateEvent = includeRefDate if includeRefDate != -1 else ref_events
    if includeRefDateEvent:
        return bool(d < refDate)
    else:
        return bool(d <= refDate)


_is_cached = False


def trading_ex_coupon(ex_date, ref):
    """Whether a cash flow with ex-coupon date ``ex_date`` trades ex-coupon at ``ref``.

    ``ref`` is an explicit, non-null date. False when ``ex_date`` is the null
    date (no ex-coupon period).

    Derived from QuantLib (BSD-3-Clause); see NOTICE.md.
    """
    # ported from pureql/cashflow.py (ql/cashflow.cpp:51-61), QuantLib v1.43, BSD-3-Clause
    ecd = ex_date
    if ecd == NULL_DATE:
        return False

    return bool(ecd <= ref)


_is_cached = False


def coupon_accrued_amount(nominal, rate, comp, freq, dc, acc_start, acc_end, ref_start, ref_end, pay, ex_date, d):
    """``FixedRateCoupon.accruedAmount(d)``: the interest accrued at ``d``, negative when ex-coupon.

    The coupon is given by its fields: ``nominal``; the rate as
    ``InterestRate(rate, dc, comp, freq)``; the accrual dates ``acc_start``,
    ``acc_end``; the reference period ``ref_start``, ``ref_end``; the payment
    date ``pay`` and the ex-coupon date ``ex_date`` (0 = none). Three
    branches in upstream's order: out of the coupon's range (0.0), trading
    ex-coupon, and the usual case. The compound factor is recomputed over the
    partial period (:func:`compound_factor_dates`).

    Derived from QuantLib (BSD-3-Clause); see NOTICE.md.
    """
    # ported from pureql/cashflows/fixedratecoupon.py (ql/fixedratecoupon.cpp:73-89), QuantLib v1.43, BSD-3-Clause
    if d <= acc_start or d > pay:
        # out of coupon range
        return 0.0
    elif trading_ex_coupon(ex_date, d):
        return -nominal * (
            compound_factor_dates(rate, comp, freq, dc, d, max(d, acc_end), ref_start, ref_end)
            - 1.0
        )
    else:
        # usual case
        return nominal * (
            compound_factor_dates(rate, comp, freq, dc, acc_start, min(d, acc_end), ref_start, ref_end)
            - 1.0
        )


_is_cached = False


def sign(x):
    """``sign(x)``: 1, 0 or -1 for a positive, zero or negative ``x`` (-1 for NaN).

    A NaN compares false against both tests and answers -1, as in C++;
    ``IrrFinder.checkSign`` may see it.

    Derived from QuantLib (BSD-3-Clause); see NOTICE.md.
    """
    # ported from pureql/cashflows/cashflows.py (ql/cashflows.cpp:556-565), QuantLib v1.43, BSD-3-Clause
    zero = 0.0
    if x == zero:
        return 0
    elif x > zero:
        return 1
    else:
        return -1


_is_cached = False


def stepwise_time(is_coupon, d, acc_start, ref_start, ref_end, dc, npv_date, last_date):
    """``getStepwiseDiscountTime``: the time of ONE discounting step, from ``last_date`` to the flow dated ``d``.

    The flow is a coupon (``is_coupon`` 1, with accrual start ``acc_start``
    and reference period ``ref_start``..``ref_end``) or not (0: a redemption,
    whose reference period is invented). Three branches, in upstream's order:

    * a coupon whose accrual start is not ``last_date``: the difference of
      two year fractions from the accrual start, ``yearFraction(acc_start,
      d) - yearFraction(acc_start, last_date)``;
    * a coupon whose accrual start is ``last_date``: ``yearFraction(last_date, d)``;
    * a non-coupon: ``yearFraction(last_date, d)`` over the reference period
      ``[d - 1Y, d]`` when ``last_date == npv_date`` (no previous flow), else
      ``[last_date, d]``. ``d - 1Y`` is ``dates.advance_date(d, -1, TU_YEARS)``.

    ``dc`` is the yield's day counter; the reference dates reach
    :func:`~.Dates.year_fraction` as its ``r1``/``r2``.

    Derived from QuantLib (BSD-3-Clause); see NOTICE.md.
    """
    # ported from pureql/cashflows/cashflows.py (ql/cashflows.cpp:567-600), QuantLib v1.43, BSD-3-Clause
    cashFlowDate = d
    refStartDate = NULL_DATE
    refEndDate = NULL_DATE
    if is_coupon:
        refStartDate = ref_start
        refEndDate = ref_end
    else:
        if last_date == npv_date:
            # we don't have a previous coupon date,
            # so we fake it
            refStartDate = dates.advance_date(cashFlowDate, -1, TU_YEARS)
        else:
            refStartDate = last_date
        refEndDate = cashFlowDate

    if is_coupon and last_date != acc_start:
        couponPeriod = dates.year_fraction(dc, acc_start, cashFlowDate, refStartDate, refEndDate)
        accruedPeriod = dates.year_fraction(dc, acc_start, last_date, refStartDate, refEndDate)
        return couponPeriod - accruedPeriod
    else:
        return dates.year_fraction(dc, last_date, cashFlowDate, refStartDate, refEndDate)


_is_cached = False


# ---------------------------------------------------------------------------
# References

dates = ("Interface", ("..", "Dates"), "auto")
