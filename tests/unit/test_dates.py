"""Unit tests of the Dates Space (docs/model-contract.md section 4.2).

Every Cells is compared with pureql EXACTLY: values with ``==`` and the same
Python type (int / bool / float, never numpy), and errors by their message
text (pureql raises ``Error``, the model ``ValueError`` with the same message).

The sweeps run on PRIVATE model instances: one per module for the fast tests,
and a fresh one per ``@pytest.mark.slow`` test, each closed afterwards.
"""

import itertools
import math
import random

import modelx as mx
import numpy as np
import pytest

from helpers.model import MODEL_DIR
from helpers.pureql_ref import (
    CAL_NULL,
    CAL_TARGET,
    CAL_US_GOVBOND,
    CAL_US_SETTLEMENT,
    DC_30360_BB,
    DC_30360_EU,
    DC_30360_USA,
    DC_ACT360,
    DC_ACT365F,
    pq_bdc,
    pq_calendar,
    pq_date,
    pq_daycounter,
    pq_period,
    ql,
    serial,
)

import pureql.time.calendar as pq_calendar_module  # noqa: E402  (pureql is on sys.path via pureql_ref)
import pureql.time.calendars.unitedstates as pq_us  # noqa: E402
import pureql.time.date as pq_date_module  # noqa: E402
from pureql.time.schedule import allowsEndOfMonth  # noqa: E402

CALS = (CAL_NULL, CAL_TARGET, CAL_US_SETTLEMENT, CAL_US_GOVBOND)
DCS = (DC_ACT360, DC_ACT365F, DC_30360_USA, DC_30360_BB, DC_30360_EU)
CONVS = tuple(range(7))
TU_DAYS, TU_WEEKS, TU_MONTHS, TU_YEARS = 0, 1, 2, 3
MIN_SERIAL, MAX_SERIAL = 367, 109574
FAST_YEARS = (1901, 1904, 1999, 2000, 2015, 2016, 2024, 2100, 2199)

_names = itertools.count()


def _private_model():
    return mx.read_model(MODEL_DIR, name=f"BondPortfolio_test_dates_{next(_names)}")


@pytest.fixture(scope="module")
def dates():
    """The Dates Space of a private model instance shared by the fast tests of this module."""
    m = _private_model()
    yield m.Dates
    m.close()


@pytest.fixture
def fresh_dates():
    """The Dates Space of a private model instance for one slow sweep, closed afterwards."""
    m = _private_model()
    yield m.Dates
    m.close()


# --------------------------------------------------------------------------- outcome comparison
def model_run(fn, *args):
    """``("ok", value)`` or ``("raise", message)`` of a Cells call (modelx wraps errors)."""
    try:
        return ("ok", fn(*args))
    except Exception as e:  # noqa: BLE001 - FormulaError carries the original error
        err = mx.get_error() if type(e).__name__ == "FormulaError" else e
        if not isinstance(err, ValueError):
            raise
        return ("raise", str(err))


def pq_run(fn, *args):
    """``("ok", value)`` or ``("raise", message)`` of a pureql call."""
    try:
        return ("ok", fn(*args))
    except ql.Error as e:
        return ("raise", str(e))


def _key(outcome):
    """A strict comparison key: the type of an ok value matters, and so does the sign of a zero."""
    tag, v = outcome
    if tag == "raise":
        return outcome
    if isinstance(v, float):
        return (tag, float, v, math.copysign(1.0, v))
    return (tag, type(v), v)


class Mismatches:
    """Collects mismatches of a sweep and fails once, with the first few cases."""

    def __init__(self):
        self.items = []
        self.count = 0

    def check(self, case, got, exp, typ=None):
        """``got`` is a model outcome, ``exp`` a pureql outcome; ``typ`` the required type of an ok value."""
        self.count += 1
        if typ is not None and exp[0] == "ok":
            exp = ("ok", typ(exp[1]))
        if _key(got) != _key(exp):
            self.items.append((case, got, exp))

    def assert_none(self):
        assert self.count > 0
        assert not self.items, f"{len(self.items)} of {self.count} differ, e.g. {self.items[:5]}"


def _serial_of(fn):
    """Wrap a pureql function returning a Date so that it returns its serial."""
    return lambda *a: serial(fn(*a))


def ymd(y, m, d):
    return serial(ql.Date(d, m, y))


def year_serials(y):
    return range(ymd(y, 1, 1), ymd(y, 12, 31) + 1)


def fast_serials():
    s = set()
    for y in FAST_YEARS:
        s.update(year_serials(y))
    s.update(range(MIN_SERIAL, MAX_SERIAL + 1, 37))
    return sorted(s)


def month_end_serials(y0, y1):
    return [serial(ql.Date.endOfMonth(ql.Date(1, m, y))) for y in range(y0, y1 + 1) for m in range(1, 13)]


def sample_dates():
    """Dates with holidays, month ends, mid-month and the two serial bounds."""
    s = set()
    for y, m in [
        (1970, 11), (1975, 10), (1985, 4), (1996, 4), (1998, 12), (1999, 12), (2001, 12), (2004, 6),
        (2012, 10), (2015, 4), (2018, 12), (2020, 2), (2021, 2), (2022, 6), (2023, 12), (2024, 1),
        (2024, 3), (2024, 4), (2024, 5), (2025, 11), (2025, 12), (2026, 1), (2026, 6), (2026, 7), (2027, 4),
    ]:
        first = ymd(y, m, 1)
        s.update(range(first, serial(ql.Date.endOfMonth(ql.Date(first))) + 1))
    s.update(month_end_serials(1990, 2060))
    s.update(ymd(y, m, 15) for y in range(1990, 2061, 3) for m in range(1, 13))
    s.update(range(MIN_SERIAL, MIN_SERIAL + 14))
    s.update(range(MAX_SERIAL - 14, MAX_SERIAL + 1))
    return sorted(s)


# A short list for the Months/Years advance grid: month ends (31st, 30th, Feb 28/29),
# holidays, a mid-month date and the bounds.
ADVANCE_DATES = (
    ymd(2024, 1, 31), ymd(2024, 2, 29), ymd(2023, 2, 28), ymd(2023, 3, 31), ymd(2021, 4, 30),
    ymd(2021, 12, 31), ymd(2022, 12, 25), ymd(2026, 7, 4), ymd(2025, 11, 27), ymd(2025, 4, 18),
    ymd(2027, 1, 1), ymd(2023, 6, 15), ymd(2023, 9, 30), ymd(2024, 8, 31), ymd(2020, 5, 29),
    MIN_SERIAL, MAX_SERIAL,
)


# --------------------------------------------------------------------------- tables and scalar helpers
@pytest.mark.parametrize("cells, table", [
    ("year_is_leap_table", pq_date_module._YearIsLeap),
    ("month_length_table", pq_date_module._MonthLength),
    ("month_leap_length_table", pq_date_module._MonthLeapLength),
    ("month_offset_table", pq_date_module._MonthOffset),
    ("month_leap_offset_table", pq_date_module._MonthLeapOffset),
    ("year_offset_table", pq_date_module._YearOffset),
    ("western_easter_table", pq_calendar_module._WesternEasterMonday),
])
def test_tables(dates, cells, table):
    arr = dates.cells[cells]()
    assert isinstance(arr, np.ndarray) and arr.dtype == np.int64 and arr.ndim == 1
    assert arr.tolist() == [int(v) for v in table]


def test_is_leap_and_year_offset(dates):
    mm = Mismatches()
    for y in range(1890, 2211):
        mm.check(("is_leap", y), model_run(dates.is_leap, y), pq_run(ql.Date.isLeap, y), bool)
        mm.check(("year_offset", y), model_run(dates.year_offset, y), pq_run(ql.Date._yearOffset, y), int)
    mm.assert_none()


def test_month_length_and_offset(dates):
    mm = Mismatches()
    for leap in (0, 1):
        for m in range(1, 13):
            mm.check(("month_length", m, leap), model_run(dates.month_length, m, leap),
                     pq_run(ql.Date._monthLength, m, bool(leap)), int)
        for m in range(1, 14):
            mm.check(("month_offset", m, leap), model_run(dates.month_offset, m, leap),
                     pq_run(ql.Date._monthOffset, m, bool(leap)), int)
    mm.assert_none()


# --------------------------------------------------------------------------- date functions over serials
DATE_FUNCTIONS = (
    ("year", lambda p: p.year(), int),
    ("month", lambda p: int(p.month()), int),
    ("day_of_month", lambda p: p.dayOfMonth(), int),
    ("day_of_year", lambda p: p.dayOfYear(), int),
    ("weekday", lambda p: int(p.weekday()), int),
    ("end_of_month", lambda p: serial(ql.Date.endOfMonth(p)), int),
    ("is_end_of_month", lambda p: ql.Date.isEndOfMonth(p), bool),
)


def check_date_functions(dates, serials):
    mm = Mismatches()
    for d in serials:
        p = pq_date(d)
        for name, pq_fn, typ in DATE_FUNCTIONS:
            mm.check((name, d), model_run(dates.cells[name], d), pq_run(pq_fn, p), typ)
        if d != 0:
            mm.check(("check_serial", d), model_run(dates.check_serial, d), ("ok", True), bool)
            dd, m, y = p.dayOfMonth(), int(p.month()), p.year()
            mm.check(("make_date", d), model_run(dates.make_date, dd, m, y), ("ok", d), int)
    mm.assert_none()


def test_date_functions_fast(dates):
    check_date_functions(dates, fast_serials())


@pytest.mark.slow
def test_date_functions_full(fresh_dates):
    check_date_functions(fresh_dates, range(MIN_SERIAL, MAX_SERIAL + 1))


def test_null_date(dates):
    """year and weekday work on the null date (1899, Saturday); DEV-01 raises for the rest."""
    check_date_functions(dates, [0])
    assert dates.year(0) == 1899 and dates.weekday(0) == 7
    for name in ("month", "day_of_month", "day_of_year", "end_of_month", "is_end_of_month"):
        assert model_run(dates.cells[name], 0)[0] == "raise"
        assert "DEV-01" in model_run(dates.cells[name], 0)[1]


def test_check_serial_bounds(dates):
    mm = Mismatches()
    for d in (-1, 0, 1, 366, 367, 368, 109573, 109574, 109575, 200000):
        exp = pq_run(lambda s: ql.Date._checkSerialNumber(s) is None, d)
        mm.check(("check_serial", d), model_run(dates.check_serial, d), exp, bool)
    mm.assert_none()


def test_make_date_grid(dates):
    mm = Mismatches()
    for y in (1899, 1900, 1901, 1904, 1999, 2000, 2024, 2100, 2199, 2200, 2201):
        for m in range(-1, 15):
            for dd in range(-1, 33):
                mm.check(("make_date", dd, m, y), model_run(dates.make_date, dd, m, y),
                         pq_run(lambda a, b, c: serial(ql.Date(a, b, c)), dd, m, y), int)
    mm.assert_none()


def advance_date_cases():
    ds = {0, MIN_SERIAL, MIN_SERIAL + 1, ymd(1901, 1, 31), ymd(1901, 2, 28), ymd(1901, 12, 31),
          MAX_SERIAL, MAX_SERIAL - 1, ymd(2199, 1, 31), ymd(2199, 2, 28), ymd(2196, 2, 29), ymd(2199, 12, 1)}
    for y in (1904, 2000, 2023, 2024, 2100):
        ds.update(month_end_serials(y, y))
        ds.update((ymd(y, 1, 29), ymd(y, 1, 30), ymd(y, 3, 30), ymd(y, 5, 15)))
    ns = list(range(-25, 26)) + [-110000, -3600, -1200, -299, -298, -120, -100, 100, 120, 298, 299, 1200, 3600, 110000]
    return sorted(ds), ns


def test_advance_date_grid(dates):
    ds, ns = advance_date_cases()
    mm = Mismatches()
    for d in ds:
        for n in ns:
            for unit in range(5):  # 4 = Hours: "undefined time units"
                exp = pq_run(lambda a, b, c: serial(ql.Date._advance(pq_date(a), b, ql.TimeUnit(c))), d, n, unit)
                mm.check(("advance_date", d, n, unit), model_run(dates.advance_date, d, n, unit), exp, int)
    mm.assert_none()


# --------------------------------------------------------------------------- calendars
def test_easter_monday(dates):
    mm = Mismatches()
    for y in range(1899, 2202):
        mm.check(("easter_monday", y), model_run(dates.easter_monday, y),
                 pq_run(pq_calendar_module.WesternImpl.easterMonday, y), int)
    mm.assert_none()


def test_is_weekend_western(dates):
    target = pq_calendar(CAL_TARGET)
    for w in range(1, 8):
        got = dates.is_weekend_western(w)
        assert type(got) is bool and got == target.isWeekend(ql.Weekday(w))


US_HELPERS = (
    ("us_washington_birthday", pq_us._isWashingtonBirthday),
    ("us_memorial_day", pq_us._isMemorialDay),
    ("us_labor_day", pq_us._isLaborDay),
    ("us_columbus_day", pq_us._isColumbusDay),
    ("us_veterans_day", pq_us._isVeteransDay),
    ("us_veterans_day_no_saturday", pq_us._isVeteransDayNoSaturday),
)


def test_us_holiday_helpers(dates):
    mm = Mismatches()
    for y in (1969, 1970, 1971, 1977, 1978, 2021, 2022, 2023):
        for m in range(1, 13):
            for dd in range(1, 32):
                for w in range(1, 8):
                    args = (dd, m, y, w)
                    for name, fn in US_HELPERS:
                        mm.check((name,) + args, model_run(dates.cells[name], *args), pq_run(fn, *args), bool)
                    for mtf in (0, 1):
                        mm.check(("us_juneteenth",) + args + (mtf,), model_run(dates.us_juneteenth, *args, mtf),
                                 pq_run(lambda *a: bool(pq_us._isJuneteenth(*a)), *args, bool(mtf)), bool)
    mm.assert_none()


def check_business_days(dates, serials):
    mm = Mismatches()
    for cal in CALS:
        pcal = pq_calendar(cal)
        for d in serials:
            mm.check(("is_business_day", cal, d), model_run(dates.is_business_day, cal, d),
                     pq_run(pcal.isBusinessDay, pq_date(d)), bool)
    mm.assert_none()


def test_is_business_day_1990_2060(dates):
    check_business_days(dates, range(ymd(1990, 1, 1), ymd(2060, 12, 31) + 1))


@pytest.mark.slow
def test_is_business_day_full(fresh_dates):
    check_business_days(fresh_dates, range(MIN_SERIAL, MAX_SERIAL + 1))


def test_market_rules_against_impls(dates):
    """target_bd / us_settlement_bd / us_govbond_bd against the Impl rules, on years with special cases."""
    impls = (("target_bd", pq_calendar(CAL_TARGET)), ("us_settlement_bd", pq_calendar(CAL_US_SETTLEMENT)),
             ("us_govbond_bd", pq_calendar(CAL_US_GOVBOND)))
    mm = Mismatches()
    for y in (1901, 1970, 1975, 1983, 1995, 1996, 1998, 1999, 2001, 2004, 2012, 2018, 2021, 2022, 2199):
        for d in year_serials(y):
            for name, pcal in impls:
                mm.check((name, d), model_run(dates.cells[name], d), pq_run(pcal._impl.isBusinessDay, pq_date(d)), bool)
    mm.assert_none()


def test_calendar_errors(dates):
    for name, args in (("is_business_day", (4, ymd(2024, 1, 2))), ("is_business_day", (-1, ymd(2024, 1, 2)))):
        got = model_run(dates.cells[name], *args)
        assert got == ("raise", f"calendar {args[0]} not supported in this model version")
    # the null date: NullCalendar answers True, the others raise DEV-01 through dayOfMonth
    mm = Mismatches()
    for cal in CALS:
        mm.check(("is_business_day", cal, 0), model_run(dates.is_business_day, cal, 0),
                 pq_run(pq_calendar(cal).isBusinessDay, ql.Date()), bool)
    mm.assert_none()


def test_holiday_and_end_of_month(dates):
    mm = Mismatches()
    for cal in CALS:
        pcal = pq_calendar(cal)
        for d in sample_dates():
            p = pq_date(d)
            mm.check(("is_holiday", cal, d), model_run(dates.is_holiday, cal, d), pq_run(pcal.isHoliday, p), bool)
            mm.check(("cal_end_of_month", cal, d), model_run(dates.cal_end_of_month, cal, d),
                     pq_run(_serial_of(pcal.endOfMonth), p), int)
            mm.check(("cal_is_end_of_month", cal, d), model_run(dates.cal_is_end_of_month, cal, d),
                     pq_run(pcal.isEndOfMonth, p), bool)
    mm.assert_none()


def check_adjust(dates, serials):
    mm = Mismatches()
    for cal in CALS:
        pcal = pq_calendar(cal)
        for d in serials:
            p = pq_date(d)
            for c in CONVS:
                mm.check(("adjust", cal, d, c), model_run(dates.adjust, cal, d, c),
                         pq_run(_serial_of(pcal.adjust), p, pq_bdc(c)), int)
    mm.assert_none()


def test_adjust(dates):
    check_adjust(dates, sample_dates())


@pytest.mark.slow
def test_adjust_full(fresh_dates):
    check_adjust(fresh_dates, range(MIN_SERIAL, MAX_SERIAL + 1, 5))


def test_adjust_errors(dates):
    mm = Mismatches()
    for cal in CALS:
        pcal = pq_calendar(cal)
        for c in CONVS:
            mm.check(("adjust", cal, 0, c), model_run(dates.adjust, cal, 0, c),
                     pq_run(_serial_of(pcal.adjust), ql.Date(), pq_bdc(c)), int)
        # pureql compares the convention with ==, so a plain int reaches its "unknown" arm; on
        # NullCalendar the Following/Preceding loops never run, so 1 Jan 2024 is tested everywhere
        for c in (7, -1):
            d = ymd(2024, 1, 1)
            mm.check(("adjust", cal, d, c), model_run(dates.adjust, cal, d, c),
                     pq_run(_serial_of(pcal.adjust), pq_date(d), c), int)
    mm.assert_none()


def check_advance(dates, serials, ns, units, convs, eoms):
    mm = Mismatches()
    for cal in CALS:
        pcal = pq_calendar(cal)
        for d in serials:
            p = pq_date(d)
            for unit in units:
                for n in ns:
                    for c in convs:
                        for eom in eoms:
                            mm.check(("advance", cal, d, n, unit, c, eom),
                                     model_run(dates.advance, cal, d, n, unit, c, eom),
                                     pq_run(_serial_of(pcal.advance), p, n, ql.TimeUnit(unit), pq_bdc(c), bool(eom)),
                                     int)
    mm.assert_none()


def test_advance_days(dates):
    ds = sample_dates()[::4] + [MIN_SERIAL, MIN_SERIAL + 3, MAX_SERIAL - 3, MAX_SERIAL]
    check_advance(dates, ds, range(-10, 11), (TU_DAYS,), (0,), (0,))
    # every convention and both eom flags (the Days arm ignores them)
    check_advance(dates, ADVANCE_DATES, range(-10, 11), (TU_DAYS,), CONVS, (0, 1))


def test_advance_weeks(dates):
    check_advance(dates, sample_dates()[::8], range(-6, 7), (TU_WEEKS,), CONVS, (0,))
    check_advance(dates, ADVANCE_DATES, range(-6, 7), (TU_WEEKS,), CONVS, (0, 1))


def test_advance_months_years(dates):
    ns = [n for n in range(-24, 25) if n != 0]
    check_advance(dates, ADVANCE_DATES, ns, (TU_MONTHS, TU_YEARS), CONVS, (0, 1))


@pytest.mark.slow
def test_advance_months_years_random(fresh_dates):
    rng = random.Random(20261011)
    ds = sorted(rng.sample(range(ymd(1950, 1, 1), ymd(2150, 12, 31)), 150))
    ns = [n for n in range(-24, 25) if n != 0]
    check_advance(fresh_dates, ds, ns, (TU_MONTHS, TU_YEARS), CONVS, (0, 1))


def test_advance_zero_and_null(dates):
    mm = Mismatches()
    for cal in CALS:
        pcal = pq_calendar(cal)
        for unit in range(4):
            for c in CONVS:
                for d in (ymd(2024, 3, 29), ymd(2024, 4, 1), ymd(2025, 12, 31)):
                    mm.check(("advance0", cal, d, unit, c), model_run(dates.advance, cal, d, 0, unit, c, 1),
                             pq_run(_serial_of(pcal.advance), pq_date(d), 0, ql.TimeUnit(unit), pq_bdc(c), True), int)
                mm.check(("advance-null", cal, unit, c), model_run(dates.advance, cal, 0, 1, unit, c, 0),
                         pq_run(_serial_of(pcal.advance), ql.Date(), 1, ql.TimeUnit(unit), pq_bdc(c), False), int)
        # Hours in the Months/Years arm: "undefined time units"
        mm.check(("advance-hours", cal), model_run(dates.advance, cal, ymd(2024, 1, 2), 1, 4, 0, 0),
                 pq_run(_serial_of(pcal.advance), pq_date(ymd(2024, 1, 2)), 1, ql.TimeUnit(4), pq_bdc(0), False), int)
    mm.assert_none()


# --------------------------------------------------------------------------- day counters
def day_count_dates():
    ds = [0]
    for y in (2000, 2023, 2024, 2100):
        for m in (1, 2, 3, 6, 12):
            for dd in (1, 15, 28, 29, 30, 31):
                if dd <= ql.Date._monthLength(m, ql.Date.isLeap(y)):
                    ds.append(ymd(y, m, dd))
    return ds


def check_day_counters(dates, pairs, refs=None):
    pq_dcs = {dc: pq_daycounter(dc) for dc in DCS}
    mm = Mismatches()
    for k, (d1, d2) in enumerate(pairs):
        p1, p2 = pq_date(d1), pq_date(d2)
        r1, r2 = refs[k] if refs is not None else (0, 0)
        for dc in DCS:
            pdc = pq_dcs[dc]
            mm.check(("day_count", dc, d1, d2), model_run(dates.day_count, dc, d1, d2),
                     pq_run(pdc.dayCount, p1, p2), int)
            mm.check(("year_fraction", dc, d1, d2, r1, r2), model_run(dates.year_fraction, dc, d1, d2, r1, r2),
                     pq_run(pdc.yearFraction, p1, p2, pq_date(r1), pq_date(r2)), float)
    mm.assert_none()


def test_day_counters_grid(dates):
    ds = day_count_dates()
    check_day_counters(dates, [(a, b) for a in ds for b in ds])


def test_day_counters_random(dates):
    rng = random.Random(1001)
    pairs = [(rng.randint(MIN_SERIAL, MAX_SERIAL), rng.randint(MIN_SERIAL, MAX_SERIAL)) for _ in range(20000)]
    # half of them close together, where the 30/360 day rules matter most
    pairs[::2] = [(a, min(MAX_SERIAL, max(MIN_SERIAL, a + rng.randint(-400, 400)))) for a, _ in pairs[::2]]
    refs = [(rng.choice((0, a)), rng.choice((0, b))) for a, b in pairs]
    check_day_counters(dates, pairs, refs)


def test_day_counter_errors(dates):
    d1, d2 = ymd(2024, 1, 31), ymd(2024, 7, 31)
    empty = pq_daycounter(0)
    mm = Mismatches()
    mm.check(("day_count", 0), model_run(dates.day_count, 0, d1, d2), pq_run(empty.dayCount, pq_date(d1), pq_date(d2)))
    mm.check(("year_fraction", 0), model_run(dates.year_fraction, 0, d1, d2, 0, 0),
             pq_run(empty.yearFraction, pq_date(d1), pq_date(d2)))
    mm.assert_none()
    for dc in (3, 13, 20, -1):
        assert model_run(dates.day_count, dc, d1, d2) == ("raise", f"day counter {dc} not supported in this model version")
        assert model_run(dates.year_fraction, dc, d1, d2, 0, 0) == \
            ("raise", f"day counter {dc} not supported in this model version")


# --------------------------------------------------------------------------- period helpers
def test_period_frequency(dates):
    mm = Mismatches()
    for unit in range(9):  # 4..8 are the intraday units: "unknown time unit (u)" unless n == 0
        for n in range(-3, 401):
            mm.check(("period_frequency", n, unit), model_run(dates.period_frequency, n, unit),
                     pq_run(lambda a, b: int(pq_period(a, b).frequency()), n, unit), int)
    mm.assert_none()


def test_allows_end_of_month(dates):
    mm = Mismatches()
    for unit in range(9):
        for n in range(-30, 31):
            mm.check(("allows_end_of_month", n, unit), model_run(dates.allows_end_of_month, n, unit),
                     pq_run(lambda a, b: allowsEndOfMonth(pq_period(a, b)), n, unit), bool)
    mm.assert_none()


@pytest.mark.slow
def test_day_counters_random_large(fresh_dates):
    rng = random.Random(4242)
    pairs = [(rng.randint(MIN_SERIAL, MAX_SERIAL), rng.randint(MIN_SERIAL, MAX_SERIAL)) for _ in range(100000)]
    pairs[::2] = [(a, min(MAX_SERIAL, max(MIN_SERIAL, a + rng.randint(-800, 800)))) for a, _ in pairs[::2]]
    check_day_counters(fresh_dates, pairs)
