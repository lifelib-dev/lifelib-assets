"""The edge grid at FUTURE valuation dates (plan Phase 3 exit, Verification L5): the model == pureql, bitwise.

One input set (:func:`write_edge_inputs`, written into ``tmp_path``): twelve
bonds and 25 valuation dates from 2015 to 2026, chosen so that every edge of
the plan's Phase 3 exit happens to some bond on some date:

* valuation dates ON coupon dates and on the next business day (the headline
  bond on 15/16-Sep-2020; a TARGET annual bond paid on 28-Dec-2020; a US
  GovernmentBond on 04-Jan-2021);
* a payment in (v, s]: the T+3 headline on Fri 11-Sep-2020 (coupon Tue 15,
  settlement Wed 16), a T+1 TARGET coupon due 25-Dec-2020 and paid Mon
  28-Dec on the settlement date of v = 24-Dec, a US GovernmentBond coupon due
  Sun 04-Jul-2021 paid Tue 06-Jul (Mon 05 observed) inside (02-Jul, 08-Jul],
  a T+2 coupon on 16-Mar-2017;
* v before issue (forward start, ``s = issue``): a bond issued 15-Jun-2021
  valued from 2015 on, and a T+0 bond valued the day before its issue;
* maturity inside (v, s] (NPV > 0, notional(s) = 0 so prices 0.0): a TARGET
  T+2 zero maturing Mon 04-Jan-2021 valued Thu 31-Dec-2020; a US Settlement
  zero due on Thanksgiving 2021; the headline on 11-Sep-2025;
* maturity on v and v after maturity (expired: NPV 0.0);
* v on holidays and weekends: 25/26-Dec-2020, 01-Jan-2021, Sun 04-Jul-2021,
  Mon 05-Jul-2021 (US observed), Thanksgiving 2020 and 2021;
* T+0..3, TARGET, US GovernmentBond, US Settlement and NullCalendar bonds,
  zero-coupon bonds, bonds with and without a spread.

Five scenarios at every date: 1 FlatForward (Actual365Fixed, Continuous,
3.5%); 2 a ZeroCurve to 30Y (Continuous); 3 a ZeroCurve ending at 2Y with
extrapolation OFF (bonds that outlive it raise pureql's "time (...) is past
max curve time (...)", and so must the model); 4 the same curve with
extrapolation ON; 5 a Thirty360 ZeroCurve quoted SimpleThenCompounded. The
spread conventions are Compounded/Annual (1), Continuous (2), Simple (3, 4)
and SimpleThenCompounded/Quarterly (5).

Checks, all EXACT (floats bit for bit, NaN-aware; a pureql raise must be the
same ``ValueError`` message), the model against EACH pureql form
(explicit dates; Settings moved): every output at every (scen, t, bond) under
the default flags; the R x T x F flag matrix on the event dates; the named
edges' properties; and the T-override jump: with ``includeTodaysCashFlows``
= True, a T+0 bond (``s == v``) with a coupon on v counts the coupon in its
settlement value although the settlement role hard-codes "exclude
settlement-date flows" (``bond.cpp:280-283``, ``cashflow.cpp:35-41``), so the
dirty price jumps by the coupon (here 2.25). The plan's exploration measured
this jump as 98.0607 -> 100.3107 on a bond this suite could not recover; the
jump of 2.25 (the coupon of a 4.5% semiannual Thirty360 bond) is reproduced
on ``T0_CPN_ON_V`` instead and pinned in ``tests/data/future_edges.json``
(regenerate with ``python tests/future/test_future_edges.py``).
"""

import datetime
import itertools
import json
import pathlib
import sys

import pytest

if __name__ == "__main__":  # the regeneration entry point needs the tests directory on sys.path
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from helpers import pureql_val as pv  # noqa: E402
from helpers.model import MODEL_DIR  # noqa: E402
from helpers.pureql_ref import pq_calendar, pq_date  # noqa: E402

ROOT = MODEL_DIR.parents[1]
GOLDEN = ROOT / "tests" / "data" / "future_edges.json"


def fr(key, nsd, cal, eff, term, tenor, rate, dc, conv="Unadjusted", pay="Following", **kw):
    row = {"bond_key": key, "bond_type": "FixedRate", "face_amount": "100", "settlement_days": str(nsd),
           "calendar": cal, "issue_date": eff, "effective_date": eff, "termination_date": term, "tenor": tenor,
           "convention": conv, "coupon_rate": rate, "accrual_day_counter": dc, "payment_convention": pay}
    row.update(kw)
    return row


def zcb(key, nsd, cal, issue, maturity, pay, **kw):
    row = {"bond_key": key, "bond_type": "ZeroCoupon", "face_amount": "100", "settlement_days": str(nsd),
           "calendar": cal, "issue_date": issue, "maturity_date": maturity, "payment_convention": pay}
    row.update(kw)
    return row


US_GOV, US_SET = "UnitedStates.GovernmentBond", "UnitedStates.Settlement"
BONDS = [
    fr("HEADLINE", 3, "TARGET", "2015-09-15", "2025-09-15", "6M", "0.04", "Thirty360.BondBasis",
       termination_convention="Unadjusted"),
    fr("HEADLINE_SPRD", 3, "TARGET", "2015-09-15", "2025-09-15", "6M", "0.04", "Thirty360.BondBasis",
       termination_convention="Unadjusted", spread_id="S"),
    fr("T0_CPN_ON_V", 0, "TARGET", "2015-09-15", "2025-09-15", "6M", "0.045", "Thirty360.BondBasis",
       termination_convention="Unadjusted"),
    fr("TARGET_T2_Q_SPRD", 2, "TARGET", "2017-06-20", "2022-06-20", "3M", "0.015", "Thirty360.European",
       conv="ModifiedFollowing", pay="ModifiedFollowing", spread_id="S"),
    fr("TARGET_T1_XMAS", 1, "TARGET", "2016-12-25", "2023-12-25", "1Y", "0.025", "Actual360", conv="Following"),
    fr("USGOV_T1_EOM", 1, US_GOV, "2013-02-28", "2023-02-28", "6M", "0.0275", "Thirty360.USA", conv="Following",
       termination_convention="Unadjusted", end_of_month="1"),
    fr("USGOV_T3_JUL4", 3, US_GOV, "2016-01-04", "2024-07-04", "6M", "0.03", "Actual365Fixed", conv="Following"),
    zcb("USSET_ZCB_T2_SPRD", 2, US_SET, "2018-11-26", "2021-11-25", "ModifiedFollowing", spread_id="S"),
    fr("FWD_START", 2, "TARGET", "2021-06-15", "2026-06-15", "6M", "0.0225", "Thirty360.BondBasis",
       conv="ModifiedFollowing"),
    zcb("ZCB_NULL_T0", 0, "NullCalendar", "2015-12-25", "2020-12-25", "Unadjusted"),
    zcb("ZCB_TARGET_T2", 2, "TARGET", "2016-01-04", "2021-01-04", "Following"),
    fr("MATURED_2018", 2, "TARGET", "2015-03-16", "2018-03-16", "1Y", "0.01", "Actual365Fixed", conv="Following"),
]
VDATES = [
    "2015-09-14",  # 0  T0_CPN_ON_V the day before issue (s = issue); FWD_START before issue
    "2017-03-15",  # 1  MATURED_2018: coupon 16-Mar in (v, s = 17-Mar]
    "2020-09-11",  # 2  Fri: HEADLINE coupon Tue 15-Sep in (v, s = Wed 16-Sep]
    "2020-09-15",  # 3  HEADLINE coupon on v; T0_CPN_ON_V coupon on v == s (T-override)
    "2020-09-16",  # 4  the next business day
    "2020-11-26",  # 5  Thanksgiving 2020 (US holiday, TARGET business day)
    "2020-12-24",  # 6  TARGET_T1_XMAS: coupon due 25-Dec paid Mon 28-Dec == s
    "2020-12-25",  # 7  holiday (TARGET, US); ZCB_NULL_T0 matures on v
    "2020-12-26",  # 8  Saturday, TARGET holiday
    "2020-12-28",  # 9  TARGET_T1_XMAS pays on v
    "2020-12-31",  # 10 ZCB_TARGET_T2 matures Mon 04-Jan in (v, s = Tue 05-Jan]
    "2021-01-01",  # 11 New Year (TARGET, US)
    "2021-01-04",  # 12 ZCB_TARGET_T2 matures on v; USGOV_T3_JUL4 coupon on v
    "2021-01-05",  # 13 the next business day
    "2021-07-02",  # 14 USGOV_T3_JUL4: coupon paid Tue 06-Jul in (v, s = Thu 08-Jul]
    "2021-07-04",  # 15 Sunday, Independence Day
    "2021-07-05",  # 16 Monday, observed US holiday
    "2021-11-25",  # 17 Thanksgiving 2021: USSET_ZCB_T2_SPRD paid Fri 26-Nov in (v, s = Mon 29-Nov]
    "2021-11-26",  # 18 USSET_ZCB_T2_SPRD pays on v
    "2023-02-28",  # 19 USGOV_T1_EOM matures on v
    "2023-03-01",  # 20 USGOV_T1_EOM after maturity
    "2025-09-11",  # 21 HEADLINE maturity Mon 15-Sep in (v, s = Tue 16-Sep]
    "2025-09-15",  # 22 HEADLINE matures on v
    "2025-09-16",  # 23 HEADLINE after maturity
    "2026-06-16",  # 24 FWD_START after maturity: everything expired
]
T_OF = {v: t for t, v in enumerate(VDATES)}
#: The dates with an event for some bond (the flag matrix runs on these).
EVENT_DATES = ["2015-09-14", "2017-03-15", "2020-09-11", "2020-09-15", "2020-09-16", "2020-12-24", "2020-12-25",
               "2020-12-28", "2020-12-31", "2021-01-04", "2021-07-02", "2021-11-25", "2021-11-26", "2023-02-28",
               "2025-09-11", "2025-09-15"]

SCEN_FLAT, SCEN_ZERO, SCEN_SHORT, SCEN_SHORT_EXTRAP, SCEN_30360 = 1, 2, 3, 4, 5
SCENARIOS = {
    SCEN_FLAT: dict(curve_type="FlatForward", day_counter="Actual365Fixed", compounding="Continuous",
                    frequency="Annual", extrapolate="0", flat_rate="0.035", spread_compounding="Compounded",
                    spread_frequency="Annual"),
    SCEN_ZERO: dict(curve_type="ZeroCurve", day_counter="Actual365Fixed", compounding="Continuous",
                    frequency="Annual", extrapolate="0", spread_compounding="Continuous", spread_frequency=""),
    SCEN_SHORT: dict(curve_type="ZeroCurve", day_counter="Actual365Fixed", compounding="Compounded",
                     frequency="Annual", extrapolate="0", spread_compounding="Simple", spread_frequency=""),
    SCEN_SHORT_EXTRAP: dict(curve_type="ZeroCurve", day_counter="Actual365Fixed", compounding="Compounded",
                            frequency="Annual", extrapolate="1", spread_compounding="Simple", spread_frequency=""),
    SCEN_30360: dict(curve_type="ZeroCurve", day_counter="Thirty360.BondBasis", compounding="SimpleThenCompounded",
                     frequency="Semiannual", extrapolate="1", spread_compounding="SimpleThenCompounded",
                     spread_frequency="Quarterly"),
}
NODES = {
    SCEN_ZERO: (("0D", "0.01"), ("1Y", "0.015"), ("3Y", "0.022"), ("10Y", "0.03"), ("30Y", "0.032")),
    SCEN_SHORT: (("0D", "0.01"), ("6M", "0.012"), ("2Y", "0.016")),
    SCEN_SHORT_EXTRAP: (("0D", "0.01"), ("6M", "0.012"), ("2Y", "0.016")),
    SCEN_30360: (("0D", "0.008"), ("3M", "0.009"), ("1Y", "0.0125"), ("5Y", "0.02"), ("30Y", "0.028")),
}
#: z-spreads for the ``*_from_z`` prices.
Z_EDGE = (-0.0125, 0.0, 0.01)
FLAGS = list(itertools.product((0, 1), (-1, 0, 1), (-1, 0, 1)))


def write_edge_inputs(out):
    params, nodes, spreads = [], [], []
    for s, conv in SCENARIOS.items():
        for t in range(len(VDATES)):
            params.append({"scen_id": str(s), "t": str(t), **conv})
            for k, (tenor, rate) in enumerate(NODES.get(s, ())):
                nodes.append({"scen_id": str(s), "t": str(t), "node": str(k), "tenor": tenor, "rate": rate})
            spreads.append({"scen_id": str(s), "t": str(t), "spread_id": "S", "spread": f"{0.01 + 0.0002 * t:.4f}"})
    return pv.write_inputs(out, BONDS, VDATES, params, nodes, spreads)


@pytest.fixture(scope="module")
def edge_inputs(tmp_path_factory):
    return write_edge_inputs(tmp_path_factory.mktemp("future_edges"))


@pytest.fixture(scope="module")
def m(set_model, edge_inputs):
    return set_model("edges", edge_inputs)


def iso(d):
    return (datetime.date(1899, 12, 30) + datetime.timedelta(days=int(d))).isoformat()


def serial_of(s):
    return (datetime.date.fromisoformat(s) - datetime.date(1899, 12, 30)).days


def bix(m, key):
    return list(m.Data.bond_keys()).index(key)


def leg_dates(m, b):
    lo, hi = int(m.Legs.cf_lo_arr()[b]), int(m.Legs.cf_lo_arr()[b + 1])
    return [int(d) for d in m.Legs.cf_date_arr().tolist()[lo:hi]]


def compare(m, points, bonds=None, zs=Z_EDGE, flag_values=None):
    bad = []
    for s, t in points:
        item = m.Valuation[s, t]
        c = pv.curve_inputs(m, s, t)
        for b in range(m.Data.n_bonds()) if bonds is None else bonds:
            got, _ = pv.two_form_mismatches(m, item, s, t, b, zs, flag_values=flag_values, c=c,
                                            ctx=f"({s}, {VDATES[t]}) {m.Data.bond_keys()[b]}")
            bad += got
    return bad


# --------------------------------------------------------------------------- the grid has its edges
def test_edge_grid_hits_the_edges(m):
    """Every edge of the plan happens on the grid (pureql explicit form, no model Cells)."""
    def x(key, vdate, s=SCEN_FLAT):
        return pv.pq_values_explicit(m, s, T_OF[vdate], bix(m, key))["bond"]

    def flows_in(key, lo, hi):
        return [d for d in leg_dates(m, bix(m, key)) if lo < d <= hi]

    checks = []
    # payment in (v, s]
    for key, vd in (("HEADLINE", "2020-09-11"), ("MATURED_2018", "2017-03-15"), ("TARGET_T1_XMAS", "2020-12-24"),
                    ("USGOV_T3_JUL4", "2021-07-02"), ("ZCB_TARGET_T2", "2020-12-31"),
                    ("USSET_ZCB_T2_SPRD", "2021-11-25"), ("HEADLINE", "2025-09-11")):
        r = x(key, vd)
        checks.append((f"{key} {vd}: a flow in (v, s]", bool(flows_in(key, serial_of(vd), r["settle"][1]))))
    s_xmas = x("TARGET_T1_XMAS", "2020-12-24")["settle"][1]
    checks.append(("TARGET_T1_XMAS 2020-12-24: the flow is ON s",
                   flows_in("TARGET_T1_XMAS", serial_of("2020-12-24"), s_xmas) == [s_xmas]))
    # flows on v
    for key, vd in (("HEADLINE", "2020-09-15"), ("T0_CPN_ON_V", "2020-09-15"), ("TARGET_T1_XMAS", "2020-12-28"),
                    ("USGOV_T3_JUL4", "2021-01-04"), ("ZCB_NULL_T0", "2020-12-25"), ("ZCB_TARGET_T2", "2021-01-04"),
                    ("USSET_ZCB_T2_SPRD", "2021-11-26"), ("USGOV_T1_EOM", "2023-02-28"), ("HEADLINE", "2025-09-15")):
        checks.append((f"{key} {vd}: a flow on v", serial_of(vd) in leg_dates(m, bix(m, key))))
    checks.append(("T0_CPN_ON_V 2020-09-15: s == v",
                   x("T0_CPN_ON_V", "2020-09-15")["settle"][1] == serial_of("2020-09-15")))
    # maturity in (v, s]: alive, not tradable
    for key, vd in (("ZCB_TARGET_T2", "2020-12-31"), ("USSET_ZCB_T2_SPRD", "2021-11-25"), ("HEADLINE", "2025-09-11")):
        r = x(key, vd)
        checks.append((f"{key} {vd}: maturity in (v, s]", not r["is_expired"][1] and not r["is_tradable"][1]
                       and r["npv"][1] > 0.0))
    # expired: matures on v, and after
    for key, vd in (("ZCB_NULL_T0", "2020-12-25"), ("ZCB_TARGET_T2", "2021-01-04"), ("USGOV_T1_EOM", "2023-02-28"),
                    ("USGOV_T1_EOM", "2023-03-01"), ("HEADLINE", "2025-09-15"), ("HEADLINE", "2025-09-16"),
                    ("MATURED_2018", "2020-09-16"), ("FWD_START", "2026-06-16")):
        checks.append((f"{key} {vd}: expired", x(key, vd)["is_expired"][1]))
    # before issue: s = issue
    for key, vd in (("T0_CPN_ON_V", "2015-09-14"), ("FWD_START", "2015-09-14"), ("FWD_START", "2021-01-04")):
        issue = int(m.Legs.bk_issue_arr()[bix(m, key)])
        checks.append((f"{key} {vd}: s == issue > v", x(key, vd)["settle"][1] == issue > serial_of(vd)))
    # holidays and weekends move the settlement of a T+0 / T+n bond
    for key, vd, cal in (("T0_CPN_ON_V", "2020-12-25", 1), ("T0_CPN_ON_V", "2020-12-26", 1),
                         ("T0_CPN_ON_V", "2021-01-01", 1), ("USGOV_T3_JUL4", "2021-07-05", 3),
                         ("USGOV_T3_JUL4", "2021-07-04", 3), ("USGOV_T1_EOM", "2020-11-26", 3)):
        checks.append((f"{vd} is not a business day of {key}'s calendar",
                       not pq_calendar(cal).isBusinessDay(pq_date(serial_of(vd)))))
    checks.append(("T0_CPN_ON_V on 2020-12-25: s = Mon 28-Dec", iso(x("T0_CPN_ON_V", "2020-12-25")["settle"][1])
                   == "2020-12-28"))
    # extrapolation off: some bond-points raise "past max curve time"; on: none raise
    short = [pv.pq_values_explicit(m, SCEN_SHORT, t, b)["bond"]["npv"] for t in range(len(VDATES))
             for b in range(m.Data.n_bonds())]
    checks.append(("scenario 3 raises 'past max curve time'",
                   any(o[0] == "err" and "is past max curve time" in o[2] for o in short)))
    checks.append(("scenario 3 also has values", any(o[0] == "ok" for o in short)))
    longer = [pv.pq_values_explicit(m, SCEN_SHORT_EXTRAP, t, b)["bond"]["npv"] for t in range(len(VDATES))
              for b in range(m.Data.n_bonds())]
    checks.append(("scenario 4 raises nothing", all(o[0] == "ok" for o in longer)))
    failed = [name for name, ok in checks if not ok]
    assert not failed, "edges missing from the grid: " + "; ".join(failed)


def test_scenario_conventions(m):
    """The five scenarios carry the documented curve and spread conventions."""
    want = {SCEN_FLAT: (1, 2, 2, 1, 1), SCEN_ZERO: (0, 2, 2, 2, -1), SCEN_SHORT: (0, 2, 1, 0, -1),
            SCEN_SHORT_EXTRAP: (0, 2, 1, 0, -1), SCEN_30360: (0, 11, 3, 3, 4)}
    for s, w in want.items():
        for t in range(len(VDATES)):
            c = pv.curve_inputs(m, s, t)
            assert (c["type"], c["dc"], c["comp"], c["sp_comp"], c["sp_freq"]) == w, (s, t)
            assert c["extrap"] == (1 if s in (SCEN_SHORT_EXTRAP, SCEN_30360) else 0)


# --------------------------------------------------------------------------- the whole grid, default flags
@pytest.mark.parametrize("scen_id", list(SCENARIOS))
def test_every_bond_point(m, scen_id):
    """Every output of every bond at every date: model == pureql explicit AND == pureql Settings-moved."""
    bad = compare(m, [(scen_id, t) for t in range(len(VDATES))])
    pv.report_mismatches(bad, f"edge grid scenario {scen_id}")


@pytest.mark.parametrize("scen_id", [SCEN_FLAT, SCEN_ZERO])
def test_portfolio_aggregates(m, scen_id):
    """``npv_total`` / ``sv_total`` / ``n_expired`` / ``n_tradable`` at every date (sequential sums, bitwise)."""
    bad = []
    for t in range(len(VDATES)):
        item = m.Valuation[scen_id, t]
        vals = [pv.pq_values_explicit(m, scen_id, t, b)["bond"] for b in range(m.Data.n_bonds())]
        for cell, key in (("npv_total", "npv"), ("sv_total", "settlement_value"), ("mv_total", "market_value"),
                          ("accrued_total", "accrued_cash")):
            total = 0.0
            for r in vals:
                total += r[key][1]
            g = pv.run_model(pv.model_cells(item, cell))
            if not pv.same_outcome(g, ("ok", total)):
                bad.append(f"({scen_id}, {VDATES[t]}) {cell}: model {pv.show(g)} vs pureql {total!r}")
        for cell, key in (("n_expired", "is_expired"), ("n_tradable", "is_tradable")):
            e = ("ok", sum(1 for r in vals if r[key][1]))
            g = pv.run_model(pv.model_cells(item, cell))
            if not pv.same_outcome(g, e):
                bad.append(f"({scen_id}, {VDATES[t]}) {cell}: model {pv.show(g)} vs pureql {pv.show(e)}")
    pv.report_mismatches(bad, f"aggregates scenario {scen_id}")


# --------------------------------------------------------------------------- the named edges, on the model
def test_named_edges_on_the_model(m):
    """The edges' defining properties, read from the model (each value is also == pureql above)."""
    def cell(name, key, vd, *args, s=SCEN_FLAT):
        return pv.model_cells(m.Valuation[s, T_OF[vd]], name)(bix(m, key), *args)

    # a payment in (v, s]: in the NPV, not in the settlement value / prices
    for key, vd in (("HEADLINE", "2020-09-11"), ("TARGET_T1_XMAS", "2020-12-24"), ("USGOV_T3_JUL4", "2021-07-02"),
                    ("MATURED_2018", "2017-03-15"), ("HEADLINE_SPRD", "2020-09-11")):
        assert cell("first_live", key, vd, pv.ROLE_ENGINE) < cell("first_live", key, vd, pv.ROLE_SETTLE), (key, vd)
        assert cell("npv", key, vd) > cell("settlement_value", key, vd) * 0.9 > 0.0
    # maturity in (v, s]: NPV > 0, every price 0.0, not expired, not tradable
    for key, vd in (("ZCB_TARGET_T2", "2020-12-31"), ("USSET_ZCB_T2_SPRD", "2021-11-25"), ("HEADLINE", "2025-09-11")):
        assert cell("npv", key, vd) > 0.0 and not cell("is_expired", key, vd) and not cell("is_tradable", key, vd)
        for k in ("settlement_value", "dirty_price", "clean_price", "accrued_amount", "notional_s"):
            assert pv.same(cell(k, key, vd), 0.0), (key, vd, k, cell(k, key, vd))
        assert pv.same(cell("clean_from_z", key, vd, 0.01), 0.0)  # NT_ENGINE
    # matures on v / after maturity: expired, everything 0.0
    for key, vd in (("ZCB_NULL_T0", "2020-12-25"), ("ZCB_TARGET_T2", "2021-01-04"), ("USGOV_T1_EOM", "2023-02-28"),
                    ("HEADLINE", "2025-09-15"), ("HEADLINE", "2025-09-16"), ("FWD_START", "2026-06-16")):
        assert cell("is_expired", key, vd)
        for k in ("npv", "npv_base", "settlement_value", "dirty_price", "clean_price", "market_value"):
            assert pv.same(cell(k, key, vd), 0.0), (key, vd, k)
    # the day before maturity on v: alive and priced
    assert cell("npv", "ZCB_NULL_T0", "2020-12-24") > 0.0 and cell("dirty_price", "ZCB_NULL_T0", "2020-12-24") > 0.0
    # before issue: s = issue, no accrued, a positive forward price
    for key, vd in (("T0_CPN_ON_V", "2015-09-14"), ("FWD_START", "2020-09-16")):
        assert cell("settle", key, vd) == int(m.Legs.bk_issue_arr()[bix(m, key)]) > serial_of(vd)
        assert pv.same(cell("accrued_amount", key, vd), 0.0) and cell("dirty_price", key, vd) > 0.0
    # a holiday v: a T+0 bond settles on the next business day, and the ZeroCurve's reference date is v
    assert iso(cell("settle", "T0_CPN_ON_V", "2020-12-25")) == "2020-12-28"
    assert pv.model_cells(m.Valuation[SCEN_ZERO, T_OF["2020-12-25"]], "node_date")(0) == serial_of("2020-12-25")


def test_extrapolation_off_raises_like_pureql(m):
    """Curve ending at 2Y, extrapolation OFF: the model raises pureql's checkRange message where pureql does.

    And with extrapolation ON (scenario 4, same nodes) the very same bond-points
    have values (``test_every_bond_point`` compares them all).
    """
    raised = 0
    for t in range(len(VDATES)):
        item_off = m.Valuation[SCEN_SHORT, t]
        item_on = m.Valuation[SCEN_SHORT_EXTRAP, t]
        for b in range(m.Data.n_bonds()):
            e = pv.pq_values_explicit(m, SCEN_SHORT, t, b)["bond"]["npv"]
            g = pv.run_model(pv.model_cells(item_off, "npv"), b)
            assert pv.same_outcome(g, e), (VDATES[t], b, pv.show(g), pv.show(e))
            if e[0] == "err":
                raised += 1
                assert g[1] is ValueError and "is past max curve time" in g[2]
                assert pv.run_model(pv.model_cells(item_on, "npv"), b)[0] == "ok"
    assert raised > 0


# --------------------------------------------------------------------------- flags
@pytest.mark.parametrize("R,T,F", FLAGS, ids=[f"R{r}-T{t}-F{f}" for r, t, f in FLAGS])
def test_flag_matrix_on_event_dates(new_model, edge_inputs, R, T, F):
    """Every output on the event dates under one (R, T, F), flat curve, on a FRESH model with the flags set first."""
    mm = new_model("FutureFlags", edge_inputs, include_reference_date_events=R, include_todays_cashflows=T,
                   engine_include_settlement_flows=F)
    assert pv.flags(mm) == (R, T, F)
    bad = compare(mm, [(SCEN_FLAT, T_OF[v]) for v in EVENT_DATES], zs=(0.0,))
    pv.report_mismatches(bad, f"flags R={R} T={T} F={F}")


@pytest.mark.slow
@pytest.mark.parametrize("R,T,F", FLAGS, ids=[f"R{r}-T{t}-F{f}" for r, t, f in FLAGS])
def test_flag_matrix_full(new_model, edge_inputs, R, T, F):
    """The flag matrix at every date of every scenario."""
    mm = new_model("FutureFlagsFull", edge_inputs, include_reference_date_events=R, include_todays_cashflows=T,
                   engine_include_settlement_flows=F)
    bad = compare(mm, [(s, t) for s in SCENARIOS for t in range(len(VDATES))], zs=(0.0,))
    pv.report_mismatches(bad, f"flags R={R} T={T} F={F} (full)")


def test_t_override_jump(new_model, edge_inputs):
    """``includeTodaysCashFlows = True`` with ``s == v``: the coupon on v enters the settlement value.

    T0_CPN_ON_V (T+0, 4.5% semiannual Thirty360) at Tue 15-Sep-2020, a
    coupon date: with T = None (default) the 2.25 coupon on v has occurred
    for every role; with T = True the override (``cashflow.cpp:35-41``: the
    reference date IS the evaluation date) includes it in the NPV AND in the
    settlement value, although the settlement role passes
    ``includeSettlementDateFlows = False``; the dirty price jumps by the
    coupon. The same override makes that coupon the next one for the
    accrued amount (``CashFlows.accruedAmount(leg, False, s)`` starts from
    the first flow NOT occurred at s), whose full accrual is the coupon: the
    accrued amount jumps by 2.25 too and the clean price stays (to T2).
    R = True alone moves the NPV but not the settlement value; T = False
    overrides R = True back. For the T+3 headline (``s != v``) T moves the
    NPV only.
    """
    vd = "2020-09-15"
    t = T_OF[vd]
    vals = {}
    for flags in ((0, -1, -1), (0, 1, -1), (1, -1, -1), (1, 0, -1)):
        mm = new_model("FutureTOverride", edge_inputs, include_reference_date_events=flags[0],
                       include_todays_cashflows=flags[1], engine_include_settlement_flows=flags[2])
        item = mm.Valuation[SCEN_FLAT, t]
        for key in ("T0_CPN_ON_V", "HEADLINE"):
            b = bix(mm, key)
            got, _ = pv.two_form_mismatches(mm, item, SCEN_FLAT, t, b, (0.0,), ctx=f"{flags} {key}")
            assert not got, got
            vals[(flags, key)] = {k: pv.model_cells(item, k)(b) for k in ("npv", "settlement_value", "dirty_price",
                                                                          "clean_price", "accrued_amount")}
    base, tod, ref, ref_t0 = (vals[((0, -1, -1), "T0_CPN_ON_V")], vals[((0, 1, -1), "T0_CPN_ON_V")],
                              vals[((1, -1, -1), "T0_CPN_ON_V")], vals[((1, 0, -1), "T0_CPN_ON_V")])
    coupon = 2.25
    assert abs((tod["dirty_price"] - base["dirty_price"]) - coupon) < 1e-12 * tod["dirty_price"]
    assert abs((tod["npv"] - base["npv"]) - coupon) < 1e-12 * tod["npv"]
    # the coupon on s is then also the NEXT coupon of ``CashFlows.accruedAmount(leg, False, s)``: its full
    # accrual (2.25) becomes the accrued amount, so the clean price does not move (T2: different sums)
    assert pv.same(base["accrued_amount"], 0.0)
    assert abs(tod["accrued_amount"] - coupon) < 1e-12 * coupon
    assert abs(tod["clean_price"] - base["clean_price"]) < 1e-12 * base["clean_price"]
    assert abs((ref["npv"] - base["npv"]) - coupon) < 1e-12 * ref["npv"]   # R moves the NPV ...
    assert pv.same(ref["dirty_price"], base["dirty_price"])                 # ... but not the price
    # T = False overrides R = True back
    assert pv.same(ref_t0["npv"], base["npv"]) and pv.same(ref_t0["dirty_price"], base["dirty_price"])
    h0, h1 = vals[((0, -1, -1), "HEADLINE")], vals[((0, 1, -1), "HEADLINE")]
    assert abs((h1["npv"] - h0["npv"]) - 2.0) < 1e-12 * h1["npv"]
    assert pv.same(h1["dirty_price"], h0["dirty_price"])


# --------------------------------------------------------------------------- the frozen named cases
#: name -> (scen_id, valuation date, bond key, (R, T, F)).
NAMED = {
    "headline coupon in (v,s] 2020-09-11": (SCEN_FLAT, "2020-09-11", "HEADLINE", (0, -1, -1)),
    "headline coupon on v 2020-09-15": (SCEN_FLAT, "2020-09-15", "HEADLINE", (0, -1, -1)),
    "headline next business day 2020-09-16": (SCEN_FLAT, "2020-09-16", "HEADLINE", (0, -1, -1)),
    "headline spread coupon in (v,s] 2020-09-11": (SCEN_ZERO, "2020-09-11", "HEADLINE_SPRD", (0, -1, -1)),
    "T-override s==v, T None": (SCEN_FLAT, "2020-09-15", "T0_CPN_ON_V", (0, -1, -1)),
    "T-override s==v, T True": (SCEN_FLAT, "2020-09-15", "T0_CPN_ON_V", (0, 1, -1)),
    "T-override s==v, R True": (SCEN_FLAT, "2020-09-15", "T0_CPN_ON_V", (1, -1, -1)),
    "T-override s==v, R True T False": (SCEN_FLAT, "2020-09-15", "T0_CPN_ON_V", (1, 0, -1)),
    "T-override s==v, F True": (SCEN_FLAT, "2020-09-15", "T0_CPN_ON_V", (0, -1, 1)),
    "xmas coupon paid on s 2020-12-24": (SCEN_FLAT, "2020-12-24", "TARGET_T1_XMAS", (0, -1, -1)),
    "xmas coupon paid on v 2020-12-28": (SCEN_FLAT, "2020-12-28", "TARGET_T1_XMAS", (0, -1, -1)),
    "zcb maturity in (v,s] 2020-12-31": (SCEN_FLAT, "2020-12-31", "ZCB_TARGET_T2", (0, -1, -1)),
    "zcb matures on v 2021-01-04": (SCEN_FLAT, "2021-01-04", "ZCB_TARGET_T2", (0, -1, -1)),
    "us thanksgiving zcb maturity in (v,s] 2021-11-25": (SCEN_ZERO, "2021-11-25", "USSET_ZCB_T2_SPRD", (0, -1, -1)),
    "us jul-4 coupon in (v,s] 2021-07-02": (SCEN_ZERO, "2021-07-02", "USGOV_T3_JUL4", (0, -1, -1)),
    "us observed holiday 2021-07-05": (SCEN_ZERO, "2021-07-05", "USGOV_T3_JUL4", (0, -1, -1)),
    "headline maturity in (v,s] 2025-09-11": (SCEN_FLAT, "2025-09-11", "HEADLINE", (0, -1, -1)),
    "headline matures on v 2025-09-15": (SCEN_FLAT, "2025-09-15", "HEADLINE", (0, -1, -1)),
    "headline after maturity 2025-09-16": (SCEN_FLAT, "2025-09-16", "HEADLINE", (0, -1, -1)),
    "forward start 2020-09-16": (SCEN_FLAT, "2020-09-16", "FWD_START", (0, -1, -1)),
    "T+0 day before issue 2015-09-14": (SCEN_FLAT, "2015-09-14", "T0_CPN_ON_V", (0, -1, -1)),
    "null zcb matures on a holiday v 2020-12-25": (SCEN_FLAT, "2020-12-25", "ZCB_NULL_T0", (0, -1, -1)),
    "T+0 on a holiday 2020-12-25": (SCEN_FLAT, "2020-12-25", "T0_CPN_ON_V", (0, -1, -1)),
    "extrapolate 0 past max time": (SCEN_SHORT, "2020-09-16", "HEADLINE", (0, -1, -1)),
    "extrapolate 1": (SCEN_SHORT_EXTRAP, "2020-09-16", "HEADLINE", (0, -1, -1)),
    "30/360 SimpleThenCompounded spread": (SCEN_30360, "2020-09-11", "HEADLINE_SPRD", (0, -1, -1)),
}


def named_values(input_dir):
    """pureql's values of every named case (form A, checked against form B), JSON-ready."""
    out = {}
    models = {}
    try:
        for name, (s, vd, key, flags) in NAMED.items():
            if flags not in models:
                models[flags] = pv.private_model("FutureNamed", input_dir, include_reference_date_events=flags[0],
                                                 include_todays_cashflows=flags[1],
                                                 engine_include_settlement_flows=flags[2])
            mm = models[flags]
            out[name] = pv.golden_record(pv.pq_bond_values(mm, s, T_OF[vd], bix(mm, key), Z_EDGE))
    finally:
        for mm in models.values():
            mm.close()
    return out


def test_golden_inputs_unchanged(edge_inputs):
    g = json.loads(GOLDEN.read_text(encoding="utf-8"))
    assert g["provenance"]["input_sha256"] == pv.input_hashes(edge_inputs)
    assert g["provenance"]["z_grid"] == list(Z_EDGE)
    assert {k: [s, vd, key, list(f)] for k, (s, vd, key, f) in NAMED.items()} == g["provenance"]["cases"]


def test_golden_t_override_jump():
    """The frozen jump: dirty and NPV move by the 2.25 coupon with T = True (s == v), not with R = True."""
    g = json.loads(GOLDEN.read_text(encoding="utf-8"))["values"]
    base, tod, ref = (g["T-override s==v, T None"]["bond"], g["T-override s==v, T True"]["bond"],
                      g["T-override s==v, R True"]["bond"])
    assert abs(tod["dirty_price"] - base["dirty_price"] - 2.25) < 1e-12 * tod["dirty_price"]
    assert ref["dirty_price"] == base["dirty_price"] and abs(ref["npv"] - base["npv"] - 2.25) < 1e-12 * ref["npv"]
    assert abs(tod["accrued_amount"] - 2.25) < 1e-12 and base["accrued_amount"] == 0.0
    assert abs(tod["clean_price"] - base["clean_price"]) < 1e-12 * base["clean_price"]


def test_pureql_still_reproduces_golden(edge_inputs):
    g = json.loads(GOLDEN.read_text(encoding="utf-8"))
    assert json.dumps(named_values(edge_inputs), sort_keys=True) == json.dumps(g["values"], sort_keys=True)


def test_model_matches_golden(new_model, edge_inputs):
    g = json.loads(GOLDEN.read_text(encoding="utf-8"))["values"]
    models, bad = {}, []
    for name, (s, vd, key, flags) in NAMED.items():
        if flags not in models:
            models[flags] = new_model("FutureNamedModel", edge_inputs, include_reference_date_events=flags[0],
                                      include_todays_cashflows=flags[1], engine_include_settlement_flows=flags[2])
        mm = models[flags]
        point = f"{s},{T_OF[vd]}"
        bad += pv.golden_mismatches(mm, {point: {key: g[name]}}, label=name)
    pv.report_mismatches(bad, "edge goldens")


def regenerate():
    """Write ``tests/data/future_edges.json`` from freshly written inputs."""
    import subprocess
    import tempfile

    from helpers.pureql_ref import PUREQL_SRC
    with tempfile.TemporaryDirectory() as d:
        write_edge_inputs(d)
        try:
            head = subprocess.run(["git", "-C", str(pathlib.Path(PUREQL_SRC).parent), "rev-parse", "HEAD"],
                                  capture_output=True, text=True, check=True).stdout.strip()
        except (OSError, subprocess.CalledProcessError):
            head = "unknown"
        doc = {
            "schema": "bondportfolio-future-edges/1",
            "provenance": {
                "what_it_is": ("pureql values of the named edge cases of tests/future/test_future_edges.py at "
                               "future valuation dates: per case (scenario, valuation date, bond key, flags R/T/F) "
                               "every contract-4.7 output of the bond (docs/model-contract.md), computed by "
                               "tests/helpers/pureql_val.py in the Settings-moved engine form and checked bit for "
                               "bit against the explicit-date form. Raw pureql outcomes ('*_from_z' keep pureql's "
                               "'non tradable' raise; the model's NT_ENGINE policy turns it into 0.0)."),
                "generator": "python tests/future/test_future_edges.py",
                "oracle": "pureql (quantlib-migration src/pureql, a port of QuantLib v1.43)",
                "quantlib_migration_head": head,
                "frozen_on": datetime.date.today().isoformat(),
                "input_dir": "tests/future/test_future_edges.py::write_edge_inputs",
                "input_sha256": pv.input_hashes(d),
                "cases": {k: [s, vd, key, list(f)] for k, (s, vd, key, f) in NAMED.items()},
                "flags_order": ["include_reference_date_events", "include_todays_cashflows",
                                "engine_include_settlement_flows"],
                "z_grid": list(Z_EDGE),
                "role_codes": {"0": "ROLE_ENGINE", "1": "ROLE_SETTLE", "2": "ROLE_EXPIRY"},
                "tier": "exact (bitwise; DECISIONS.md D-2)",
                "licence": "data computed with pureql (BSD-3-Clause, derived from QuantLib); see NOTICE.md",
            },
            "values": named_values(d),
        }
    GOLDEN.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")


if __name__ == "__main__":
    regenerate()
    print(f"wrote {GOLDEN}")
