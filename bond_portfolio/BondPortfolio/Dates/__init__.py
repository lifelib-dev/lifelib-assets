# modelx: pseudo-python
# This file is part of a modelx model.
# It can be imported as a Python module, but functions defined herein
# are model formulas and may not be executable as standard Python.

"""Date algebra, calendars and day counters on integer serial dates.

Dates are QuantLib serial numbers (1 Jan 1901 = 367, 31 Dec 2199 =
109574, 0 = the null date).

Derived from QuantLib (BSD-3-Clause); see NOTICE.md."""

from modelx.serialize.jsonvalues import *

_formula = None

_bases = []

_allow_none = None

_spaces = []

# ---------------------------------------------------------------------------
# Cells

def year_is_leap_table():
    """The static table of ``Date::isLeap``: 1 if year ``1900 + i`` is leap, for 1900..2200.

    1900 is leap, in agreement with Excel's bug. Read element-wise only.

    Derived from QuantLib (BSD-3-Clause); see NOTICE.md.
    """
    # ported from pureql/time/date.py (ql/date.cpp:187-256), QuantLib v1.43, BSD-3-Clause
    return np.array([
        # 1900 is leap in agreement with Excel's bug
        # 1900 is out of valid date range anyway
        # 1900-1909
        True, False, False, False, True, False, False, False, True, False,
        # 1910-1919
        False, False, True, False, False, False, True, False, False, False,
        # 1920-1929
        True, False, False, False, True, False, False, False, True, False,
        # 1930-1939
        False, False, True, False, False, False, True, False, False, False,
        # 1940-1949
        True, False, False, False, True, False, False, False, True, False,
        # 1950-1959
        False, False, True, False, False, False, True, False, False, False,
        # 1960-1969
        True, False, False, False, True, False, False, False, True, False,
        # 1970-1979
        False, False, True, False, False, False, True, False, False, False,
        # 1980-1989
        True, False, False, False, True, False, False, False, True, False,
        # 1990-1999
        False, False, True, False, False, False, True, False, False, False,
        # 2000-2009
        True, False, False, False, True, False, False, False, True, False,
        # 2010-2019
        False, False, True, False, False, False, True, False, False, False,
        # 2020-2029
        True, False, False, False, True, False, False, False, True, False,
        # 2030-2039
        False, False, True, False, False, False, True, False, False, False,
        # 2040-2049
        True, False, False, False, True, False, False, False, True, False,
        # 2050-2059
        False, False, True, False, False, False, True, False, False, False,
        # 2060-2069
        True, False, False, False, True, False, False, False, True, False,
        # 2070-2079
        False, False, True, False, False, False, True, False, False, False,
        # 2080-2089
        True, False, False, False, True, False, False, False, True, False,
        # 2090-2099
        False, False, True, False, False, False, True, False, False, False,
        # 2100-2109
        False, False, False, False, True, False, False, False, True, False,
        # 2110-2119
        False, False, True, False, False, False, True, False, False, False,
        # 2120-2129
        True, False, False, False, True, False, False, False, True, False,
        # 2130-2139
        False, False, True, False, False, False, True, False, False, False,
        # 2140-2149
        True, False, False, False, True, False, False, False, True, False,
        # 2150-2159
        False, False, True, False, False, False, True, False, False, False,
        # 2160-2169
        True, False, False, False, True, False, False, False, True, False,
        # 2170-2179
        False, False, True, False, False, False, True, False, False, False,
        # 2180-2189
        True, False, False, False, True, False, False, False, True, False,
        # 2190-2199
        False, False, True, False, False, False, True, False, False, False,
        # 2200
        False,
    ], dtype=np.int64)


def month_length_table():
    """The non-leap static table of ``Date::monthLength`` (index ``m - 1``).

    Derived from QuantLib (BSD-3-Clause); see NOTICE.md.
    """
    # ported from pureql/time/date.py (ql/date.cpp:259-267), QuantLib v1.43, BSD-3-Clause
    return np.array([
        31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31,
    ], dtype=np.int64)


def month_leap_length_table():
    """The leap-year static table of ``Date::monthLength`` (index ``m - 1``).

    Derived from QuantLib (BSD-3-Clause); see NOTICE.md.
    """
    # ported from pureql/time/date.py (ql/date.cpp:259-267), QuantLib v1.43, BSD-3-Clause
    return np.array([
        31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31,
    ], dtype=np.int64)


def month_offset_table():
    """The non-leap static table of ``Date::monthOffset``: 13 entries (index ``m - 1``).

    Derived from QuantLib (BSD-3-Clause); see NOTICE.md.
    """
    # ported from pureql/time/date.py (ql/date.cpp:269-281), QuantLib v1.43, BSD-3-Clause
    return np.array([
        0, 31, 59, 90, 120, 151,     # Jan - Jun
        181, 212, 243, 273, 304, 334,  # Jun - Dec
        365,  # used in dayOfMonth to bracket day
    ], dtype=np.int64)


def month_leap_offset_table():
    """The leap-year static table of ``Date::monthOffset``: 13 entries (index ``m - 1``).

    Derived from QuantLib (BSD-3-Clause); see NOTICE.md.
    """
    # ported from pureql/time/date.py (ql/date.cpp:269-281), QuantLib v1.43, BSD-3-Clause
    return np.array([
        0, 31, 60, 91, 121, 152,     # Jan - Jun
        182, 213, 244, 274, 305, 335,  # Jun - Dec
        366,  # used in dayOfMonth to bracket day
    ], dtype=np.int64)


def year_offset_table():
    """The static table of ``Date::yearOffset``: 31 December of the preceding year, 1900..2200.

    Derived from QuantLib (BSD-3-Clause); see NOTICE.md.
    """
    # ported from pureql/time/date.py (ql/date.cpp:283-351), QuantLib v1.43, BSD-3-Clause
    # the list of all December 31st in the preceding year
    # e.g. for 1901 yearOffset[1] is 366, that is, December 31 1900
    return np.array([
        # 1900-1909
        0, 366, 731, 1096, 1461, 1827, 2192, 2557, 2922, 3288,
        # 1910-1919
        3653, 4018, 4383, 4749, 5114, 5479, 5844, 6210, 6575, 6940,
        # 1920-1929
        7305, 7671, 8036, 8401, 8766, 9132, 9497, 9862, 10227, 10593,
        # 1930-1939
        10958, 11323, 11688, 12054, 12419, 12784, 13149, 13515, 13880, 14245,
        # 1940-1949
        14610, 14976, 15341, 15706, 16071, 16437, 16802, 17167, 17532, 17898,
        # 1950-1959
        18263, 18628, 18993, 19359, 19724, 20089, 20454, 20820, 21185, 21550,
        # 1960-1969
        21915, 22281, 22646, 23011, 23376, 23742, 24107, 24472, 24837, 25203,
        # 1970-1979
        25568, 25933, 26298, 26664, 27029, 27394, 27759, 28125, 28490, 28855,
        # 1980-1989
        29220, 29586, 29951, 30316, 30681, 31047, 31412, 31777, 32142, 32508,
        # 1990-1999
        32873, 33238, 33603, 33969, 34334, 34699, 35064, 35430, 35795, 36160,
        # 2000-2009
        36525, 36891, 37256, 37621, 37986, 38352, 38717, 39082, 39447, 39813,
        # 2010-2019
        40178, 40543, 40908, 41274, 41639, 42004, 42369, 42735, 43100, 43465,
        # 2020-2029
        43830, 44196, 44561, 44926, 45291, 45657, 46022, 46387, 46752, 47118,
        # 2030-2039
        47483, 47848, 48213, 48579, 48944, 49309, 49674, 50040, 50405, 50770,
        # 2040-2049
        51135, 51501, 51866, 52231, 52596, 52962, 53327, 53692, 54057, 54423,
        # 2050-2059
        54788, 55153, 55518, 55884, 56249, 56614, 56979, 57345, 57710, 58075,
        # 2060-2069
        58440, 58806, 59171, 59536, 59901, 60267, 60632, 60997, 61362, 61728,
        # 2070-2079
        62093, 62458, 62823, 63189, 63554, 63919, 64284, 64650, 65015, 65380,
        # 2080-2089
        65745, 66111, 66476, 66841, 67206, 67572, 67937, 68302, 68667, 69033,
        # 2090-2099
        69398, 69763, 70128, 70494, 70859, 71224, 71589, 71955, 72320, 72685,
        # 2100-2109
        73050, 73415, 73780, 74145, 74510, 74876, 75241, 75606, 75971, 76337,
        # 2110-2119
        76702, 77067, 77432, 77798, 78163, 78528, 78893, 79259, 79624, 79989,
        # 2120-2129
        80354, 80720, 81085, 81450, 81815, 82181, 82546, 82911, 83276, 83642,
        # 2130-2139
        84007, 84372, 84737, 85103, 85468, 85833, 86198, 86564, 86929, 87294,
        # 2140-2149
        87659, 88025, 88390, 88755, 89120, 89486, 89851, 90216, 90581, 90947,
        # 2150-2159
        91312, 91677, 92042, 92408, 92773, 93138, 93503, 93869, 94234, 94599,
        # 2160-2169
        94964, 95330, 95695, 96060, 96425, 96791, 97156, 97521, 97886, 98252,
        # 2170-2179
        98617, 98982, 99347, 99713, 100078, 100443, 100808, 101174, 101539, 101904,
        # 2180-2189
        102269, 102635, 103000, 103365, 103730, 104096, 104461, 104826, 105191, 105557,
        # 2190-2199
        105922, 106287, 106652, 107018, 107383, 107748, 108113, 108479, 108844, 109209,
        # 2200
        109574,
    ], dtype=np.int64)


def western_easter_table():
    """Western Easter Monday as the day of the year, for 1901..2199 (index ``yr - 1901``).

    The static table of ``Calendar::WesternImpl::easterMonday``.

    Derived from QuantLib (BSD-3-Clause); see NOTICE.md.
    """
    # ported from pureql/time/calendar.py (ql/calendar.cpp:199-233), QuantLib v1.43, BSD-3-Clause
    return np.array([
        98, 90, 103, 95, 114, 106, 91, 111, 102,  # 1901-1909
        87, 107, 99, 83, 103, 95, 115, 99, 91, 111,  # 1910-1919
        96, 87, 107, 92, 112, 103, 95, 108, 100, 91,  # 1920-1929
        111, 96, 88, 107, 92, 112, 104, 88, 108, 100,  # 1930-1939
        85, 104, 96, 116, 101, 92, 112, 97, 89, 108,  # 1940-1949
        100, 85, 105, 96, 109, 101, 93, 112, 97, 89,  # 1950-1959
        109, 93, 113, 105, 90, 109, 101, 86, 106, 97,  # 1960-1969
        89, 102, 94, 113, 105, 90, 110, 101, 86, 106,  # 1970-1979
        98, 110, 102, 94, 114, 98, 90, 110, 95, 86,  # 1980-1989
        106, 91, 111, 102, 94, 107, 99, 90, 103, 95,  # 1990-1999
        115, 106, 91, 111, 103, 87, 107, 99, 84, 103,  # 2000-2009
        95, 115, 100, 91, 111, 96, 88, 107, 92, 112,  # 2010-2019
        104, 95, 108, 100, 92, 111, 96, 88, 108, 92,  # 2020-2029
        112, 104, 89, 108, 100, 85, 105, 96, 116, 101,  # 2030-2039
        93, 112, 97, 89, 109, 100, 85, 105, 97, 109,  # 2040-2049
        101, 93, 113, 97, 89, 109, 94, 113, 105, 90,  # 2050-2059
        110, 101, 86, 106, 98, 89, 102, 94, 114, 105,  # 2060-2069
        90, 110, 102, 86, 106, 98, 111, 102, 94, 114,  # 2070-2079
        99, 90, 110, 95, 87, 106, 91, 111, 103, 94,  # 2080-2089
        107, 99, 91, 103, 95, 115, 107, 91, 111, 103,  # 2090-2099
        88, 108, 100, 85, 105, 96, 109, 101, 93, 112,  # 2100-2109
        97, 89, 109, 93, 113, 105, 90, 109, 101, 86,  # 2110-2119
        106, 97, 89, 102, 94, 113, 105, 90, 110, 101,  # 2120-2129
        86, 106, 98, 110, 102, 94, 114, 98, 90, 110,  # 2130-2139
        95, 86, 106, 91, 111, 102, 94, 107, 99, 90,  # 2140-2149
        103, 95, 115, 106, 91, 111, 103, 87, 107, 99,  # 2150-2159
        84, 103, 95, 115, 100, 91, 111, 96, 88, 107,  # 2160-2169
        92, 112, 104, 95, 108, 100, 92, 111, 96, 88,  # 2170-2179
        108, 92, 112, 104, 89, 108, 100, 85, 105, 96,  # 2180-2189
        116, 101, 93, 112, 97, 89, 109, 100, 85, 105,  # 2190-2199
    ], dtype=np.int64)


def is_leap(yr):
    """``Date::isLeap(y)``: whether ``yr`` is a leap year (1900 is, as in Excel).

    Raises outside 1900..2200.

    Derived from QuantLib (BSD-3-Clause); see NOTICE.md.
    """
    # ported from pureql/time/date.py (ql/date.cpp:187-256), QuantLib v1.43, BSD-3-Clause
    if not (yr >= 1900 and yr <= 2200):
        raise ValueError("year outside valid range")
    return bool(year_is_leap_table()[yr - 1900])


def year_offset(yr):
    """``Date::yearOffset(y)``: the serial of 31 December of year ``yr - 1``.

    DEV-01: raises outside 1900..2200 (the null date's year 1899 reads before
    the table in C++).

    Derived from QuantLib (BSD-3-Clause); see NOTICE.md.
    """
    # ported from pureql/time/date.py (ql/date.cpp:283-351), QuantLib v1.43, BSD-3-Clause
    if not (yr >= 1900 and yr <= 2200):
        raise ValueError(
            f"year {yr} is outside the YearOffset table [1900,2200]. `Date::yearOffset` indexes the table "
            f"without a bound check and the null date's year of 1899 reads before its first entry, which "
            f"is undefined behaviour in C++ and a wrapped index in Python (DEVIATIONS.md, DEV-01)"
        )
    return int(year_offset_table()[yr - 1900])


def month_length(m, leap):
    """``Date::monthLength(m, leapYear)``: the number of days of month ``m``; ``leap`` is 0/1.

    Derived from QuantLib (BSD-3-Clause); see NOTICE.md.
    """
    # ported from pureql/time/date.py (ql/date.cpp:259-267), QuantLib v1.43, BSD-3-Clause
    return int(month_leap_length_table()[m - 1]) if leap else int(month_length_table()[m - 1])


def month_offset(m, leap):
    """``Date::monthOffset(m, leapYear)``: days before month ``m``; ``m`` runs 1..13, ``leap`` is 0/1.

    The thirteenth entry (365 or 366) is the bracket ``month`` needs.

    Derived from QuantLib (BSD-3-Clause); see NOTICE.md.
    """
    # ported from pureql/time/date.py (ql/date.cpp:269-281), QuantLib v1.43, BSD-3-Clause
    return int(month_leap_offset_table()[m - 1]) if leap else int(month_offset_table()[m - 1])


def year(d):
    """``Date::year()``: ``d // 365 + 1900``, corrected down by at most one.

    The null date gives 1899, as upstream does.

    Derived from QuantLib (BSD-3-Clause); see NOTICE.md.
    """
    # ported from pureql/time/date.py (ql/date.cpp:93-99), QuantLib v1.43, BSD-3-Clause
    y = (d // 365) + 1900
    # yearOffset(y) is December 31st of the preceding year
    if d <= year_offset(y):
        y -= 1
    return y


def day_of_year(d):
    """``Date::dayOfYear()``: one-based. DEV-01: raises on the null date.

    Derived from QuantLib (BSD-3-Clause); see NOTICE.md.
    """
    # ported from pureql/time/date.py (ql/date.hpp:400-402), QuantLib v1.43, BSD-3-Clause
    return d - year_offset(year(d))


def month(d):
    """``Date::month()``: brackets the day of the year in the month offsets (1..12).

    Both bracketing loops of upstream are kept. DEV-01: raises on the null
    date.

    Derived from QuantLib (BSD-3-Clause); see NOTICE.md.
    """
    # ported from pureql/time/date.py (ql/date.cpp:82-91), QuantLib v1.43, BSD-3-Clause
    doy = day_of_year(d)  # dayOfYear is 1 based
    m = doy // 30 + 1
    leap = int(is_leap(year(d)))
    while doy <= month_offset(m, leap):
        m -= 1
    while doy > month_offset(m + 1, leap):
        m += 1
    return m


def day_of_month(d):
    """``Date::dayOfMonth()``: ``dayOfYear() - monthOffset(month(), isLeap(year()))``.

    DEV-01: raises on the null date.

    Derived from QuantLib (BSD-3-Clause); see NOTICE.md.
    """
    # ported from pureql/time/date.py (ql/date.hpp:396-398), QuantLib v1.43, BSD-3-Clause
    return day_of_year(d) - month_offset(month(d), int(is_leap(year(d))))


def weekday(d):
    """``Date::weekday()``: ``d % 7`` with 0 meaning Saturday (Sunday = 1 .. Saturday = 7).

    Derived from QuantLib (BSD-3-Clause); see NOTICE.md.
    """
    # ported from pureql/time/date.py (ql/date.hpp:391-394), QuantLib v1.43, BSD-3-Clause
    w = d % 7
    return 7 if w == 0 else w


def end_of_month(d):
    """``Date::endOfMonth(d)``: the last calendar day of ``d``'s month.

    Derived from QuantLib (BSD-3-Clause); see NOTICE.md.
    """
    # ported from pureql/time/date.py (ql/date.hpp:424-428), QuantLib v1.43, BSD-3-Clause
    m = month(d)
    y = year(d)
    return make_date(month_length(m, int(is_leap(y))), m, y)


def is_end_of_month(d):
    """``Date::isEndOfMonth(d)``: whether ``d`` is the last calendar day of its month.

    Derived from QuantLib (BSD-3-Clause); see NOTICE.md.
    """
    # ported from pureql/time/date.py (ql/date.hpp:430-432), QuantLib v1.43, BSD-3-Clause
    return day_of_month(d) == month_length(month(d), int(is_leap(year(d))))


def make_date(dd, m, yr):
    """``Date(d, m, y)``: the serial of day ``dd`` of month ``m`` of year ``yr``, each checked.

    Derived from QuantLib (BSD-3-Clause); see NOTICE.md.
    """
    # ported from pureql/time/date.py (ql/date.cpp:66-80), QuantLib v1.43, BSD-3-Clause
    if not (yr > 1900 and yr < 2200):
        raise ValueError(f"year {yr} out of bound. It must be in [1901,2199]")
    if not (m > 0 and m < 13):
        raise ValueError(f"month {m} outside January-December range [1,12]")

    leap = int(is_leap(yr))
    len_, offset = month_length(m, leap), month_offset(m, leap)
    if not (dd <= len_ and dd > 0):
        raise ValueError(f"day outside month ({m}) day-range [1,{len_}]")

    return dd + offset + year_offset(yr)

_is_cached = False


def check_serial(d):
    """``Date::checkSerialNumber``: True if ``d`` is in [367, 109574], else raises.

    Every ``Date(serial)`` of upstream, including ``Date + n``, runs this check.

    Derived from QuantLib (BSD-3-Clause); see NOTICE.md.
    """
    # ported from pureql/time/date.py (ql/date.cpp:757-764), QuantLib v1.43, BSD-3-Clause
    if not (d >= MIN_SERIAL and d <= MAX_SERIAL):
        raise ValueError(
            f"Date's serial number ({d}) outside allowed range "
            f"[{MIN_SERIAL}-{MAX_SERIAL}], i.e. "
            f"[January 1st, 1901-December 31st, 2199]"
        )
    return True

_is_cached = False


def advance_date(d, n, unit):
    """``Date::advance(date, n, units)``: the Date + Period algebra (``unit`` a ``TU_*`` code).

    Days and Weeks move the serial, range-checked like ``Date(serial)``.
    Months carries into years and clips the day to the target month's
    length; Years clips 29 February only. Other units raise.

    Derived from QuantLib (BSD-3-Clause); see NOTICE.md.
    """
    # ported from pureql/time/date.py (ql/date.cpp:139-185), QuantLib v1.43, BSD-3-Clause
    # ported from pureql/time/date.py (ql/date.hpp:408-410), QuantLib v1.43, BSD-3-Clause
    if unit == TU_DAYS:
        check_serial(d + n)
        return d + n
    elif unit == TU_WEEKS:
        check_serial(d + 7 * n)
        return d + 7 * n
    elif unit == TU_MONTHS:
        dd = day_of_month(d)
        m = month(d) + n
        y = year(d)
        while m > 12:
            m -= 12
            y += 1
        while m < 1:
            m += 12
            y -= 1

        if not (y >= 1900 and y <= 2199):
            raise ValueError(f"year {y} out of bounds. It must be in [1901,2199]")

        length = month_length(m, int(is_leap(y)))
        if dd > length:
            dd = length

        return make_date(dd, m, y)
    elif unit == TU_YEARS:
        dd = day_of_month(d)
        m = month(d)
        y = year(d) + n

        if not (y >= 1900 and y <= 2199):
            raise ValueError(f"year {y} out of bounds. It must be in [1901,2199]")

        if dd == 29 and m == FEBRUARY and not is_leap(y):
            dd = 28

        return make_date(dd, m, y)
    else:
        raise ValueError("undefined time units")

_is_cached = False


def easter_monday(yr):
    """``WesternImpl::easterMonday(y)``: Western Easter Monday as the day of the year.

    DEV-17: raises outside 1901..2199 instead of reading out of the table.

    Derived from QuantLib (BSD-3-Clause); see NOTICE.md.
    """
    # ported from pureql/time/calendar.py (ql/calendar.cpp:199-233), QuantLib v1.43, BSD-3-Clause
    if not (yr >= 1901 and yr <= 2199):
        raise ValueError(
            f"year {yr} is outside the Western EasterMonday table [1901,2199]. `easterMonday` indexes it "
            f"without a bound check, which is an out-of-bounds read in C++ and a wrapped index in Python "
            f"(DEVIATIONS.md, DEV-17)"
        )
    return int(western_easter_table()[yr - 1901])


def is_weekend_western(w):
    """``WesternImpl::isWeekend(w)``: Saturday or Sunday.

    Derived from QuantLib (BSD-3-Clause); see NOTICE.md.
    """
    # ported from pureql/time/calendar.py (ql/calendar.cpp:195-197), QuantLib v1.43, BSD-3-Clause
    return w == SATURDAY or w == SUNDAY


def target_bd(d):
    """``TARGET::Impl::isBusinessDay``: the euro-area settlement calendar.

    Derived from QuantLib (BSD-3-Clause); see NOTICE.md.
    """
    # ported from pureql/time/calendars/target.py (ql/target.cpp:30-54), QuantLib v1.43, BSD-3-Clause
    w = weekday(d)
    dd, doy = day_of_month(d), day_of_year(d)
    m = month(d)
    y = year(d)
    em = easter_monday(y)
    if (
        is_weekend_western(w)
        # New Year's Day
        or (dd == 1 and m == JANUARY)
        # Good Friday
        or (doy == em - 3 and y >= 2000)
        # Easter Monday
        or (doy == em and y >= 2000)
        # Labour Day
        or (dd == 1 and m == MAY and y >= 2000)
        # Christmas
        or (dd == 25 and m == DECEMBER)
        # Day of Goodwill
        or (dd == 26 and m == DECEMBER and y >= 2000)
        # December 31st, 1998, 1999, and 2001 only
        or (dd == 31 and m == DECEMBER and (y == 1998 or y == 1999 or y == 2001))
    ):
        return False
    return True


def us_washington_birthday(dd, m, yr, w):
    """Presidents' Day: the third Monday in February since 1971, 22 February before.

    Derived from QuantLib (BSD-3-Clause); see NOTICE.md.
    """
    # ported from pureql/time/calendars/unitedstates.py (ql/unitedstates.cpp:35-44), QuantLib v1.43, BSD-3-Clause
    if yr >= 1971:
        # third Monday in February
        return (dd >= 15 and dd <= 21) and w == MONDAY and m == FEBRUARY
    else:
        # February 22nd, possibly adjusted
        return (dd == 22 or (dd == 23 and w == MONDAY) or (dd == 21 and w == FRIDAY)) and m == FEBRUARY

_is_cached = False


def us_memorial_day(dd, m, yr, w):
    """Memorial Day: the last Monday in May since 1971, 30 May before.

    Derived from QuantLib (BSD-3-Clause); see NOTICE.md.
    """
    # ported from pureql/time/calendars/unitedstates.py (ql/unitedstates.cpp:46-55), QuantLib v1.43, BSD-3-Clause
    if yr >= 1971:
        # last Monday in May
        return dd >= 25 and w == MONDAY and m == MAY
    else:
        # May 30th, possibly adjusted
        return (dd == 30 or (dd == 31 and w == MONDAY) or (dd == 29 and w == FRIDAY)) and m == MAY

_is_cached = False


def us_labor_day(dd, m, yr, w):
    """Labor Day: the first Monday in September (``yr`` unused, as upstream).

    Derived from QuantLib (BSD-3-Clause); see NOTICE.md.
    """
    # ported from pureql/time/calendars/unitedstates.py (ql/unitedstates.cpp:57-60), QuantLib v1.43, BSD-3-Clause
    # first Monday in September
    return dd <= 7 and w == MONDAY and m == SEPTEMBER

_is_cached = False


def us_columbus_day(dd, m, yr, w):
    """Columbus Day: the second Monday in October, since 1971.

    Derived from QuantLib (BSD-3-Clause); see NOTICE.md.
    """
    # ported from pureql/time/calendars/unitedstates.py (ql/unitedstates.cpp:62-66), QuantLib v1.43, BSD-3-Clause
    # second Monday in October
    return (dd >= 8 and dd <= 14) and w == MONDAY and m == OCTOBER and yr >= 1971

_is_cached = False


def us_veterans_day(dd, m, yr, w):
    """Veterans Day: 11 November rolled to either side; the fourth Monday in October 1971-1977.

    Derived from QuantLib (BSD-3-Clause); see NOTICE.md.
    """
    # ported from pureql/time/calendars/unitedstates.py (ql/unitedstates.cpp:68-77), QuantLib v1.43, BSD-3-Clause
    if yr <= 1970 or yr >= 1978:
        # November 11th, adjusted
        return (dd == 11 or (dd == 12 and w == MONDAY) or (dd == 10 and w == FRIDAY)) and m == NOVEMBER
    else:
        # fourth Monday in October
        return (dd >= 22 and dd <= 28) and w == MONDAY and m == OCTOBER

_is_cached = False


def us_veterans_day_no_saturday(dd, m, yr, w):
    """Veterans Day without the Saturday-to-Friday roll (bond market form).

    Derived from QuantLib (BSD-3-Clause); see NOTICE.md.
    """
    # ported from pureql/time/calendars/unitedstates.py (ql/unitedstates.cpp:79-87), QuantLib v1.43, BSD-3-Clause
    if yr <= 1970 or yr >= 1978:
        # November 11th, adjusted, but no Saturday to Friday
        return (dd == 11 or (dd == 12 and w == MONDAY)) and m == NOVEMBER
    else:
        # fourth Monday in October
        return (dd >= 22 and dd <= 28) and w == MONDAY and m == OCTOBER

_is_cached = False


def us_juneteenth(dd, m, yr, w, move_to_friday):
    """Juneteenth: 19 June since 2022, rolled to Monday, and to Friday if ``move_to_friday`` (0/1).

    Derived from QuantLib (BSD-3-Clause); see NOTICE.md.
    """
    # ported from pureql/time/calendars/unitedstates.py (ql/unitedstates.cpp:89-93), QuantLib v1.43, BSD-3-Clause
    # declared in 2021, but only observed by exchanges since 2022
    return bool(
        (dd == 19 or (dd == 20 and w == MONDAY) or ((dd == 18 and w == FRIDAY) and move_to_friday))
        and m == JUNE
        and yr >= 2022
    )

_is_cached = False


def us_settlement_bd(d):
    """``UnitedStates::SettlementImpl::isBusinessDay``: the US federal-holiday calendar.

    Derived from QuantLib (BSD-3-Clause); see NOTICE.md.
    """
    # ported from pureql/time/calendars/unitedstates.py (ql/unitedstates.cpp:134-169), QuantLib v1.43, BSD-3-Clause
    w = weekday(d)
    dd = day_of_month(d)
    m = month(d)
    y = year(d)
    if (
        is_weekend_western(w)
        # New Year's Day (possibly moved to Monday if on Sunday)
        or ((dd == 1 or (dd == 2 and w == MONDAY)) and m == JANUARY)
        # (or to Friday if on Saturday)
        or (dd == 31 and w == FRIDAY and m == DECEMBER)
        # Martin Luther King's birthday (third Monday in January)
        or ((dd >= 15 and dd <= 21) and w == MONDAY and m == JANUARY and y >= 1983)
        # Washington's birthday (third Monday in February)
        or us_washington_birthday(dd, m, y, w)
        # Memorial Day (last Monday in May)
        or us_memorial_day(dd, m, y, w)
        # Juneteenth (Monday if Sunday or Friday if Saturday)
        or us_juneteenth(dd, m, y, w, 1)
        # Independence Day (Monday if Sunday or Friday if Saturday)
        or ((dd == 4 or (dd == 5 and w == MONDAY) or (dd == 3 and w == FRIDAY)) and m == JULY)
        # Labor Day (first Monday in September)
        or us_labor_day(dd, m, y, w)
        # Columbus Day (second Monday in October)
        or us_columbus_day(dd, m, y, w)
        # Veteran's Day (Monday if Sunday or Friday if Saturday)
        or us_veterans_day(dd, m, y, w)
        # Thanksgiving Day (fourth Thursday in November)
        or ((dd >= 22 and dd <= 28) and w == THURSDAY and m == NOVEMBER)
        # Christmas (Monday if Sunday or Friday if Saturday)
        or ((dd == 25 or (dd == 26 and w == MONDAY) or (dd == 24 and w == FRIDAY)) and m == DECEMBER)
    ):
        return False
    return True


def us_govbond_bd(d):
    """``UnitedStates::GovernmentBondImpl::isBusinessDay``: the US government-bond market.

    Good Friday is a business day when it falls on the 1st to the 7th since
    1996 (the NFP release); three special closings.

    Derived from QuantLib (BSD-3-Clause); see NOTICE.md.
    """
    # ported from pureql/time/calendars/unitedstates.py (ql/unitedstates.cpp:273-329), QuantLib v1.43, BSD-3-Clause
    w = weekday(d)
    dd, doy = day_of_month(d), day_of_year(d)
    m = month(d)
    y = year(d)
    em = easter_monday(y)
    if (
        is_weekend_western(w)
        # New Year's Day (possibly moved to Monday if on Sunday)
        or ((dd == 1 or (dd == 2 and w == MONDAY)) and m == JANUARY)
        # Martin Luther King's birthday (third Monday in January)
        or ((dd >= 15 and dd <= 21) and w == MONDAY and m == JANUARY and y >= 1983)
        # Washington's birthday (third Monday in February)
        or us_washington_birthday(dd, m, y, w)
        # Good Friday. Since 1996 it's an early close and not a full market
        # close when it coincides with the NFP release date, which is the
        # first Friday of the month(*).
        # See <https://www.sifma.org/resources/general/holiday-schedule/>
        #
        # (*) The full rule is "the third Friday after the conclusion of the
        # week which includes the 12th of the month". This is usually the
        # first Friday of the next month, but can be the second Friday if the
        # month has fewer than 31 days. Since Good Friday is always between
        # March 20th and April 23rd, it can only coincide with the April NFP,
        # which is always on the first Friday, because March has 31 days.
        or (doy == em - 3 and (y < 1996 or dd > 7))
        # Memorial Day (last Monday in May)
        or us_memorial_day(dd, m, y, w)
        # Juneteenth (Monday if Sunday or Friday if Saturday)
        or us_juneteenth(dd, m, y, w, 1)
        # Independence Day (Monday if Sunday or Friday if Saturday)
        or ((dd == 4 or (dd == 5 and w == MONDAY) or (dd == 3 and w == FRIDAY)) and m == JULY)
        # Labor Day (first Monday in September)
        or us_labor_day(dd, m, y, w)
        # Columbus Day (second Monday in October)
        or us_columbus_day(dd, m, y, w)
        # Veteran's Day (Monday if Sunday)
        or us_veterans_day_no_saturday(dd, m, y, w)
        # Thanksgiving Day (fourth Thursday in November)
        or ((dd >= 22 and dd <= 28) and w == THURSDAY and m == NOVEMBER)
        # Christmas (Monday if Sunday or Friday if Saturday)
        or ((dd == 25 or (dd == 26 and w == MONDAY) or (dd == 24 and w == FRIDAY)) and m == DECEMBER)
    ):
        return False

    # Special closings
    if (
        # President Bush's Funeral
        (y == 2018 and m == DECEMBER and dd == 5)
        # Hurricane Sandy
        or (y == 2012 and m == OCTOBER and dd == 30)
        # President Reagan's funeral
        or (y == 2004 and m == JUNE and dd == 11)
    ):
        return False

    return True


def is_business_day(cal, d):
    """``Calendar::isBusinessDay(d)`` dispatched on the calendar code ``cal``.

    ``CAL_NULL`` is always True. v1 has no added or removed holidays, so the
    market rule decides. Unknown codes raise.

    Derived from QuantLib (BSD-3-Clause); see NOTICE.md.
    """
    # ported from pureql/time/calendar.py (ql/calendar.hpp:229-247), QuantLib v1.43, BSD-3-Clause
    # ported from pureql/time/calendars/nullcalendar.py (ql/nullcalendar.hpp:44), QuantLib v1.43, BSD-3-Clause
    if cal == CAL_NULL:
        return True
    elif cal == CAL_TARGET:
        return target_bd(d)
    elif cal == CAL_US_SETTLEMENT:
        return us_settlement_bd(d)
    elif cal == CAL_US_GOVBOND:
        return us_govbond_bd(d)
    else:
        raise ValueError(f"calendar {cal} not supported in this model version")


def is_holiday(cal, d):
    """``Calendar::isHoliday(d)``: ``not isBusinessDay(d)``.

    Derived from QuantLib (BSD-3-Clause); see NOTICE.md.
    """
    # ported from pureql/time/calendar.py (ql/calendar.hpp:265-267), QuantLib v1.43, BSD-3-Clause
    return not is_business_day(cal, d)

_is_cached = False


def cal_end_of_month(cal, d):
    """``Calendar::endOfMonth(d)``: the last business day of ``d``'s month.

    Derived from QuantLib (BSD-3-Clause); see NOTICE.md.
    """
    # ported from pureql/time/calendar.py (ql/calendar.hpp:261-263), QuantLib v1.43, BSD-3-Clause
    return adjust(cal, end_of_month(d), BDC_PRECEDING)

_is_cached = False


def cal_is_end_of_month(cal, d):
    """``Calendar::isEndOfMonth(d)``: on or after the month's last business day.

    Derived from QuantLib (BSD-3-Clause); see NOTICE.md.
    """
    # ported from pureql/time/calendar.py (ql/calendar.hpp:257-259), QuantLib v1.43, BSD-3-Clause
    return d >= cal_end_of_month(cal, d)

_is_cached = False


def adjust(cal, d, conv):
    """``Calendar::adjust(d, c)``: move a holiday to a business day by convention ``conv``.

    All seven ``BDC_*`` conventions; ``Nearest`` prefers the following day
    on a tie. Each ``d1 + 1`` / ``d1 - 1`` is range-checked like
    upstream's ``Date + n``.

    Derived from QuantLib (BSD-3-Clause); see NOTICE.md.
    """
    # ported from pureql/time/calendar.py (ql/calendar.cpp:84-128), QuantLib v1.43, BSD-3-Clause
    if d == NULL_DATE:
        raise ValueError("null date")

    c = conv
    if c == BDC_UNADJUSTED:
        return d

    d1 = d
    if c == BDC_FOLLOWING or c == BDC_MODIFIED_FOLLOWING or c == BDC_HALF_MONTH_MODIFIED_FOLLOWING:
        while is_holiday(cal, d1):
            d1 = d1 + 1
            check_serial(d1)
        if c == BDC_MODIFIED_FOLLOWING or c == BDC_HALF_MONTH_MODIFIED_FOLLOWING:
            if month(d1) != month(d):
                return adjust(cal, d, BDC_PRECEDING)
            if c == BDC_HALF_MONTH_MODIFIED_FOLLOWING:
                if day_of_month(d) <= 15 and day_of_month(d1) > 15:
                    return adjust(cal, d, BDC_PRECEDING)
    elif c == BDC_PRECEDING or c == BDC_MODIFIED_PRECEDING:
        while is_holiday(cal, d1):
            d1 = d1 - 1
            check_serial(d1)
        if c == BDC_MODIFIED_PRECEDING and month(d1) != month(d):
            return adjust(cal, d, BDC_FOLLOWING)
    elif c == BDC_NEAREST:
        d2 = d
        while is_holiday(cal, d1) and is_holiday(cal, d2):
            d1 = d1 + 1
            check_serial(d1)
            d2 = d2 - 1
            check_serial(d2)
        if is_holiday(cal, d1):
            return d2
        else:
            return d1
    else:
        raise ValueError("unknown business-day convention")
    return d1

_is_cached = False


def advance(cal, d, n, unit, conv, eom):
    """``Calendar::advance(d, n, unit, c, endOfMonth)``; ``eom`` is 0/1.

    ``n == 0`` adjusts; Days steps business days and ignores ``conv``; Weeks
    adds and adjusts; Months/Years add, then apply the end-of-month rule
    (calendar-day rule if Unadjusted, business-day rule otherwise).

    Derived from QuantLib (BSD-3-Clause); see NOTICE.md.
    """
    # ported from pureql/time/calendar.py (ql/calendar.cpp:130-173), QuantLib v1.43, BSD-3-Clause
    if d == NULL_DATE:
        raise ValueError("null date")
    if n == 0:
        return adjust(cal, d, conv)
    elif unit == TU_DAYS:
        d1 = d
        if n > 0:
            while n > 0:
                d1 = d1 + 1
                check_serial(d1)
                while is_holiday(cal, d1):
                    d1 = d1 + 1
                    check_serial(d1)
                n -= 1
        else:
            while n < 0:
                d1 = d1 - 1
                check_serial(d1)
                while is_holiday(cal, d1):
                    d1 = d1 - 1
                    check_serial(d1)
                n += 1
        return d1
    elif unit == TU_WEEKS:
        d1 = advance_date(d, n, unit)
        return adjust(cal, d1, conv)
    else:
        d1 = advance_date(d, n, unit)

        # we are sure the unit is Months or Years
        if eom:
            if conv == BDC_UNADJUSTED:
                # move to the last calendar day if d is the last calendar day
                if is_end_of_month(d):
                    return end_of_month(d1)
            else:
                # move to the last business day if d is the last business day
                if cal_is_end_of_month(cal, d):
                    return cal_end_of_month(cal, d1)
        return adjust(cal, d1, conv)

_is_cached = False


def day_count(dc, d1, d2):
    """``DayCounter::dayCount(d1, d2)`` dispatched on the day-counter code ``dc``.

    Actual/360 (without the last day), Actual/365 (Fixed) Standard, and
    30/360 USA, Bond Basis (= ISMA) and European (= Eurobond Basis). Code 0
    is the empty ``DayCounter()``; other codes raise.

    Derived from QuantLib (BSD-3-Clause); see NOTICE.md.
    """
    # ported from pureql/time/daycounter.py (ql/daycounter.hpp:122-126), QuantLib v1.43, BSD-3-Clause
    # ported from pureql/time/daycounters/thirty360.py (ql/thirty360.cpp:34-55), QuantLib v1.43, BSD-3-Clause
    # ported from pureql/time/daycounters/actual360.py (ql/actual360.hpp:50-52), QuantLib v1.43, BSD-3-Clause
    # ported from pureql/time/daycounter.py (ql/daycounter.hpp:51-55), QuantLib v1.43, BSD-3-Clause
    # ported from pureql/time/daycounters/thirty360.py (ql/thirty360.cpp:28-30), QuantLib v1.43, BSD-3-Clause
    # ported from pureql/time/daycounters/thirty360.py (ql/thirty360.cpp:57-73), QuantLib v1.43, BSD-3-Clause
    # ported from pureql/time/daycounters/thirty360.py (ql/thirty360.cpp:75-85), QuantLib v1.43, BSD-3-Clause
    # ported from pureql/time/daycounters/thirty360.py (ql/thirty360.cpp:87-97), QuantLib v1.43, BSD-3-Clause
    if dc == 0:
        raise ValueError("no day counter implementation provided")
    if dc == DC_ACT360:
        # Actual360(includeLastDay=false)
        return (d2 - d1) + 0
    elif dc == DC_ACT365F:
        # Actual365Fixed(Standard) inherits DayCounter::Impl::dayCount
        return d2 - d1
    elif dc == DC_30360_USA:
        dd1, dd2 = day_of_month(d1), day_of_month(d2)
        mm1, mm2 = month(d1), month(d2)
        yy1, yy2 = year(d1), year(d2)

        # See https://en.wikipedia.org/wiki/Day_count_convention#30/360_US
        # NOTE: the order of checks is important
        # _isLastOfFebruary(d, m, y): m == 2 and d == 28 + (isLeap(y) ? 1 : 0)
        if mm1 == 2 and dd1 == 28 + (1 if is_leap(yy1) else 0):
            if mm2 == 2 and dd2 == 28 + (1 if is_leap(yy2) else 0):
                dd2 = 30
            dd1 = 30
        if dd2 == 31 and dd1 >= 30:
            dd2 = 30
        if dd1 == 31:
            dd1 = 30

        return 360 * (yy2 - yy1) + 30 * (mm2 - mm1) + (dd2 - dd1)
    elif dc == DC_30360_BB:
        # Thirty360::ISMA_Impl (BondBasis and ISMA)
        dd1, dd2 = day_of_month(d1), day_of_month(d2)
        mm1, mm2 = month(d1), month(d2)
        yy1, yy2 = year(d1), year(d2)

        if dd1 == 31:
            dd1 = 30
        if dd2 == 31 and dd1 == 30:
            dd2 = 30

        return 360 * (yy2 - yy1) + 30 * (mm2 - mm1) + (dd2 - dd1)
    elif dc == DC_30360_EU:
        # Thirty360::EU_Impl (European and EurobondBasis)
        dd1, dd2 = day_of_month(d1), day_of_month(d2)
        mm1, mm2 = month(d1), month(d2)
        yy1, yy2 = year(d1), year(d2)

        if dd1 == 31:
            dd1 = 30
        if dd2 == 31:
            dd2 = 30

        return 360 * (yy2 - yy1) + 30 * (mm2 - mm1) + (dd2 - dd1)
    else:
        raise ValueError(f"day counter {dc} not supported in this model version")

_is_cached = False


def year_fraction(dc, d1, d2, r1, r2):
    """``DayCounter::yearFraction(d1, d2, refPeriodStart, refPeriodEnd)`` dispatched on ``dc``.

    ``r1`` and ``r2`` are the reference dates (0 = the null date); the v1
    day counters ignore them.

    Derived from QuantLib (BSD-3-Clause); see NOTICE.md.
    """
    # ported from pureql/time/daycounter.py (ql/daycounter.hpp:128-132), QuantLib v1.43, BSD-3-Clause
    # ported from pureql/time/daycounters/actual360.py (ql/actual360.hpp:53-57), QuantLib v1.43, BSD-3-Clause
    # ported from pureql/time/date.py (ql/date.hpp:272, date.hpp:438-440), QuantLib v1.43, BSD-3-Clause
    # ported from pureql/time/daycounters/actual365fixed.py (ql/actual365fixed.hpp:55-58), QuantLib v1.43, BSD-3-Clause
    # ported from pureql/time/daycounters/thirty360.py (ql/thirty360.hpp:92-95), QuantLib v1.43, BSD-3-Clause
    if dc == 0:
        raise ValueError("no day counter implementation provided")
    if dc == DC_ACT360:
        # (daysBetween(d1,d2) + (includeLastDay_ ? 1.0 : 0.0))/360.0, includeLastDay_ false
        return (float(d2 - d1) + 0.0) / 360.0
    elif dc == DC_ACT365F:
        return float(d2 - d1) / 365.0
    elif dc == DC_30360_USA or dc == DC_30360_BB or dc == DC_30360_EU:
        return day_count(dc, d1, d2) / 360.0
    else:
        raise ValueError(f"day counter {dc} not supported in this model version")

_is_cached = False


def daycounter_name(dc):
    """``DayCounter.name()`` of the v1 day-counter code ``dc``, e.g. ``'30/360 (Bond Basis)'``.

    The text pureql prints for a day counter (``str(dayCounter)``), used in
    error messages; the inverse of ``Data.daycounter_code`` up to the
    BondBasis/ISMA and European/EurobondBasis pairs, which share a code and a
    name. Any other code gives ``'day counter <dc>'``.

    Derived from QuantLib (BSD-3-Clause); see NOTICE.md.
    """
    # ported from pureql/time/daycounters/actual360.py (ql/actual360.hpp:45-49), QuantLib v1.43, BSD-3-Clause
    # ported from pureql/time/daycounters/actual365fixed.py (ql/actual365fixed.hpp:54), QuantLib v1.43, BSD-3-Clause
    # ported from pureql/time/daycounters/thirty360.py (ql/thirty360.hpp:99), QuantLib v1.43, BSD-3-Clause
    # ported from pureql/time/daycounters/thirty360.py (ql/thirty360.hpp:104), QuantLib v1.43, BSD-3-Clause
    # ported from pureql/time/daycounters/thirty360.py (ql/thirty360.hpp:109), QuantLib v1.43, BSD-3-Clause
    if dc == DC_ACT360:
        return "Actual/360"
    elif dc == DC_ACT365F:
        return "Actual/365 (Fixed)"
    elif dc == DC_30360_USA:
        return "30/360 (US)"
    elif dc == DC_30360_BB:
        return "30/360 (Bond Basis)"
    elif dc == DC_30360_EU:
        return "30E/360 (Eurobond Basis)"
    return "day counter " + str(dc)

_is_cached = False


def period_frequency(n, unit):
    """``Period(n, unit).frequency()``: the tenor read back as a ``FREQ_*`` code.

    No normalisation (12M is Annual, 24M and 7D are OtherFrequency); a zero
    length is Once for Years and NoFrequency otherwise; units other than the
    four ``TU_*`` codes raise.

    Derived from QuantLib (BSD-3-Clause); see NOTICE.md.
    """
    # ported from pureql/time/period.py (ql/period.cpp:69-106), QuantLib v1.43, BSD-3-Clause
    # unsigned version
    length = abs(n)

    if length == 0:
        if unit == TU_YEARS:
            return FREQ_ONCE
        return FREQ_NO_FREQUENCY

    if unit == TU_YEARS:
        if length == 1:
            return FREQ_ANNUAL
        else:
            return FREQ_OTHER_FREQUENCY
    elif unit == TU_MONTHS:
        if 12 % length == 0 and length <= 12:
            return 12 // length
        else:
            return FREQ_OTHER_FREQUENCY
    elif unit == TU_WEEKS:
        if length == 1:
            return FREQ_WEEKLY
        elif length == 2:
            return FREQ_BIWEEKLY
        elif length == 4:
            return FREQ_EVERY_FOURTH_WEEK
        else:
            return FREQ_OTHER_FREQUENCY
    elif unit == TU_DAYS:
        if length == 1:
            return FREQ_DAILY
        else:
            return FREQ_OTHER_FREQUENCY
    else:
        raise ValueError(f"unknown time unit ({unit})")

_is_cached = False


def allows_end_of_month(n, unit):
    """``allowsEndOfMonth(Period(n, unit))``: a non-zero Months or Years tenor of at least 1M.

    ``tenor >= 1 * Months`` is ``!(tenor < 1 * Months)``, written out with
    the arms of ``operator<`` that a Months or Years tenor can reach.

    Derived from QuantLib (BSD-3-Clause); see NOTICE.md.
    """
    # ported from pureql/time/schedule.py (ql/schedule.cpp:656-658), QuantLib v1.43, BSD-3-Clause
    # ported from pureql/time/period.py (ql/period.hpp:178-180), QuantLib v1.43, BSD-3-Clause
    # ported from pureql/time/period.py (ql/period.cpp:347-377), QuantLib v1.43, BSD-3-Clause
    if not (unit == TU_MONTHS or unit == TU_YEARS):
        return False
    # p1 = Period(n, unit), p2 = Period(1, Months); p1 < p2:
    if n == 0:
        # special cases
        less = 1 > 0
    elif unit == TU_MONTHS:
        # exact comparisons: same units
        less = n < 1
    else:
        # exact comparisons: Years against Months
        less = 12 * n < 1
    return not less

_is_cached = False


# ---------------------------------------------------------------------------
# References

lib = ("Interface", ("..", "Lib"), "auto")
