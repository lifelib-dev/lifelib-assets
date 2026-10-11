# modelx: pseudo-python
# This file is part of a modelx model.
# It can be imported as a Python module, but functions defined herein
# are model formulas and may not be executable as standard Python.

"""Schedule and leg of one bond, ``Bond[b]`` for row ``b`` of bonds.csv.

Transcribes Schedule, FixedRateLeg, FixedRateBond and ZeroCouponBond
construction. Generated once per bond.

Derived from QuantLib (BSD-3-Clause); see NOTICE.md."""

from modelx.serialize.jsonvalues import *

_formula = lambda b: None

_bases = []

_allow_none = None

_spaces = []

# ---------------------------------------------------------------------------
# Cells

def bond_type():
    """Bond type code (``BOND_FIXED`` / ``BOND_ZERO``)."""
    return int(data.b_type_arr()[b])


def face_amount():
    """Face amount."""
    return float(data.b_face_arr()[b])


def settlement_days():
    """Settlement days."""
    return int(data.b_settle_days_arr()[b])


def bond_calendar():
    """Calendar code of the input: the schedule calendar of a FixedRate bond, the calendar of a ZeroCoupon bond."""
    return int(data.b_calendar_arr()[b])


def issue_date():
    """Issue date serial (0 = none)."""
    return int(data.b_issue_arr()[b])


def redemption():
    """Redemption in percent of face (base 100)."""
    return float(data.b_redemption_arr()[b])


def spread_index():
    """Spread index into ``data.spread_ids()`` (-1 = no spread)."""
    return int(data.b_spread_idx_arr()[b])


def effective_date():
    """Schedule effective date serial."""
    return int(data.b_eff_arr()[b])


def termination_date():
    """Schedule termination date serial."""
    return int(data.b_term_arr()[b])


def tenor_n():
    """Length of the schedule tenor."""
    return int(data.b_tenor_n_arr()[b])


def tenor_unit():
    """Unit of the schedule tenor (``TU_*``)."""
    return int(data.b_tenor_unit_arr()[b])


def convention():
    """Schedule business-day convention (``BDC_*``)."""
    return int(data.b_conv_arr()[b])


def termination_convention():
    """Schedule termination-date business-day convention (``BDC_*``)."""
    return int(data.b_term_conv_arr()[b])


def rule():
    """Date-generation rule of the input (``RULE_*``)."""
    return int(data.b_rule_arr()[b])


def end_of_month():
    """Schedule end-of-month flag of the input (0/1)."""
    return int(data.b_eom_arr()[b])


def first_date():
    """Schedule first date serial (0 = none)."""
    return int(data.b_first_arr()[b])


def next_to_last_date():
    """Schedule next-to-last date serial (0 = none)."""
    return int(data.b_ntl_arr()[b])


def accrual_dc():
    """Accrual day-counter code (``DC_*``)."""
    return int(data.b_accrual_dc_arr()[b])


def first_period_dc():
    """First-period day-counter code (0 = none: the accrual day counter)."""
    return int(data.b_first_dc_arr()[b])


def payment_convention():
    """Payment business-day convention (``BDC_*``)."""
    return int(data.b_pay_conv_arr()[b])


def payment_calendar_in():
    """Payment calendar code of the input (-1 = not given: the schedule calendar)."""
    return int(data.b_pay_cal_arr()[b])


def maturity_in():
    """Maturity date serial of the input (ZeroCoupon bonds)."""
    return int(data.b_maturity_arr()[b])


def yield_dc():
    """Yield-quote day-counter code."""
    return int(data.b_ydc_arr()[b])


def yield_comp():
    """Yield-quote compounding (``COMP_*``)."""
    return int(data.b_ycomp_arr()[b])


def yield_freq():
    """Yield-quote frequency (``FREQ_*``)."""
    return int(data.b_yfreq_arr()[b])


def coupon_rates():
    """The coupon-rate vector of the bond: its slice of ``data.cr_rate_arr()`` (empty for ZeroCoupon)."""
    lo = int(data.cr_lo_arr()[b])
    cnt = int(data.cr_cnt_arr()[b])
    rates = []
    for k in range(cnt):
        rates.append(float(data.cr_rate_arr()[lo + k]))
    return tuple(rates)


def calendar():
    """The bond's ``calendar_``: the calendar of settlement and of coupon payments.

    FixedRateBond: the payment calendar if one is given, else the schedule
    calendar (``paymentCalendar == Calendar() ? schedule.calendar() :
    paymentCalendar``). ZeroCouponBond: its calendar.

    Derived from QuantLib (BSD-3-Clause); see NOTICE.md.
    """
    # ported from pureql/instruments/bonds/fixedratebond.py (ql/fixedratebond.cpp:31-69), QuantLib v1.43, BSD-3-Clause
    # ported from pureql/instruments/bonds/zerocouponbond.py (ql/zerocouponbond.cpp:26-39), QuantLib v1.43, BSD-3-Clause
    if bond_type() == BOND_FIXED:
        paymentCalendar = payment_calendar_in()
        return schedule()[5] if paymentCalendar == -1 else paymentCalendar
    return bond_calendar()


def schedule():
    """The coupon schedule: ``Schedule(effectiveDate, terminationDate, tenor, ...)``, rule-based.

    Returns ``(dates, is_regular, has_tenor, tenor_n, tenor_unit, calendar,
    convention, termination_convention, rule, end_of_month)``: ``dates`` is a
    tuple of serials, ``is_regular`` a tuple of bool (one per period), the
    rest are the schedule's stored meta data (the rule and the tenor after a
    zero tenor has forced the Zero rule; ``end_of_month`` 0/1 after
    ``allowsEndOfMonth``).

    Transcribed statement for statement: the checks, the NullCalendar seed
    loop with duplicates skipped against the real calendar, the first and
    next-to-last stubs with their computed regularity, the reversal, the
    convention / termination-convention adjustments, the end-of-month rule
    and both safety checks (DEV-02 guard). v1 has the Backward rule and the
    Zero arm; any other rule raises ``rule not supported in this model
    version``. The placeholder effective date that upstream measures from
    the evaluation date is not available: a null effective date raises
    ``null effective date``.

    A ZeroCoupon bond has no schedule: the empty ``Schedule()`` (no dates,
    Unadjusted, the other meta data -1).

    Derived from QuantLib (BSD-3-Clause); see NOTICE.md.
    """
    # ported from pureql/time/schedule.py (ql/schedule.cpp:76-422), QuantLib v1.43, BSD-3-Clause
    if bond_type() != BOND_FIXED:
        # Schedule() = default (schedule.hpp:66, DEV-24)
        return ((), (), 0, 0, 0, -1, BDC_UNADJUSTED, -1, -1, -1)

    effectiveDate = effective_date()
    terminationDate = termination_date()
    tenor_len = tenor_n()
    tenor_units = tenor_unit()
    cal = bond_calendar()
    conv = convention()
    terminationDateConvention = termination_convention()
    rule_in = rule()
    endOfMonth = end_of_month()
    first = first_date()
    nextToLast = next_to_last_date()

    # the mem-initialiser list of `schedule.cpp:86-90`, in declaration order
    eom = endOfMonth if dates.allows_end_of_month(tenor_len, tenor_units) else 0
    firstDate = NULL_DATE if first == effectiveDate else first
    nextToLastDate = NULL_DATE if nextToLast == terminationDate else nextToLast
    sdates = []
    isRegular = []
    rule_ = rule_in

    # sanity checks
    if terminationDate == NULL_DATE:
        raise ValueError("null termination date")

    # in many cases (e.g. non-expired bonds) the effective date is not
    # really necessary. In these cases a decent placeholder is enough
    # (upstream measures it from the evaluation date, which the model does
    # not have: a null effective date raises)
    if effectiveDate == NULL_DATE:
        raise ValueError("null effective date")

    if not (effectiveDate < terminationDate):
        raise ValueError(
            f"effective date ({lib.long_date(effectiveDate)}) later than or equal to "
            f"termination date ({lib.long_date(terminationDate)})")

    if tenor_len == 0:
        rule_ = RULE_ZERO
    else:
        if not (tenor_len > 0):
            raise ValueError(f"non positive tenor ({tenor_len}{'DWMY'[tenor_units]}) not allowed")

    # v1 scope: the Backward rule and the Zero arm a zero tenor forces
    if not (rule_ == RULE_BACKWARD or rule_ == RULE_ZERO):
        raise ValueError("rule not supported in this model version")
    rule_name = "Backward" if rule_ == RULE_BACKWARD else "Zero"

    if firstDate != NULL_DATE:
        if rule_ == RULE_BACKWARD:
            if not (firstDate > effectiveDate and firstDate <= terminationDate):
                raise ValueError(
                    f"first date ({lib.long_date(firstDate)}) out of effective-termination date range "
                    f"({lib.long_date(effectiveDate)}, {lib.long_date(terminationDate)}]")
            # we should ensure that the above condition is still
            # verified after adjustment
        else:
            raise ValueError(f"first date incompatible with {rule_name} date generation rule")
    if nextToLastDate != NULL_DATE:
        if rule_ == RULE_BACKWARD:
            if not (nextToLastDate >= effectiveDate and nextToLastDate < terminationDate):
                raise ValueError(
                    f"next to last date ({lib.long_date(nextToLastDate)}) out of effective-termination "
                    f"date range [{lib.long_date(effectiveDate)}, {lib.long_date(terminationDate)})")
            # we should ensure that the above condition is still
            # verified after adjustment
        else:
            raise ValueError(f"next to last date incompatible with {rule_name} date generation rule")

    # calendar needed for endOfMonth adjustment: CAL_NULL
    periods = 1
    seed = NULL_DATE
    exitDate = NULL_DATE

    if rule_ == RULE_ZERO:
        tenor_len = 0
        tenor_units = TU_YEARS
        sdates.append(effectiveDate)
        sdates.append(terminationDate)
        isRegular.append(True)

    elif rule_ == RULE_BACKWARD:
        sdates.append(terminationDate)

        seed = terminationDate
        if nextToLastDate != NULL_DATE:
            sdates.append(nextToLastDate)
            temp = dates.advance(CAL_NULL, seed, -periods * tenor_len, tenor_units, conv, eom)
            isRegular.append(temp == nextToLastDate)
            seed = nextToLastDate

        exitDate = effectiveDate
        if firstDate != NULL_DATE:
            exitDate = firstDate

        while True:
            temp = dates.advance(CAL_NULL, seed, -periods * tenor_len, tenor_units, conv, eom)
            if temp < exitDate:
                if firstDate != NULL_DATE and (
                    dates.adjust(cal, sdates[-1], conv) != dates.adjust(cal, firstDate, conv)
                ):
                    sdates.append(firstDate)
                    isRegular.append(
                        dates.advance(CAL_NULL, sdates[len(sdates) - 2], -1 * tenor_len, tenor_units, conv, eom)
                        == firstDate
                    )
                break
            else:
                # skip dates that would result in duplicates
                # after adjustment
                if dates.adjust(cal, sdates[-1], conv) != dates.adjust(cal, temp, conv):
                    sdates.append(temp)
                    isRegular.append(True)
                periods += 1

        if dates.adjust(cal, sdates[-1], conv) != dates.adjust(cal, effectiveDate, conv):
            sdates.append(effectiveDate)
            isRegular.append(
                dates.advance(CAL_NULL, sdates[len(sdates) - 2], -1 * tenor_len, tenor_units, conv, eom)
                == effectiveDate
            )
        sdates.reverse()
        isRegular.reverse()

    # adjustments (no third-Wednesday replacement for Backward or Zero)

    # first date not adjusted for old CDS schedules (not a v1 rule)
    if conv != BDC_UNADJUSTED:
        sdates[0] = dates.adjust(cal, sdates[0], conv)

    # termination date is NOT adjusted as per ISDA
    # specifications, unless otherwise specified in the
    # confirmation of the deal or unless we're creating a CDS
    # schedule (not a v1 rule)
    if terminationDateConvention != BDC_UNADJUSTED:
        sdates[-1] = dates.adjust(cal, sdates[-1], terminationDateConvention)

    if eom and dates.cal_is_end_of_month(cal, seed):
        # adjust to end of month
        for i in range(1, len(sdates) - 1):
            sdates[i] = dates.adjust(cal, dates.end_of_month(sdates[i]), conv)
    else:
        for i in range(1, len(sdates) - 1):
            sdates[i] = dates.adjust(cal, sdates[i], conv)

    # Final safety checks to remove extra next-to-last date, if
    # necessary.  It can happen to be equal or later than the end
    # date due to EOM adjustments (see the Schedule test suite
    # for an example).
    if len(sdates) >= 2 and sdates[len(sdates) - 2] >= sdates[-1]:
        # there might be two dates only, then isRegular_ has size one
        if len(isRegular) >= 2:
            isRegular[len(isRegular) - 2] = sdates[len(sdates) - 2] == sdates[-1]
        sdates[len(sdates) - 2] = sdates[-1]
        sdates.pop()
        isRegular.pop()
    if len(sdates) >= 2 and sdates[1] <= sdates[0]:
        # DEV-02: upstream writes `isRegular_[1]` here with no guard; the
        # guard is the one upstream's own first safety check carries
        if len(isRegular) >= 2:
            isRegular[1] = sdates[1] == sdates[0]
        sdates[1] = sdates[0]
        del sdates[0]
        del isRegular[0]

    if not (len(sdates) > 1):
        raise ValueError(
            f"degenerate single date ({lib.long_date(sdates[0])}) schedule"
            f"\n seed date: {lib.long_date(seed)}"
            f"\n exit date: {lib.long_date(exitDate)}"
            f"\n effective date: {lib.long_date(effectiveDate)}"
            f"\n first date: {lib.long_date(first)}"
            f"\n next to last date: {lib.long_date(nextToLast)}"
            f"\n termination date: {lib.long_date(terminationDate)}"
            f"\n generation rule: {rule_name}"
            f"\n end of month: {int(eom)}"
        )

    return (tuple(sdates), tuple(isRegular), 1, tenor_len, tenor_units, cal, conv,
            terminationDateConvention, rule_, int(eom))


def coupons():
    """The fixed-rate coupons of the bond, in schedule order (empty for ZeroCoupon).

    One record per coupon: ``(pay, acc_start, acc_end, ref_start, ref_end,
    ex_date, nominal, rate, comp, freq, dc)``. ``FixedRateLeg(schedule)
    .build()`` with the builder settings of ``FixedRateBond``: one notional
    (the face amount), the coupon-rate vector as
    ``InterestRate(rate, accrual_dc, Simple, Annual)`` (the vector's last rate
    repeats; ``freq`` is the rate's ``frequency()``, NoFrequency for a Simple
    rate), the first-period day counter, the bond's payment calendar
    (:func:`calendar`), the payment adjustment, no payment lag and no
    ex-coupon period (``ex_date`` 0). The first period's reference start and
    the last period's reference end are the tenor-implied dates when the
    period is irregular; then ``Coupon``'s own defaults (a null reference
    date is the accrual date).

    Derived from QuantLib (BSD-3-Clause); see NOTICE.md.
    """
    # ported from pureql/instruments/bonds/fixedratebond.py (ql/fixedratebond.cpp:31-69), QuantLib v1.43, BSD-3-Clause
    # ported from pureql/cashflows/fixedratecoupon.py (ql/fixedratecoupon.cpp:92-93, fixedratecoupon.hpp:116-126), QuantLib v1.43, BSD-3-Clause
    # ported from pureql/cashflows/fixedratecoupon.py (ql/fixedratecoupon.cpp:120-128), QuantLib v1.43, BSD-3-Clause
    # ported from pureql/cashflows/fixedratecoupon.py (ql/fixedratecoupon.cpp:32-43), QuantLib v1.43, BSD-3-Clause
    # ported from pureql/cashflows/fixedratecoupon.py (ql/fixedratecoupon.cpp:176-275), QuantLib v1.43, BSD-3-Clause
    # ported from pureql/cashflows/coupon.py (ql/coupon.cpp:28-42), QuantLib v1.43, BSD-3-Clause
    # ported from pureql/interestrate.py (ql/interestrate.cpp:33-42), QuantLib v1.43, BSD-3-Clause
    # ported from pureql/interestrate.py (ql/interestrate.hpp:58-60), QuantLib v1.43, BSD-3-Clause
    if bond_type() == BOND_ZERO:
        return ()
    if bond_type() != BOND_FIXED:
        raise ValueError("bond type not supported in this model version")

    sch = schedule()
    sdates = sch[0]
    isRegular = sch[1]
    hasTenor = sch[2]
    sch_tenor_len = sch[3]
    sch_tenor_units = sch[4]
    sch_calendar = sch[5]
    sch_convention = sch[6]
    sch_eom = sch[9]

    # FixedRateBond's builder settings: withNotionals(faceAmount),
    # withCouponRates(coupons, accrualDayCounter) (Simple, Annual),
    # withFirstPeriodDayCounter(firstPeriodDayCounter),
    # withPaymentCalendar(calendar_), withPaymentAdjustment(paymentConvention),
    # no ex-coupon period; the rest are the builder's defaults
    notionals = (face_amount(),)
    rates = coupon_rates()
    rate_dc = accrual_dc()
    rate_comp = COMP_SIMPLE
    rate_freq_in = FREQ_ANNUAL
    # InterestRate(r, dc, comp, freq): the frequency is stored only where it
    # makes sense, and frequency() is NoFrequency otherwise (a Simple rate)
    lib.check_rate(rate_comp, rate_freq_in)
    if (rate_comp == COMP_COMPOUNDED or rate_comp == COMP_SIMPLE_THEN_COMPOUNDED
            or rate_comp == COMP_COMPOUNDED_THEN_SIMPLE):
        rate_freq = rate_freq_in
    else:
        rate_freq = FREQ_NO_FREQUENCY
    firstPeriodDC = first_period_dc()
    lastPeriodDC = 0
    paymentCalendar = calendar()
    paymentAdjustment = payment_convention()
    paymentLag = 0

    if not (len(rates) != 0):
        raise ValueError("no coupon rates given")
    if not (len(notionals) != 0):
        raise ValueError("no notional given")

    # FixedRateCoupon(paymentDate, nominal, rate, dc, start, end, refStart, refEnd, exCouponDate)
    leg = []

    # first period might be short or long
    start = sdates[0]
    end = sdates[1]
    paymentDate = dates.advance(paymentCalendar, end, paymentLag, TU_DAYS, paymentAdjustment, 0)
    exCouponDate = NULL_DATE
    rate = rates[0]
    nominal = notionals[0]

    if hasTenor and len(isRegular) != 0 and not isRegular[1 - 1]:
        ref = dates.advance(sch_calendar, end, -sch_tenor_len, sch_tenor_units, sch_convention, sch_eom)
    else:
        ref = start
    r_dc = rate_dc if firstPeriodDC == 0 else firstPeriodDC
    leg.append((paymentDate, nominal, rate, r_dc, start, end, ref, end, exCouponDate))
    # regular periods
    for i in range(2, len(sdates) - 1):
        start = end
        end = sdates[i]
        paymentDate = dates.advance(paymentCalendar, end, paymentLag, TU_DAYS, paymentAdjustment, 0)
        if (i - 1) < len(rates):
            rate = rates[i - 1]
        else:
            rate = rates[len(rates) - 1]  # `couponRates_.back()`
        if (i - 1) < len(notionals):
            nominal = notionals[i - 1]
        else:
            nominal = notionals[len(notionals) - 1]  # `notionals_.back()`
        leg.append((paymentDate, nominal, rate, rate_dc, start, end, start, end, exCouponDate))
    if len(sdates) > 2:
        # last period might be short or long
        N = len(sdates)
        start = end
        end = sdates[N - 1]
        paymentDate = dates.advance(paymentCalendar, end, paymentLag, TU_DAYS, paymentAdjustment, 0)
        if (N - 2) < len(rates):
            rate = rates[N - 2]
        else:
            rate = rates[len(rates) - 1]
        if (N - 2) < len(notionals):
            nominal = notionals[N - 2]
        else:
            nominal = notionals[len(notionals) - 1]
        r_dc = rate_dc if lastPeriodDC == 0 else lastPeriodDC
        if (len(isRegular) != 0 and isRegular[N - 1 - 1]) or not hasTenor:
            leg.append((paymentDate, nominal, rate, r_dc, start, end, start, end, exCouponDate))
        else:
            ref = dates.advance(sch_calendar, start, sch_tenor_len, sch_tenor_units, sch_convention, sch_eom)
            leg.append((paymentDate, nominal, rate, r_dc, start, end, start, ref, exCouponDate))

    out = []
    for cp in leg:
        paymentDate = cp[0]
        accrualStartDate = cp[4]
        accrualEndDate = cp[5]
        refPeriodStart = cp[6]
        refPeriodEnd = cp[7]
        # Coupon(paymentDate, nominal, accrualStartDate, accrualEndDate,
        #        refPeriodStart, refPeriodEnd, exCouponDate)
        if refPeriodStart == NULL_DATE:
            refPeriodStart = accrualStartDate
        if refPeriodEnd == NULL_DATE:
            refPeriodEnd = accrualEndDate
        out.append((paymentDate, accrualStartDate, accrualEndDate, refPeriodStart, refPeriodEnd,
                    cp[8], cp[1], cp[2], rate_comp, rate_freq, cp[3]))
    return tuple(out)


def coupon_amounts():
    """The amount of each coupon: ``nominal * (compoundFactor(start, end, refStart, refEnd) - 1.0)``.

    Derived from QuantLib (BSD-3-Clause); see NOTICE.md.
    """
    # ported from pureql/cashflows/fixedratecoupon.py (ql/fixedratecoupon.cpp:67-71), QuantLib v1.43, BSD-3-Clause
    out = []
    for cp in coupons():
        out.append(cp[6] * (
            lib.compound_factor_dates(float(cp[7]), cp[8], cp[9], cp[10], cp[1], cp[2], cp[3], cp[4])
            - 1.0
        ))
    return tuple(out)


def accrual_periods():
    """The accrual period of each coupon: ``dayCounter().yearFraction(start, end, refStart, refEnd)``.

    Derived from QuantLib (BSD-3-Clause); see NOTICE.md.
    """
    # ported from pureql/cashflows/coupon.py (ql/coupon.cpp:44-50), QuantLib v1.43, BSD-3-Clause
    out = []
    for cp in coupons():
        out.append(dates.year_fraction(cp[10], cp[1], cp[2], cp[3], cp[4]))
    return tuple(out)


def notional_schedule():
    """``(notionalSchedule_, notionals_)``: the notional in force and the date it runs to.

    FixedRateBond: ``calculateNotionalsFromCashflows`` over the coupons (a
    new notional where ``close`` says the nominal changed; a null first
    date; a final 0.0). ZeroCouponBond: ``setSingleRedemption``, i.e.
    ``((0, redemption date), (face, 0.0))``.

    Derived from QuantLib (BSD-3-Clause); see NOTICE.md.
    """
    # ported from pureql/instruments/bond.py (ql/bond.cpp:363-396), QuantLib v1.43, BSD-3-Clause
    # ported from pureql/instruments/bond.py (ql/bond.cpp:340-354), QuantLib v1.43, BSD-3-Clause
    if bond_type() == BOND_ZERO:
        redemptionFlow = redemption_flows()[0]
        return ((NULL_DATE, redemptionFlow[0]), (face_amount(), 0.0))

    notionalSchedule = []
    notionals = []

    lastPaymentDate = NULL_DATE
    notionalSchedule.append(NULL_DATE)
    for cp in coupons():
        notional = cp[6]
        # we add the notional only if it is the first one...
        if len(notionals) == 0:
            notionals.append(cp[6])
            lastPaymentDate = cp[0]
        elif not lib.close(float(notional), float(notionals[len(notionals) - 1])):
            # ...or if it has changed.
            notionals.append(cp[6])
            # in this case, we also add the last valid date for
            # the previous one...
            notionalSchedule.append(lastPaymentDate)
            # ...and store the candidate for this one.
            lastPaymentDate = cp[0]
        else:
            # otherwise, we just extend the valid range of dates
            # for the current notional.
            lastPaymentDate = cp[0]
    if not (len(notionals) != 0):
        raise ValueError("no coupons provided")
    notionals.append(0.0)
    notionalSchedule.append(lastPaymentDate)
    return (tuple(notionalSchedule), tuple(notionals))


def redemption_flows():
    """The redemption payments: ``(date, kind, amount)`` with kind ``CF_AMORTIZING`` or ``CF_REDEMPTION``.

    FixedRateBond: ``addRedemptionsToCashflows([redemption])``, one payment
    per notional step, ``(R / 100.0) * (notionals[i-1] - notionals[i])`` with
    the 1-indexed redemption vector; the last is the Redemption.
    ZeroCouponBond: one Redemption of ``face * redemption / 100.0`` on
    ``calendar.adjust(maturity, paymentConvention)``.

    Derived from QuantLib (BSD-3-Clause); see NOTICE.md.
    """
    # ported from pureql/instruments/bond.py (ql/bond.cpp:304-329), QuantLib v1.43, BSD-3-Clause
    # ported from pureql/instruments/bonds/zerocouponbond.py (ql/zerocouponbond.cpp:26-39), QuantLib v1.43, BSD-3-Clause
    # ported from pureql/instruments/bond.py (ql/bond.cpp:331-338), QuantLib v1.43, BSD-3-Clause
    # ported from pureql/cashflows/simplecashflow.py (ql/simplecashflow.cpp:27-33, simplecashflow.hpp:37-38), QuantLib v1.43, BSD-3-Clause
    if bond_type() == BOND_ZERO:
        redemptionDate = dates.adjust(calendar(), maturity_in(), payment_convention())
        amount = face_amount() * redemption() / 100.0
        if redemptionDate == NULL_DATE:
            raise ValueError("null date SimpleCashFlow")
        return ((redemptionDate, CF_REDEMPTION, amount),)

    redemptions = (redemption(),)
    ns = notional_schedule()
    notionalSchedule = ns[0]
    notionals = ns[1]
    out = []
    for i in range(1, len(notionalSchedule)):
        if i < len(redemptions):
            R = redemptions[i]
        elif len(redemptions) != 0:
            R = redemptions[len(redemptions) - 1]
        else:
            R = 100.0
        amount = (R / 100.0) * (notionals[i - 1] - notionals[i])
        if i < len(notionalSchedule) - 1:
            kind = CF_AMORTIZING
        else:
            kind = CF_REDEMPTION
        if notionalSchedule[i] == NULL_DATE:
            raise ValueError("null date SimpleCashFlow")
        out.append((notionalSchedule[i], kind, amount))
    return tuple(out)


def leg():
    """The bond's cash flows: ``(date, kind, amount, coupon_index)``, coupons then redemptions, stable-sorted by date.

    ``coupon_index`` indexes :func:`coupons` (-1 for a redemption). The sort
    keeps a redemption after a coupon paid on the same date
    (``std::stable_sort`` of ``addRedemptionsToCashflows``).

    Derived from QuantLib (BSD-3-Clause); see NOTICE.md.
    """
    # ported from pureql/instruments/bond.py (ql/bond.cpp:304-329), QuantLib v1.43, BSD-3-Clause
    flows = []
    amounts = coupon_amounts()
    cps = coupons()
    for i in range(len(cps)):
        flows.append((cps[i][0], CF_COUPON, amounts[i], i))
    for rf in redemption_flows():
        flows.append((rf[0], rf[1], rf[2], -1))
    if bond_type() == BOND_ZERO:
        # setSingleRedemption appends without sorting
        return tuple(flows)
    # stable_sort by date: the position breaks ties
    keyed = []
    for k in range(len(flows)):
        keyed.append((flows[k][0], k))
    keyed.sort()
    out = []
    for item in keyed:
        out.append(flows[item[1]])
    return tuple(out)


def maturity_date():
    """``maturityDate()``: FixedRateBond the schedule's end date; ZeroCouponBond the unadjusted input maturity.

    Derived from QuantLib (BSD-3-Clause); see NOTICE.md.
    """
    # ported from pureql/instruments/bonds/fixedratebond.py (ql/fixedratebond.cpp:31-69), QuantLib v1.43, BSD-3-Clause
    # ported from pureql/instruments/bonds/zerocouponbond.py (ql/zerocouponbond.cpp:26-39), QuantLib v1.43, BSD-3-Clause
    if bond_type() == BOND_ZERO:
        return maturity_in()
    sdates = schedule()[0]
    return sdates[len(sdates) - 1]


def n_flows():
    """The number of flows of :func:`leg`."""
    return len(leg())


def cashflow_table():
    """The leg as a DataFrame for inspection: one row per flow, dates in ISO format.

    Columns: ``flow``, ``kind`` ('coupon' / 'amortizing' / 'redemption'),
    ``date``, ``amount``, ``nominal``, ``rate``, ``accrual_start``,
    ``accrual_end``, ``ref_start``, ``ref_end``, ``accrual_period`` (blank or
    NaN for a redemption).
    """
    kinds = ("coupon", "amortizing", "redemption")
    cps = coupons()
    aps = accrual_periods()
    base = datetime.date(1899, 12, 30)
    rows = []
    flows = leg()
    for k in range(len(flows)):
        f = flows[k]
        row = [k, kinds[f[1]], (base + datetime.timedelta(days=int(f[0]))).isoformat(), f[2]]
        if f[3] >= 0:
            cp = cps[f[3]]
            row.append(cp[6])
            row.append(cp[7])
            for d in (cp[1], cp[2], cp[3], cp[4]):
                row.append((base + datetime.timedelta(days=int(d))).isoformat())
            row.append(aps[f[3]])
        else:
            row.extend([lib.nan_value(), lib.nan_value(), "", "", "", "", lib.nan_value()])
        rows.append(row)
    return pd.DataFrame(rows, columns=["flow", "kind", "date", "amount", "nominal", "rate",
                                       "accrual_start", "accrual_end", "ref_start", "ref_end",
                                       "accrual_period"])


# ---------------------------------------------------------------------------
# References

b = 0

data = ("Interface", ("..", "Data"), "auto")

lib = ("Interface", ("..", "Lib"), "auto")

dates = ("Interface", ("..", "Dates"), "auto")
