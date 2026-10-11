"""pureql as the reference implementation, for TESTS ONLY.

quantlib-migration decision D-11: the model never imports pureql; tests may.
The checkout is found through the ``PUREQL_SRC`` environment variable, which
defaults to ``../quantlib-migration/src`` next to this project.

This module maps the model's integer codes (docs/model-contract.md section 2)
to pureql objects, so that a test can build the same instrument on both sides.
"""

import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
PUREQL_SRC = pathlib.Path(os.environ.get("PUREQL_SRC", ROOT.parent / "quantlib-migration" / "src"))
if str(PUREQL_SRC) not in sys.path:
    sys.path.insert(0, str(PUREQL_SRC))

import pureql as ql  # noqa: E402
from pureql.time.calendars.target import TARGET  # noqa: E402
from pureql.time.calendars.unitedstates import UnitedStates  # noqa: E402
from pureql.time.daycounters.actual360 import Actual360  # noqa: E402
from pureql.time.daycounters.thirty360 import Thirty360  # noqa: E402

# model codes (docs/model-contract.md section 2)
CAL_NULL, CAL_TARGET, CAL_US_SETTLEMENT, CAL_US_GOVBOND = 0, 1, 2, 3
DC_ACT360, DC_ACT365F, DC_30360_USA, DC_30360_BB, DC_30360_EU = 1, 2, 10, 11, 12
BOND_FIXED, BOND_ZERO = 0, 1


def pq_date(serial):
    """pureql Date from an int serial (0 is the null date)."""
    return ql.Date(int(serial)) if serial else ql.Date()


def serial(date):
    """int serial from a pureql Date."""
    return int(date.serialNumber())


def pq_calendar(code):
    if code == CAL_NULL:
        return ql.NullCalendar()
    if code == CAL_TARGET:
        return TARGET()
    if code == CAL_US_SETTLEMENT:
        return UnitedStates(UnitedStates.Settlement)
    if code == CAL_US_GOVBOND:
        return UnitedStates(UnitedStates.GovernmentBond)
    raise ValueError(f"unknown calendar code {code}")


def pq_daycounter(code):
    if code == 0:
        return ql.DayCounter()
    if code == DC_ACT360:
        return Actual360()
    if code == DC_ACT365F:
        return ql.Actual365Fixed()
    if code == DC_30360_USA:
        return Thirty360(Thirty360.USA)
    if code == DC_30360_BB:
        return Thirty360(Thirty360.BondBasis)
    if code == DC_30360_EU:
        return Thirty360(Thirty360.European)
    raise ValueError(f"unknown day counter code {code}")


def pq_bdc(code):
    return ql.BusinessDayConvention(int(code))


def pq_comp(code):
    return ql.Compounding(int(code))


def pq_freq(code):
    return ql.Frequency(int(code))


def pq_time_unit(code):
    return ql.TimeUnit(int(code))


def pq_period(n, unit):
    return ql.Period(int(n), pq_time_unit(unit))


# --------------------------------------------------------------------------- bonds (contract 4.4)
# The pureql instruments of a bond of the model, built from the model's own
# parsed inputs (the Data arrays), so that a test compares like with like: the
# CSV parsing and its defaults are Data's, tested in tests/unit/test_data.py.
from pureql.cashflows.coupon import coupon_cast  # noqa: E402
from pureql.cashflows.simplecashflow import AmortizingPayment, Redemption  # noqa: E402

CF_COUPON, CF_AMORTIZING, CF_REDEMPTION = 0, 1, 2


def bond_inputs(model, b):
    """The parsed inputs of bond ``b`` as plain Python values, read from ``model.Data``."""
    d = model.Data
    lo, cnt = int(d.cr_lo_arr()[b]), int(d.cr_cnt_arr()[b])
    return {
        "type": int(d.b_type_arr()[b]),
        "face": float(d.b_face_arr()[b]),
        "settlement_days": int(d.b_settle_days_arr()[b]),
        "calendar": int(d.b_calendar_arr()[b]),
        "issue": int(d.b_issue_arr()[b]),
        "redemption": float(d.b_redemption_arr()[b]),
        "eff": int(d.b_eff_arr()[b]),
        "term": int(d.b_term_arr()[b]),
        "tenor_n": int(d.b_tenor_n_arr()[b]),
        "tenor_unit": int(d.b_tenor_unit_arr()[b]),
        "conv": int(d.b_conv_arr()[b]),
        "term_conv": int(d.b_term_conv_arr()[b]),
        "rule": int(d.b_rule_arr()[b]),
        "eom": int(d.b_eom_arr()[b]),
        "first": int(d.b_first_arr()[b]),
        "ntl": int(d.b_ntl_arr()[b]),
        "accrual_dc": int(d.b_accrual_dc_arr()[b]),
        "first_dc": int(d.b_first_dc_arr()[b]),
        "pay_conv": int(d.b_pay_conv_arr()[b]),
        "pay_cal": int(d.b_pay_cal_arr()[b]),
        "maturity": int(d.b_maturity_arr()[b]),
        "rates": [float(d.cr_rate_arr()[lo + k]) for k in range(cnt)],
    }


def pq_schedule(model, b, inputs=None):
    """The pureql rule-based ``Schedule`` of FixedRate bond ``b``."""
    x = bond_inputs(model, b) if inputs is None else inputs
    return ql.Schedule(
        pq_date(x["eff"]), pq_date(x["term"]), pq_period(x["tenor_n"], x["tenor_unit"]),
        pq_calendar(x["calendar"]), pq_bdc(x["conv"]), pq_bdc(x["term_conv"]),
        ql.DateGeneration.Rule(x["rule"]), bool(x["eom"]), pq_date(x["first"]), pq_date(x["ntl"]))


def pq_bond(model, b, inputs=None):
    """The pureql ``FixedRateBond`` or ``ZeroCouponBond`` of bond ``b``, as the model would build it.

    FixedRateBond: the coupon-rate vector, the accrual day counter, the
    payment convention, the redemption, the issue date, the payment calendar
    (None when not given), no ex-coupon period, the first-period day counter
    (None when not given).
    """
    x = bond_inputs(model, b) if inputs is None else inputs
    if x["type"] == BOND_ZERO:
        return ql.ZeroCouponBond(
            x["settlement_days"], pq_calendar(x["calendar"]), x["face"], pq_date(x["maturity"]),
            pq_bdc(x["pay_conv"]), x["redemption"], pq_date(x["issue"]))
    return ql.FixedRateBond(
        x["settlement_days"], x["face"], pq_schedule(model, b, x), list(x["rates"]),
        pq_daycounter(x["accrual_dc"]), pq_bdc(x["pay_conv"]), x["redemption"], pq_date(x["issue"]),
        pq_calendar(x["pay_cal"]) if x["pay_cal"] != -1 else None,
        None, None, ql.BusinessDayConvention.Unadjusted, False,
        pq_daycounter(x["first_dc"]) if x["first_dc"] != 0 else None)


def pq_schedule_record(s):
    """``(dates, is_regular)`` of a pureql Schedule as int serials and bools."""
    return (tuple(serial(d) for d in s.dates()),
            tuple(bool(r) for r in s.isRegular()) if s.hasIsRegular() else ())


def pq_coupon_records(bond):
    """The coupons of a pureql bond, as ``Bond.coupons()`` records minus the codes.

    ``(pay, acc_start, acc_end, ref_start, ref_end, ex_date, nominal, rate,
    comp, freq, dc_name)``; the coupons are found with ``coupon_cast`` in the
    bond's cash-flow order.
    """
    out = []
    for cf in bond.cashflows():
        c = coupon_cast(cf)
        if c is None:
            continue
        ir = c.interestRate()
        out.append((serial(c.date()), serial(c.accrualStartDate()), serial(c.accrualEndDate()),
                    serial(c.referencePeriodStart()), serial(c.referencePeriodEnd()),
                    serial(c.exCouponDate()) if c.exCouponDate() != ql.Date() else 0,
                    c.nominal(), c.rate(), int(ir.compounding()), int(ir.frequency()),
                    c.dayCounter().name()))
    return out


def pq_leg_records(bond):
    """Every cash flow of a pureql bond, in order, as plain values.

    ``(date, kind, amount, acc_start, acc_end, ref_start, ref_end, nominal,
    rate, accrual_period)``; for a non-coupon flow the accrual and reference
    dates are 0 and nominal, rate and accrual period are None. ``kind`` is
    ``CF_COUPON`` for a coupon (``coupon_cast``), ``CF_REDEMPTION`` for a
    ``Redemption`` and ``CF_AMORTIZING`` for an ``AmortizingPayment``.
    """
    out = []
    for cf in bond.cashflows():
        c = coupon_cast(cf)
        if c is not None:
            out.append((serial(c.date()), CF_COUPON, c.amount(),
                        serial(c.accrualStartDate()), serial(c.accrualEndDate()),
                        serial(c.referencePeriodStart()), serial(c.referencePeriodEnd()),
                        c.nominal(), c.rate(), c.accrualPeriod()))
        elif isinstance(cf, Redemption):
            out.append((serial(cf.date()), CF_REDEMPTION, cf.amount(), 0, 0, 0, 0, None, None, None))
        elif isinstance(cf, AmortizingPayment):
            out.append((serial(cf.date()), CF_AMORTIZING, cf.amount(), 0, 0, 0, 0, None, None, None))
        else:
            raise TypeError(f"unexpected cash flow {type(cf).__name__}")
    return out


def pq_notional_schedule(bond):
    """``(notionalSchedule_, notionals_)`` of a pureql bond as int serials (0 = null) and floats."""
    return (tuple(serial(d) if d != ql.Date() else 0 for d in bond._notionalSchedule),
            tuple(bond.notionals()))
