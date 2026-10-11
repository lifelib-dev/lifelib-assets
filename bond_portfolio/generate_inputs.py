"""Seeded synthetic inputs for the BondPortfolio model.

Writes the CSV schema of ``bond_portfolio/inputs.md`` (bonds.csv,
coupon_rates.csv, valuation_dates.csv, curve_params.csv, curve_nodes.csv,
spreads.csv) for a random portfolio of v1 bonds and S scenarios x T
valuation dates::

    python bond_portfolio/generate_inputs.py --n-bonds 1000 --n-scen 2 --n-times 13 \\
        --seed 1 --out outputs/inputs_1k [--validate]

or the small, deterministic, coverage-complete set used by the mx2cy sample
(every calendar, day counter, convention and compounding the v1 model
supports; both bond and curve types; stubs; end of month; T+0..3; a
forward-start and a matured bond; extrapolation on and off; 2 scenarios x 4
dates; prices and yields)::

    python bond_portfolio/generate_inputs.py --coverage --out tools/cy/sample_inputs

The same arguments always write the same files (numpy ``default_rng(seed)``).
Every generated bond is constructible by pureql by design; ``--validate``
checks this by building each bond with pureql, which is imported from
``PUREQL_SRC`` (default ``../quantlib-migration/src``). The model itself never
imports pureql.
"""

import argparse
import csv
import datetime
import os
import pathlib
import sys

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[1]

CALENDARS = ("NullCalendar", "TARGET", "UnitedStates.Settlement", "UnitedStates.GovernmentBond")
DAY_COUNTERS = ("Actual360", "Actual365Fixed", "Thirty360.USA", "Thirty360.BondBasis",
                "Thirty360.ISMA", "Thirty360.European", "Thirty360.EurobondBasis")
BDCS = ("Following", "ModifiedFollowing", "Preceding", "ModifiedPreceding", "Unadjusted",
        "HalfMonthModifiedFollowing", "Nearest")
COMPOUNDINGS = ("Simple", "Compounded", "Continuous", "SimpleThenCompounded", "CompoundedThenSimple")
QUOTE_FREQUENCIES = ("Annual", "Semiannual", "Quarterly", "Monthly")
SPREAD_IDS = ("AAA", "AA", "A", "BBB", "BB")
SPREAD_BASE = (0.002, 0.004, 0.007, 0.012, 0.025)
CURVE_TENORS = ("0D", "1M", "3M", "6M", "1Y", "2Y", "3Y", "5Y", "7Y", "10Y", "15Y", "20Y",
                "30Y", "40Y", "60Y")

BOND_COLUMNS = (
    "bond_key", "bond_type", "face_amount", "settlement_days", "calendar", "issue_date",
    "redemption", "spread_id", "effective_date", "termination_date", "tenor", "convention",
    "termination_convention", "rule", "end_of_month", "first_date", "next_to_last_date",
    "coupon_rate", "accrual_day_counter", "first_period_day_counter", "payment_convention",
    "payment_calendar", "maturity_date", "yield_day_counter", "yield_compounding",
    "yield_frequency")
COUPON_RATE_COLUMNS = ("bond_key", "k", "rate")
VAL_DATE_COLUMNS = ("t", "val_date")
CURVE_PARAM_COLUMNS = ("scen_id", "t", "curve_type", "day_counter", "compounding", "frequency",
                       "extrapolate", "flat_rate", "spread_compounding", "spread_frequency")
CURVE_NODE_COLUMNS = ("scen_id", "t", "node", "date", "tenor", "rate")
SPREAD_COLUMNS = ("scen_id", "t", "spread_id", "spread")
PRICE_COLUMNS = ("scen_id", "t", "bond_key", "price", "price_type")
YIELD_COLUMNS = ("scen_id", "t", "bond_key", "yield")


# ----------------------------------------------------------------------------- dates

def parse_iso(s):
    return datetime.date.fromisoformat(s)


def iso(d):
    return d.isoformat()


def month_end(d):
    nxt = datetime.date(d.year + (d.month == 12), d.month % 12 + 1, 1)
    return nxt - datetime.timedelta(days=1)


def add_months(d, n):
    """``Date + n*Months`` without a calendar: the day is capped at the month's length."""
    k = d.year * 12 + (d.month - 1) + n
    y, m = divmod(k, 12)
    first = datetime.date(y, m + 1, 1)
    return datetime.date(y, m + 1, min(d.day, month_end(first).day))


def add_tenor(d, tenor):
    """``Date + Period(tenor)`` without a calendar, for tenors ``<n><D|W|M|Y>``."""
    n, unit = int(tenor[:-1]), tenor[-1].upper()
    if unit == "D":
        return d + datetime.timedelta(days=n)
    if unit == "W":
        return d + datetime.timedelta(days=7 * n)
    if unit == "M":
        return add_months(d, n)
    return add_months(d, 12 * n)


def tenor_years(tenor):
    n, unit = int(tenor[:-1]), tenor[-1].upper()
    return n * {"D": 1 / 365, "W": 7 / 365, "M": 1 / 12, "Y": 1.0}[unit]


def fmt_rate(x):
    return f"{x:.6f}".rstrip("0").rstrip(".") if x != 0 else "0"


# ----------------------------------------------------------------------------- random bonds

class Picker:
    """Thin wrapper over ``numpy.random.Generator`` returning plain Python values."""

    def __init__(self, seed):
        self.rng = np.random.default_rng(seed)

    def u(self):
        return float(self.rng.random())

    def int(self, lo, hi):
        """Uniform integer in ``[lo, hi]``."""
        return int(self.rng.integers(lo, hi + 1))

    def choice(self, seq, p=None):
        return seq[int(self.rng.choice(len(seq), p=p))]

    def date(self, lo, hi):
        lo, hi = parse_iso(lo), parse_iso(hi)
        return lo + datetime.timedelta(days=self.int(0, (hi - lo).days))


def random_bond(pk, key):
    """One random v1 bond row (dict of strings) and its coupon-rate vector (empty for a scalar)."""
    row = dict.fromkeys(BOND_COLUMNS, "")
    row["bond_key"] = key
    row["face_amount"] = pk.choice(("100", "1000", "1000000"), p=(0.7, 0.2, 0.1))
    row["settlement_days"] = str(pk.int(0, 3))
    row["calendar"] = pk.choice(CALENDARS)
    row["spread_id"] = pk.choice(SPREAD_IDS) if pk.u() < 0.7 else ""
    if pk.u() < 0.1:
        row["redemption"] = pk.choice(("99.5", "101", "102.5"))
    elif pk.u() < 0.2:
        row["redemption"] = "100"
    if pk.u() < 0.3:
        row["yield_day_counter"] = pk.choice(DAY_COUNTERS)
        row["yield_compounding"] = pk.choice(COMPOUNDINGS)
        if pk.u() < 0.8:
            row["yield_frequency"] = pk.choice(QUOTE_FREQUENCIES)
    vec = []
    if pk.u() < 0.2:
        row["bond_type"] = "ZeroCoupon"
        issue = pk.date("2000-01-01", "2030-12-31")
        years = pk.int(1, 30)
        maturity = add_months(issue, 12 * years + (pk.int(1, 11) if pk.u() < 0.3 else 0))
        row["maturity_date"] = iso(maturity)
        row["issue_date"] = iso(issue) if pk.u() < 0.9 else ""
        row["payment_convention"] = pk.choice(BDCS) if pk.u() < 0.7 else ""
        return row, vec

    row["bond_type"] = "FixedRate"
    tenor = pk.choice(("1M", "3M", "6M", "1Y", "0D"), p=(0.1, 0.25, 0.4, 0.2, 0.05))
    years = pk.int(1, 3) if tenor == "0D" else pk.int(1, 30)
    eff = pk.date("2000-01-01", "2030-12-31")
    eom = 0
    if tenor != "0D" and pk.u() < 0.2:
        eom = 1
        if pk.u() < 0.7:
            eff = month_end(eff)
    term = add_months(eff, 12 * years + (pk.int(1, 11) if pk.u() < 0.3 else 0))
    if eom and eff == month_end(eff):
        term = month_end(term)
    row["tenor"] = tenor
    row["effective_date"] = iso(eff)
    row["termination_date"] = iso(term)
    row["end_of_month"] = str(eom) if pk.u() < 0.8 or eom else ""
    row["convention"] = pk.choice(BDCS, p=(0.25, 0.25, 0.05, 0.05, 0.3, 0.05, 0.05))
    row["termination_convention"] = pk.choice(BDCS) if pk.u() < 0.5 else ""
    row["rule"] = "Backward" if pk.u() < 0.5 else ""
    if tenor in ("3M", "6M", "1Y") and years >= 5:
        tm = int(tenor[:-1]) * (12 if tenor.endswith("Y") else 1)
        if pk.u() < 0.1:
            row["first_date"] = iso(add_months(eff, pk.int(1, 2 * tm - 1)))
        if pk.u() < 0.1:
            row["next_to_last_date"] = iso(add_months(term, -pk.int(1, 2 * tm - 1)))
    r = pk.u()
    if r < 0.7:
        row["issue_date"] = iso(eff)
    elif r < 0.8:
        row["issue_date"] = iso(eff - datetime.timedelta(days=pk.int(1, 10)))
    if pk.u() < 0.1:
        r0 = 0.005 + 0.045 * pk.u()
        vec = [round(r0 + 0.0025 * k, 6) for k in range(pk.int(2, 6))]
    else:
        row["coupon_rate"] = fmt_rate(0.00125 * pk.int(0, 64))
    row["accrual_day_counter"] = pk.choice(DAY_COUNTERS)
    if pk.u() < 0.1:
        row["first_period_day_counter"] = pk.choice(DAY_COUNTERS)
    row["payment_convention"] = pk.choice(BDCS) if pk.u() < 0.7 else ""
    if pk.u() < 0.1:
        row["payment_calendar"] = pk.choice(CALENDARS)
    return row, vec


def random_bonds(pk, n_bonds):
    bonds, coupon_rows = [], []
    for i in range(n_bonds):
        key = f"B{i + 1:06d}"
        row, vec = random_bond(pk, key)
        bonds.append(row)
        for k, rate in enumerate(vec):
            coupon_rows.append({"bond_key": key, "k": str(k), "rate": fmt_rate(rate)})
    return bonds, coupon_rows


# ----------------------------------------------------------------------------- random scenarios

def valuation_dates(base, n_times, step):
    b = parse_iso(base)
    n, unit = int(step[:-1]), step[-1].upper()
    out = []
    for t in range(n_times):
        if unit in ("M", "Y"):
            out.append(add_months(b, t * n * (12 if unit == "Y" else 1)))
        else:
            out.append(add_tenor(b, f"{t * n}{unit}"))
    return out


def random_scenarios(pk, n_scen, vdates):
    """curve_params, curve_nodes and spreads rows for S scenarios over the valuation dates."""
    params, nodes, spreads = [], [], []
    for s in range(1, n_scen + 1):
        level0 = 0.005 + 0.035 * pk.u()
        for t, v in enumerate(vdates):
            level = max(0.0005, level0 + 0.002 * t / 12 * (pk.u() - 0.5) + 0.002 * (pk.u() - 0.5))
            p = dict.fromkeys(CURVE_PARAM_COLUMNS, "")
            p["scen_id"], p["t"] = str(s), str(t)
            p["curve_type"] = "ZeroCurve" if pk.u() < 0.7 else "FlatForward"
            p["day_counter"] = "Actual365Fixed" if pk.u() < 0.7 else pk.choice(DAY_COUNTERS)
            p["compounding"] = "Continuous" if pk.u() < 0.6 else pk.choice(COMPOUNDINGS)
            p["frequency"] = pk.choice(QUOTE_FREQUENCIES[:3]) if pk.u() < 0.7 else ""
            p["extrapolate"] = str(pk.int(0, 1))
            if pk.u() < 0.3:
                p["spread_compounding"] = pk.choice(COMPOUNDINGS)
                p["spread_frequency"] = pk.choice(QUOTE_FREQUENCIES)
            if p["curve_type"] == "FlatForward":
                p["flat_rate"] = fmt_rate(round(level, 6))
            else:
                by_date = pk.u() < 0.5
                for k, tenor in enumerate(CURVE_TENORS):
                    yrs = tenor_years(tenor)
                    rate = level + 0.02 * (1.0 - np.exp(-yrs / 7.0)) + 0.0005 * (pk.u() - 0.5)
                    nodes.append({"scen_id": str(s), "t": str(t), "node": str(k),
                                  "date": iso(add_tenor(v, tenor)) if by_date else "",
                                  "tenor": "" if by_date else tenor,
                                  "rate": fmt_rate(round(float(rate), 6))})
            params.append(p)
            for sid, base in zip(SPREAD_IDS, SPREAD_BASE):
                spreads.append({"scen_id": str(s), "t": str(t), "spread_id": sid,
                                "spread": fmt_rate(round(base * (0.8 + 0.4 * pk.u()), 6))})
    return params, nodes, spreads


def generate(n_bonds, n_scen, n_times, seed, base="2015-09-16", step="1M"):
    """All tables of a random input set, as {file name: (columns, rows)}."""
    pk = Picker(seed)
    bonds, coupon_rows = random_bonds(pk, n_bonds)
    vdates = valuation_dates(base, n_times, step)
    params, nodes, spreads = random_scenarios(pk, n_scen, vdates)
    return {
        "bonds.csv": (BOND_COLUMNS, bonds),
        "coupon_rates.csv": (COUPON_RATE_COLUMNS, coupon_rows),
        "valuation_dates.csv": (VAL_DATE_COLUMNS,
                                [{"t": str(t), "val_date": iso(v)} for t, v in enumerate(vdates)]),
        "curve_params.csv": (CURVE_PARAM_COLUMNS, params),
        "curve_nodes.csv": (CURVE_NODE_COLUMNS, nodes),
        "spreads.csv": (SPREAD_COLUMNS, spreads),
    }


# ----------------------------------------------------------------------------- coverage set

def coverage():
    """The deterministic coverage-complete input set (see the module docstring)."""
    def bond(key, **kw):
        row = dict.fromkeys(BOND_COLUMNS, "")
        row["bond_key"] = key
        row.update(kw)
        return row

    frb = dict(bond_type="FixedRate", face_amount="100")
    zcb = dict(bond_type="ZeroCoupon", face_amount="100")
    bonds = [
        bond("C01_HEADLINE", **frb, settlement_days="3", calendar="TARGET", issue_date="2015-09-15",
             effective_date="2015-09-15", termination_date="2025-09-15", tenor="6M", convention="Unadjusted",
             termination_convention="Unadjusted", rule="Backward", end_of_month="0", coupon_rate="0.04",
             accrual_day_counter="Thirty360.BondBasis", payment_convention="Following"),
        bond("C02_USSET_ACT360_Q", **frb, settlement_days="2", calendar="UnitedStates.Settlement",
             issue_date="2014-03-20", spread_id="SP1", effective_date="2014-03-20", termination_date="2021-03-20",
             tenor="3M", convention="ModifiedFollowing", termination_convention="ModifiedFollowing",
             coupon_rate="0.025", accrual_day_counter="Actual360", payment_convention="ModifiedFollowing",
             yield_compounding="Simple"),
        bond("C03_USGOV_30360USA_EOM", **frb, settlement_days="1", calendar="UnitedStates.GovernmentBond",
             issue_date="2013-02-28", effective_date="2013-02-28", termination_date="2023-02-28", tenor="6M",
             convention="Following", termination_convention="Unadjusted", end_of_month="1",
             coupon_rate="0.0275", accrual_day_counter="Thirty360.USA", payment_convention="Following",
             yield_compounding="Continuous"),
        bond("C04_NULL_A365F_SHORTFIRST", **frb, settlement_days="0", calendar="NullCalendar",
             issue_date="2015-03-10", spread_id="SP2", effective_date="2015-03-10", termination_date="2024-06-30",
             tenor="1Y", convention="Unadjusted", first_date="2015-06-30", coupon_rate="0.03",
             accrual_day_counter="Actual365Fixed", payment_convention="Unadjusted",
             yield_day_counter="Actual360", yield_compounding="SimpleThenCompounded",
             yield_frequency="Semiannual"),
        bond("C05_TARGET_30360EU_LONGLAST", **frb, settlement_days="2", calendar="TARGET",
             issue_date="2015-05-20", redemption="100", spread_id="SP1", effective_date="2015-05-20",
             termination_date="2025-11-20", tenor="1Y", convention="Preceding", next_to_last_date="2024-05-20",
             coupon_rate="0.015", accrual_day_counter="Thirty360.European", payment_convention="Preceding",
             yield_compounding="CompoundedThenSimple", yield_frequency="Quarterly"),
        bond("C06_TARGET_ISMA_STEPUP", **frb, settlement_days="2", calendar="TARGET", issue_date="2014-06-16",
             spread_id="SP2", effective_date="2014-06-16", termination_date="2024-06-17", tenor="1Y",
             convention="ModifiedPreceding", accrual_day_counter="Thirty360.ISMA",
             first_period_day_counter="Actual360", payment_convention="ModifiedPreceding",
             yield_day_counter="Thirty360.EurobondBasis", yield_compounding="Compounded",
             yield_frequency="Annual"),
        bond("C07_TARGET_EUROBOND_EOM_USPAY", **frb, settlement_days="3", calendar="TARGET",
             issue_date="2015-08-31", spread_id="SP1", effective_date="2015-08-31", termination_date="2020-08-31",
             tenor="3M", convention="HalfMonthModifiedFollowing", end_of_month="1", coupon_rate="0.02",
             accrual_day_counter="Thirty360.EurobondBasis", payment_convention="HalfMonthModifiedFollowing",
             payment_calendar="UnitedStates.Settlement"),
        bond("C08_USSET_A365F_1M", **frb, settlement_days="0", calendar="UnitedStates.Settlement",
             issue_date="2015-07-15", effective_date="2015-07-15", termination_date="2018-07-15", tenor="1M",
             convention="Nearest", coupon_rate="0.01", accrual_day_counter="Actual365Fixed",
             payment_convention="Nearest", payment_calendar="NullCalendar"),
        bond("C09_USSET_ONE_PERIOD_0D", **frb, settlement_days="2", calendar="UnitedStates.Settlement",
             issue_date="2015-06-01", effective_date="2015-06-01", termination_date="2017-06-01", tenor="0D",
             convention="Following", coupon_rate="0.012", accrual_day_counter="Actual360",
             payment_convention="ModifiedFollowing"),
        bond("C10_FORWARD_START", **frb, settlement_days="3", calendar="TARGET", issue_date="2016-06-15",
             spread_id="SP1", effective_date="2016-06-15", termination_date="2026-06-15", tenor="6M",
             convention="ModifiedFollowing", coupon_rate="0.0225", accrual_day_counter="Thirty360.BondBasis",
             payment_convention="Following", payment_calendar="TARGET"),
        bond("C11_MATURES_BEFORE_T2", **dict(frb, face_amount="1000"), settlement_days="1",
             calendar="UnitedStates.GovernmentBond", issue_date="2013-05-15", effective_date="2013-05-15",
             termination_date="2016-05-15", tenor="6M", convention="Following", coupon_rate="0.0175",
             accrual_day_counter="Thirty360.USA", payment_convention="Following",
             payment_calendar="UnitedStates.GovernmentBond"),
        bond("C12_ZCB_TARGET_10Y", **zcb, settlement_days="3", calendar="TARGET", issue_date="2015-09-16",
             redemption="100", payment_convention="Following", maturity_date="2025-09-16",
             yield_day_counter="Actual365Fixed", yield_compounding="Compounded", yield_frequency="Annual"),
        bond("C13_ZCB_USGOV_SPREAD", **dict(zcb, face_amount="1000000"), settlement_days="1",
             calendar="UnitedStates.GovernmentBond", issue_date="2014-11-28", spread_id="SP2",
             payment_convention="ModifiedFollowing", maturity_date="2021-11-30"),
        bond("C14_ZCB_NULL_MATURED", **zcb, settlement_days="0", calendar="NullCalendar",
             issue_date="2013-01-02", payment_convention="Unadjusted", maturity_date="2016-08-31"),
        bond("C15_ZCB_USSET_PRECEDING", **zcb, settlement_days="2", calendar="UnitedStates.Settlement",
             redemption="101", payment_convention="Preceding", maturity_date="2019-12-31",
             yield_compounding="Simple"),
        bond("C16_USGOV_SHORTFIRST_LONGLAST", **frb, settlement_days="2", calendar="UnitedStates.GovernmentBond",
             issue_date="2015-01-20", spread_id="SP1", effective_date="2015-01-20", termination_date="2027-08-15",
             tenor="6M", convention="ModifiedFollowing", first_date="2015-05-15",
             next_to_last_date="2026-11-15", coupon_rate="0.0325", accrual_day_counter="Thirty360.USA",
             payment_convention="ModifiedFollowing"),
        bond("C17_NULL_2W", **frb, settlement_days="1", calendar="NullCalendar", issue_date="2016-01-04",
             effective_date="2016-01-04", termination_date="2016-12-19", tenor="2W", convention="Following",
             coupon_rate="0.005", accrual_day_counter="Actual360", payment_convention="Following",
             yield_compounding="Compounded", yield_frequency="Monthly"),
    ]
    coupon_rows = [{"bond_key": "C06_TARGET_ISMA_STEPUP", "k": str(k), "rate": r}
                   for k, r in enumerate(("0.01", "0.0125", "0.015", "0.0175", "0.02", "0.025"))]
    vdates = ["2015-09-16", "2016-03-16", "2016-09-16", "2017-09-18"]

    def cp(s, t, ctype, dc, comp, freq, extrap, flat="", sp_comp="", sp_freq=""):
        return dict(zip(CURVE_PARAM_COLUMNS, (str(s), str(t), ctype, dc, comp, freq, str(extrap), flat,
                                              sp_comp, sp_freq)))

    params = [
        cp(1, 0, "FlatForward", "Actual365Fixed", "Continuous", "Annual", 0, "0.03"),
        cp(1, 1, "ZeroCurve", "Actual360", "Simple", "", 0, "", "Compounded", "Annual"),
        cp(1, 2, "ZeroCurve", "Thirty360.BondBasis", "Compounded", "Semiannual", 1, "",
           "SimpleThenCompounded", "Quarterly"),
        cp(1, 3, "FlatForward", "Thirty360.USA", "SimpleThenCompounded", "Annual", 0, "0.0325",
           "CompoundedThenSimple", "Semiannual"),
        cp(2, 0, "ZeroCurve", "Actual365Fixed", "Continuous", "Annual", 0, "", "Simple", ""),
        cp(2, 1, "FlatForward", "Actual360", "CompoundedThenSimple", "Quarterly", 1, "0.0275",
           "Continuous", ""),
        cp(2, 2, "ZeroCurve", "Thirty360.European", "SimpleThenCompounded", "Annual", 1, "",
           "Compounded", "Monthly"),
        cp(2, 3, "ZeroCurve", "Actual365Fixed", "CompoundedThenSimple", "Semiannual", 0),
    ]
    long_tenors = ("0D", "3M", "6M", "1Y", "2Y", "3Y", "5Y", "7Y", "10Y", "15Y", "20Y", "30Y", "40Y")
    short_tenors = ("0D", "6M", "1Y", "2Y", "3Y")
    nodes = []

    def add_nodes(s, t, tenors, by_date, base, slope):
        v = parse_iso(vdates[t])
        for k, tenor in enumerate(tenors):
            rate = base + slope * (1.0 - np.exp(-tenor_years(tenor) / 7.0))
            nodes.append({"scen_id": str(s), "t": str(t), "node": str(k),
                          "date": iso(add_tenor(v, tenor)) if by_date else "",
                          "tenor": "" if by_date else tenor, "rate": fmt_rate(round(float(rate), 6))})

    add_nodes(1, 1, long_tenors, False, 0.004, 0.026)
    add_nodes(1, 2, short_tenors, True, 0.006, 0.02)
    add_nodes(2, 0, long_tenors, True, 0.005, 0.025)
    add_nodes(2, 2, short_tenors, False, 0.003, 0.018)
    add_nodes(2, 3, long_tenors, False, 0.008, 0.024)
    spreads = []
    for s in (1, 2):
        for t in range(4):
            spreads.append({"scen_id": str(s), "t": str(t), "spread_id": "SP1",
                            "spread": fmt_rate(0.0075 + 0.0005 * t + 0.001 * (s - 1))})
            spreads.append({"scen_id": str(s), "t": str(t), "spread_id": "SP2",
                            "spread": fmt_rate(0.02 + 0.001 * t + 0.0025 * (s - 1))})
    prices = [
        dict(scen_id="1", t="0", bond_key="C01_HEADLINE", price="107.5", price_type="Clean"),
        dict(scen_id="1", t="0", bond_key="C12_ZCB_TARGET_10Y", price="72.0", price_type=""),
        dict(scen_id="1", t="1", bond_key="C02_USSET_ACT360_Q", price="101.0", price_type="Dirty"),
        dict(scen_id="1", t="2", bond_key="C16_USGOV_SHORTFIRST_LONGLAST", price="104.0", price_type="Clean"),
        dict(scen_id="1", t="3", bond_key="C10_FORWARD_START", price="99.0", price_type="Clean"),
        dict(scen_id="2", t="0", bond_key="C05_TARGET_30360EU_LONGLAST", price="96.5", price_type="Dirty"),
        dict(scen_id="2", t="1", bond_key="C13_ZCB_USGOV_SPREAD", price="85.0", price_type="Clean"),
        dict(scen_id="2", t="2", bond_key="C04_NULL_A365F_SHORTFIRST", price="101.5", price_type="Clean"),
        dict(scen_id="2", t="3", bond_key="C06_TARGET_ISMA_STEPUP", price="100.25", price_type="Dirty"),
    ]
    yields = [
        dict(scen_id="1", t="0", bond_key="C01_HEADLINE", **{"yield": "0.0305"}),
        dict(scen_id="1", t="2", bond_key="C04_NULL_A365F_SHORTFIRST", **{"yield": "0.028"}),
        dict(scen_id="2", t="1", bond_key="C12_ZCB_TARGET_10Y", **{"yield": "0.026"}),
        dict(scen_id="2", t="3", bond_key="C17_NULL_2W", **{"yield": "0.004"}),
    ]
    return {
        "bonds.csv": (BOND_COLUMNS, bonds),
        "coupon_rates.csv": (COUPON_RATE_COLUMNS, coupon_rows),
        "valuation_dates.csv": (VAL_DATE_COLUMNS,
                                [{"t": str(t), "val_date": v} for t, v in enumerate(vdates)]),
        "curve_params.csv": (CURVE_PARAM_COLUMNS, params),
        "curve_nodes.csv": (CURVE_NODE_COLUMNS, nodes),
        "spreads.csv": (SPREAD_COLUMNS, spreads),
        "prices.csv": (PRICE_COLUMNS, prices),
        "yields.csv": (YIELD_COLUMNS, yields),
    }


# ----------------------------------------------------------------------------- output

def write_tables(out, tables):
    out = pathlib.Path(out)
    out.mkdir(parents=True, exist_ok=True)
    for name, (columns, rows) in tables.items():
        with open(out / name, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f, lineterminator="\n")
            w.writerow(columns)
            for r in rows:
                w.writerow([r.get(c, "") for c in columns])


# ----------------------------------------------------------------------------- pureql validation

def import_pureql():
    """pureql, from ``PUREQL_SRC`` (default ``../quantlib-migration/src``); for --validate and tests only."""
    src = pathlib.Path(os.environ.get("PUREQL_SRC", ROOT.parent / "quantlib-migration" / "src"))
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))
    import pureql
    return pureql


def pureql_bond(row, coupon_rates=()):
    """The pureql FixedRateBond or ZeroCouponBond of a bonds.csv row (dict of strings), with the
    blank-cell defaults of inputs.md. ``coupon_rates`` is the coupon_rates.csv vector, if any."""
    ql = import_pureql()
    from pureql.time.calendars.target import TARGET
    from pureql.time.calendars.unitedstates import UnitedStates
    from pureql.time.daycounters.actual360 import Actual360
    from pureql.time.daycounters.thirty360 import Thirty360

    cals = {"NullCalendar": ql.NullCalendar, "TARGET": TARGET,
            "UnitedStates.Settlement": lambda: UnitedStates(UnitedStates.Settlement),
            "UnitedStates.GovernmentBond": lambda: UnitedStates(UnitedStates.GovernmentBond)}
    dcs = {"Actual360": Actual360, "Actual365Fixed": ql.Actual365Fixed,
           "Thirty360.USA": lambda: Thirty360(Thirty360.USA),
           "Thirty360.BondBasis": lambda: Thirty360(Thirty360.BondBasis),
           "Thirty360.ISMA": lambda: Thirty360(Thirty360.ISMA),
           "Thirty360.European": lambda: Thirty360(Thirty360.European),
           "Thirty360.EurobondBasis": lambda: Thirty360(Thirty360.EurobondBasis)}
    units = {"D": ql.TimeUnit.Days, "W": ql.TimeUnit.Weeks, "M": ql.TimeUnit.Months, "Y": ql.TimeUnit.Years}

    def date(s):
        if not s:
            return ql.Date()
        d = parse_iso(s)
        return ql.Date(d.day, ql.Month(d.month), d.year)

    def bdc(s, default="Following"):
        return getattr(ql.BusinessDayConvention, s or default)

    face = float(row["face_amount"])
    redemption = float(row["redemption"]) if row["redemption"] else 100.0
    nsd = int(row["settlement_days"])
    cal = cals[row["calendar"]]()
    if row["bond_type"] == "ZeroCoupon":
        return ql.ZeroCouponBond(nsd, cal, face, date(row["maturity_date"]), bdc(row["payment_convention"]),
                                 redemption, date(row["issue_date"]))
    tenor = row["tenor"] or "0D"
    conv = bdc(row["convention"])
    schedule = ql.Schedule(
        date(row["effective_date"]), date(row["termination_date"]),
        ql.Period(int(tenor[:-1]), units[tenor[-1].upper()]), cal, conv,
        bdc(row["termination_convention"], conv.name),
        getattr(ql.DateGeneration, row["rule"] or "Backward"),
        row["end_of_month"] in ("1", "true", "True", "TRUE"),
        date(row["first_date"]), date(row["next_to_last_date"]))
    rates = list(coupon_rates) if coupon_rates else [float(row["coupon_rate"])]
    return ql.FixedRateBond(
        nsd, face, schedule, rates, dcs[row["accrual_day_counter"]](), bdc(row["payment_convention"]),
        redemption, date(row["issue_date"]),
        cals[row["payment_calendar"]]() if row["payment_calendar"] else None,
        None, None, ql.BusinessDayConvention.Unadjusted, False,
        dcs[row["first_period_day_counter"]]() if row["first_period_day_counter"] else None)


def validate(tables):
    """Build every bond with pureql; raise ``ValueError`` naming the first that fails."""
    vecs = {}
    for r in tables["coupon_rates.csv"][1]:
        vecs.setdefault(r["bond_key"], []).append((int(r["k"]), float(r["rate"])))
    for row in tables["bonds.csv"][1]:
        rates = [x for _, x in sorted(vecs.get(row["bond_key"], []))]
        try:
            bond = pureql_bond(row, rates)
            bond.cashflows()
        except Exception as e:  # noqa: BLE001 - report any pureql failure with the row
            raise ValueError(f"bond {row['bond_key']} is not constructible by pureql: {e!r}\n{row}") from e
    return True


# ----------------------------------------------------------------------------- CLI

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--n-bonds", type=int, default=100)
    ap.add_argument("--n-scen", type=int, default=2)
    ap.add_argument("--n-times", type=int, default=13)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--base-date", default="2015-09-16", help="valuation date of t=0 (ISO)")
    ap.add_argument("--step", default="1M", help="valuation date step, e.g. 1M, 3M, 1Y")
    ap.add_argument("--out", required=True, help="output directory")
    ap.add_argument("--coverage", action="store_true",
                    help="write the deterministic coverage-complete set instead of a random one")
    ap.add_argument("--validate", action="store_true", help="build every bond with pureql (needs PUREQL_SRC)")
    args = ap.parse_args(argv)
    if args.coverage:
        tables = coverage()
    else:
        tables = generate(args.n_bonds, args.n_scen, args.n_times, args.seed, args.base_date, args.step)
    if args.validate:
        validate(tables)
    write_tables(args.out, tables)
    return 0


if __name__ == "__main__":
    sys.exit(main())
