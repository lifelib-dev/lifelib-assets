"""Measured goldens at FUTURE valuation dates (plan Phase 3 exit, Verification L5): bitwise.

The quantlib-migration README headline bond (a 10Y semiannual 4%
``FixedRateBond``, TARGET / Thirty360(BondBasis), T+3, issued 15-Sep-2015,
``bond_portfolio/bonds.csv`` row ``HEADLINE_10Y``) valued again five years on.

**Flat curve** (scenario 1), the literals measured in the plan's exploration
at v = 16-Sep-2020 (Wednesday; settlement T+3 = Mon 21-Sep-2020) on
``FlatForward(v, 3.5%, Actual365Fixed)`` (Continuous):

====================================== ==========================
NPV                                    ``102.13530449214969``
settlementValue = dirty price          ``102.18428521477128``
clean price                            ``102.11761854810462``
accrued amount                         ``0.06666666666665932``
clean price at z = 1.25% (Comp., Ann.) ``96.67131290103727``
====================================== ==========================

and, at t = 0, the README's own literals (16-Sep-2015, flat 3%): NPV
``108.36776235612268``, clean ``108.34563953853349``.

**Zero curve** (scenario 2): ``ZeroCurve`` on the nodes {v, v+1Y, v+3Y,
v+10Y} at {1%, 1.5%, 2.2%, 3%} (tenor nodes, resolved against each v), at
v = 15-Sep-2020 (a coupon date: the 2.0 coupon paid on v has occurred and is
EXCLUDED from NPV and prices) and at v = 16-Sep-2020. The exploration's
curve conventions could not be recovered, so this suite FIXES them as
``Actual365Fixed`` (the headline curve's day counter) and ``Continuous``
(the ZeroCurve default, so the input rates ARE the zero rates; no
``_initialize`` conversion), and pins the values measured here. They are
checked three ways: pureql's explicit-date form, pureql's Settings-moved
form (an independent README-style construction below), and QuantLib 1.41
with its evaluation date moved, at T2 (``test_future_oracle.py``).

The inputs are written into ``tmp_path`` (:func:`write_headline_inputs`).
``tests/data/future_headline_2020.json`` freezes every contract-4.7 output
of the set (pureql, both forms, bitwise), with its provenance; regenerate it
with ``python tests/future/test_future_goldens.py`` when the inputs change.
"""

import datetime
import json
import pathlib
import sys

import pytest

if __name__ == "__main__":  # the regeneration entry point needs the tests directory on sys.path
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from helpers import pureql_val as pv  # noqa: E402
from helpers.model import MODEL_DIR  # noqa: E402
from helpers.pureql_ref import pq_date, ql, serial  # noqa: E402

ROOT = MODEL_DIR.parents[1]
GOLDEN = ROOT / "tests" / "data" / "future_headline_2020.json"

#: The headline bond: bond_portfolio/bonds.csv row HEADLINE_10Y (quantlib-migration README.md:61-80).
HEADLINE = {"bond_key": "HEADLINE_10Y", "bond_type": "FixedRate", "face_amount": "100", "settlement_days": "3",
            "calendar": "TARGET", "issue_date": "2015-09-15", "redemption": "100",
            "effective_date": "2015-09-15", "termination_date": "2025-09-15", "tenor": "6M",
            "convention": "Unadjusted", "termination_convention": "Unadjusted", "rule": "Backward",
            "end_of_month": "0", "coupon_rate": "0.04", "accrual_day_counter": "Thirty360.BondBasis",
            "payment_convention": "Following"}
VDATES = ["2015-09-16", "2020-09-15", "2020-09-16"]
T_README, T_COUPON, T_2020 = 0, 1, 2
FLAT_RATES = ("0.03", "0.035", "0.035")
ZERO_NODES = (("0D", "0.01"), ("1Y", "0.015"), ("3Y", "0.022"), ("10Y", "0.03"))
SCEN_FLAT, SCEN_ZERO = 1, 2
#: The z grid of the golden file: the plan's z = 1.25% and the Phase 2 grid.
Z_GOLDEN = (-0.0125, 0.0, 0.0075, 0.0125)

README_NPV, README_CLEAN = 108.36776235612268, 108.34563953853349
#: Exploration literals at (flat 3.5%, 16-Sep-2020).
FLAT_2020 = {
    "npv": 102.13530449214969,
    "settlement_value": 102.18428521477128,
    "dirty_price": 102.18428521477128,
    "clean_price": 102.11761854810462,
    "accrued_amount": 0.06666666666665932,
}
Z_PLAN, Z_CLEAN_2020 = 0.0125, 96.67131290103727
#: Measured by this suite (ZeroCurve Actual365Fixed / Continuous; see the module docstring), per t.
ZERO_2020 = {
    T_COUPON: {"npv": 107.40808196296933, "dirty_price": 107.41694667000058, "clean_price": 107.38361333666725,
               "accrued_amount": 0.03333333333332966, "settle": "2020-09-18"},
    T_2020: {"npv": 107.41667973302043, "dirty_price": 107.43149615345824, "clean_price": 107.36482948679158,
             "accrued_amount": 0.06666666666665932, "settle": "2020-09-21"},
}


def write_headline_inputs(out):
    """The headline input set: 1 bond, 3 valuation dates, scenario 1 flat and scenario 2 the zero curve."""
    params, nodes = [], []
    for t in range(len(VDATES)):
        params.append({"scen_id": str(SCEN_FLAT), "t": str(t), "curve_type": "FlatForward",
                       "day_counter": "Actual365Fixed", "compounding": "Continuous", "frequency": "Annual",
                       "extrapolate": "0", "flat_rate": FLAT_RATES[t], "spread_compounding": "Compounded",
                       "spread_frequency": "Annual"})
        params.append({"scen_id": str(SCEN_ZERO), "t": str(t), "curve_type": "ZeroCurve",
                       "day_counter": "Actual365Fixed", "compounding": "Continuous", "frequency": "Annual",
                       "extrapolate": "0", "spread_compounding": "Compounded", "spread_frequency": "Annual"})
        for k, (tenor, rate) in enumerate(ZERO_NODES):
            nodes.append({"scen_id": str(SCEN_ZERO), "t": str(t), "node": str(k), "tenor": tenor, "rate": rate})
    return pv.write_inputs(out, [HEADLINE], VDATES, params, nodes)


@pytest.fixture(scope="module")
def headline_inputs(tmp_path_factory):
    return write_headline_inputs(tmp_path_factory.mktemp("future_headline"))


@pytest.fixture(scope="module")
def m(set_model, headline_inputs):
    return set_model("headline2020", headline_inputs)


def iso(d):
    """The ISO text of an int serial."""
    return (datetime.date(1899, 12, 30) + datetime.timedelta(days=int(d))).isoformat()


def iso_serial(s):
    """The serial of an ISO date: ``(date - 1899-12-30).days``."""
    return (datetime.date.fromisoformat(s) - datetime.date(1899, 12, 30)).days


def readme_bond(nsd=3):
    """The README construction (quantlib-migration tests/meta/test_documentation_set.py:322-358)."""
    from pureql.time.calendars.target import TARGET
    from pureql.time.daycounters.thirty360 import Thirty360
    issue = ql.Date(15, ql.September, 2015)
    sched = ql.Schedule(issue, ql.Date(15, ql.September, 2025), ql.Period(ql.Semiannual), TARGET(),
                        ql.Unadjusted, ql.Unadjusted, ql.DateGeneration.Backward, False)
    return ql.FixedRateBond(nsd, 100.0, sched, [0.04], Thirty360(Thirty360.BondBasis), ql.Following, 100.0, issue)


def readme_values(vdate_iso, curve_fn):
    """pureql with Settings moved to ``vdate_iso`` (independent of the harness): the README way."""
    from pureql.handle import Handle
    from pureql.pricingengines.bond.bondfunctions import BondFunctions
    from pureql.termstructures.yieldtermstructure import YieldTermStructure
    v = pq_date(iso_serial(vdate_iso))
    with pv.pq_settings(serial(v)):
        bond = readme_bond()
        curve = curve_fn(v)
        bond.setPricingEngine(ql.DiscountingBondEngine(Handle[YieldTermStructure](curve)))
        return {
            "npv": bond.NPV(), "settlement_value": bond.settlementValue(), "dirty_price": bond.dirtyPrice(),
            "clean_price": bond.cleanPrice(), "accrued_amount": bond.accruedAmount(),
            "settle": iso(serial(bond.settlementDate())),
            "clean_from_z": BondFunctions.cleanPrice(bond, curve, Z_PLAN, ql.Compounding.Compounded,
                                                     ql.Frequency.Annual),
        }


def flat_curve(rate):
    return lambda v: ql.FlatForward(v, rate, ql.Actual365Fixed())


def zero_curve(v):
    from pureql.math.interpolations.linearinterpolation import Linear
    from pureql.termstructures.yield_.zerocurve import ZeroCurve
    dates = [v, v + ql.Period(1, ql.Years), v + ql.Period(3, ql.Years), v + ql.Period(10, ql.Years)]
    return ZeroCurve(dates, [0.01, 0.015, 0.022, 0.03], ql.Actual365Fixed(), ql.NullCalendar(), Linear(),
                     ql.Compounding.Continuous, ql.Frequency.Annual)


# --------------------------------------------------------------------------- the inputs are what they claim
def test_inputs_are_the_headline_bond_on_the_plan_curves(m):
    assert list(m.Data.bond_keys()) == ["HEADLINE_10Y"]
    assert [iso(d) for d in m.Data.val_date_arr().tolist()] == VDATES
    for t in range(3):
        cf = pv.curve_inputs(m, SCEN_FLAT, t)
        assert (cf["type"], cf["dc"], cf["comp"], cf["flat"]) == (pv.CURVE_FLAT, 2, 2, float(FLAT_RATES[t]))
        cz = pv.curve_inputs(m, SCEN_ZERO, t)
        v = pq_date(cz["vdate"])
        assert (cz["type"], cz["dc"], cz["comp"]) == (pv.CURVE_ZERO, 2, 2)
        assert cz["node_dates"] == [serial(v), serial(v + ql.Period(1, ql.Years)), serial(v + ql.Period(3, ql.Years)),
                                    serial(v + ql.Period(10, ql.Years))]
        assert cz["node_rates"] == [0.01, 0.015, 0.022, 0.03]
        assert (cz["sp_comp"], cz["sp_freq"]) == (1, 1)


# --------------------------------------------------------------------------- the literals
def test_readme_construction_reproduces_the_literals():
    """pureql, Settings moved (README construction, no harness): the plan's literals and this suite's."""
    r = readme_values("2015-09-16", flat_curve(0.03))
    assert pv.same(r["npv"], README_NPV) and pv.same(r["clean_price"], README_CLEAN)
    r = readme_values("2020-09-16", flat_curve(0.035))
    assert r["settle"] == "2020-09-21"
    for k, want in FLAT_2020.items():
        assert pv.same(r[k], want), (k, r[k], want)
    assert pv.same(r["clean_from_z"], Z_CLEAN_2020)
    for t, vd in ((T_COUPON, "2020-09-15"), (T_2020, "2020-09-16")):
        r = readme_values(vd, zero_curve)
        for k, want in ZERO_2020[t].items():
            assert r[k] == want if k == "settle" else pv.same(r[k], want), (vd, k, r[k], want)


def test_harness_reproduces_the_literals(m):
    """Both harness forms (explicit dates; Settings moved), from the model's parsed inputs, give the literals."""
    for form in (pv.pq_values_engine, pv.pq_values_explicit):
        raw = form(m, SCEN_FLAT, T_README, 0)["bond"]
        assert pv.same_outcome(raw["npv"], ("ok", README_NPV)) and pv.same_outcome(raw["clean_price"],
                                                                                    ("ok", README_CLEAN))
        x = form(m, SCEN_FLAT, T_2020, 0, (Z_PLAN,))
        for k, want in FLAT_2020.items():
            assert pv.same_outcome(x["bond"][k], ("ok", want)), (form.__name__, k, x["bond"][k], want)
        assert pv.same_outcome(x["z"][("clean_from_z", Z_PLAN)], ("ok", Z_CLEAN_2020))
        for t in (T_COUPON, T_2020):
            raw = form(m, SCEN_ZERO, t, 0)["bond"]
            for k, want in ZERO_2020[t].items():
                want = ("ok", iso_serial(want)) if k == "settle" else ("ok", want)
                assert pv.same_outcome(raw[k], want), (form.__name__, t, k, raw[k], want)


def test_model_flat_2020_literals(m):
    """The model at (flat 3.5%, 16-Sep-2020): the exploration's literals, bit for bit."""
    item = m.Valuation[SCEN_FLAT, T_2020]
    assert iso(pv.model_cells(item, "settle")(0)) == "2020-09-21"
    for k, want in FLAT_2020.items():
        got = pv.model_cells(item, k)(0)
        assert pv.same(got, want), f"{k}: model {got!r} vs {want!r}"
    got = pv.model_cells(item, "clean_from_z")(0, Z_PLAN)
    assert pv.same(got, Z_CLEAN_2020), f"clean_from_z(1.25%): model {got!r} vs {Z_CLEAN_2020!r}"
    item0 = m.Valuation[SCEN_FLAT, T_README]
    assert pv.same(pv.model_cells(item0, "npv")(0), README_NPV)
    assert pv.same(pv.model_cells(item0, "clean_price")(0), README_CLEAN)


@pytest.mark.parametrize("t", [T_COUPON, T_2020])
def test_model_zero_curve_2020(m, t):
    """The model on the zero curve at 15- and 16-Sep-2020: this suite's measured values, bit for bit."""
    item = m.Valuation[SCEN_ZERO, t]
    for k, want in ZERO_2020[t].items():
        got = pv.model_cells(item, k)(0)
        if k == "settle":
            assert iso(got) == want
        else:
            assert pv.same(got, want), f"(2, {t}) {k}: model {got!r} vs {want!r}"
    assert pv.same(pv.model_cells(item, "settlement_value")(0), pv.model_cells(item, "dirty_price")(0))


@pytest.mark.parametrize("scen_id", [SCEN_FLAT, SCEN_ZERO])
@pytest.mark.parametrize("t", range(3))
def test_model_equals_both_pureql_forms(m, scen_id, t):
    """Every contract-4.7 output at every (scen, t), against each pureql form separately (bitwise)."""
    item = m.Valuation[scen_id, t]
    bad, _ = pv.two_form_mismatches(m, item, scen_id, t, 0, Z_GOLDEN, ctx=f"({scen_id}, {t})")
    pv.report_mismatches(bad, f"headline ({scen_id}, {t})")


@pytest.mark.parametrize("scen_id", [SCEN_FLAT, SCEN_ZERO])
def test_coupon_on_the_valuation_date_is_excluded(m, scen_id):
    """At v = 15-Sep-2020 the coupon paid on v has occurred (R = False, T = None): not in NPV, not in prices.

    The engine's first live flow is the one after it, and the NPV equals
    pureql's ``CashFlows.npv`` over the leg WITHOUT that flow (bitwise: the
    sum skips it either way); at 16-Sep-2020 the same flow is simply past.
    """
    from pureql.cashflows.cashflows import CashFlows
    item = m.Valuation[scen_id, T_COUPON]
    v = iso_serial("2020-09-15")
    dates = m.Legs.cf_date_arr().tolist()
    k = dates.index(v)
    assert m.Legs.cf_kind_arr()[k] == 0 and pv.same(float(m.Legs.cf_amount_arr()[k]), 2.0000000000000018) or \
        abs(float(m.Legs.cf_amount_arr()[k]) - 2.0) < 1e-12
    assert pv.model_cells(item, "first_live")(0, pv.ROLE_ENGINE) == k + 1
    assert pv.model_cells(item, "first_live")(0, pv.ROLE_SETTLE) == k + 1
    c = pv.curve_inputs(m, scen_id, T_COUPON)
    with pv.pq_settings():
        bond = pv.pq_bond(m, 0)
        leg = bond.cashflows()
        assert serial(leg[k].date()) == v
        curve = pv.pq_curve(m, scen_id, T_COUPON, c)
        without = CashFlows.npv(leg[k + 1:], curve, False, pq_date(v), pq_date(v))
        with_flow = CashFlows.npv(leg[k:], curve, True, pq_date(v), pq_date(v))
    npv = pv.model_cells(item, "npv")(0)
    assert pv.same(npv, without)
    assert abs(with_flow - npv - leg[k].amount()) < 1e-12 * with_flow


# --------------------------------------------------------------------------- the frozen file
def test_golden_inputs_unchanged(headline_inputs):
    """The golden was frozen from these exact input files (else regenerate it)."""
    g = json.loads(GOLDEN.read_text(encoding="utf-8"))
    assert g["provenance"]["input_sha256"] == pv.input_hashes(headline_inputs)
    assert g["provenance"]["z_grid"] == list(Z_GOLDEN)


def test_golden_holds_the_literals():
    g = json.loads(GOLDEN.read_text(encoding="utf-8"))["values"]
    rec = g[f"{SCEN_FLAT},{T_2020}"]["HEADLINE_10Y"]
    for k, want in FLAT_2020.items():
        assert pv.same(rec["bond"][k], want), k
    assert pv.same(rec["z"][f"clean_from_z[{Z_PLAN!r}]"], Z_CLEAN_2020)
    for t in (T_COUPON, T_2020):
        rec = g[f"{SCEN_ZERO},{t}"]["HEADLINE_10Y"]
        for k, want in ZERO_2020[t].items():
            assert rec["bond"][k] == (iso_serial(want) if k == "settle" else want), (t, k)


def test_pureql_still_reproduces_golden(m):
    """pureql today == the frozen values, bit for bit (a drift of the oracle shows here)."""
    g = json.loads(GOLDEN.read_text(encoding="utf-8"))
    assert json.dumps(pv.golden_values(m, Z_GOLDEN), sort_keys=True) == json.dumps(g["values"], sort_keys=True)


def test_model_matches_golden(m):
    g = json.loads(GOLDEN.read_text(encoding="utf-8"))
    pv.report_mismatches(pv.golden_mismatches(m, g["values"], label="headline 2020"), "golden headline 2020")


# --------------------------------------------------------------------------- regeneration
def regenerate():
    """Write ``tests/data/future_headline_2020.json`` from freshly written inputs."""
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        write_headline_inputs(d)
        model = pv.private_model("FutureGoldenRegen", d)
        try:
            pv.write_golden(
                model, d, GOLDEN, "future-headline-2020 (tests/future/test_future_goldens.py::write_headline_inputs)",
                zs=Z_GOLDEN,
                what_it_is=("The quantlib-migration README headline bond at 16-Sep-2015, 15-Sep-2020 (a coupon "
                            "date) and 16-Sep-2020; scenario 1 FlatForward Actual365Fixed Continuous (3%, 3.5%, "
                            "3.5%), scenario 2 ZeroCurve on the tenor nodes 0D/1Y/3Y/10Y at 1%/1.5%/2.2%/3% "
                            "(Actual365Fixed, Continuous; conventions fixed by this suite). Spread conventions "
                            "Compounded/Annual. The (1, 2) values are the plan's exploration literals."),
                generator="python tests/future/test_future_goldens.py")
        finally:
            model.close()


if __name__ == "__main__":
    regenerate()
    print(f"wrote {GOLDEN}")
