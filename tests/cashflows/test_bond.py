"""The Bond[b] Space (docs/model-contract.md 4.4) against pureql, bond by bond.

Every bond of an input set is built twice, by the model and by pureql from
the model's own parsed inputs (``helpers.pureql_ref.pq_bond``), and compared
EXACTLY: schedule dates and isRegular, the schedule's meta data, the
coupons (dates, nominal, rate, compounding, frequency, day counter), the
leg (date, kind, amount, accrual and reference dates, nominal, rate,
accrual period), the notional schedule, the maturity, the issue date and
the settlement days. Errors must agree in type and message.

The default run covers the demo inputs, the mx2cy coverage set, a seeded
2,000-bond generated portfolio and 1,000 adversarial bonds; the 20,000-bond
and 9,000-adversarial-bond variants are marked ``slow``.
"""

import math

import pytest

from cashflow_checks import (
    COVERAGE,
    DEMO,
    bond_mismatches,
    fuzz_mismatches,
    fuzz_tables,
    gen,
    portfolio_mismatches,
    private_model,
    run_model,
    run_pq,
    same,
    write_generated,
)
from helpers.pureql_ref import pq_bond, pq_leg_records, ql, serial
from pureql import _state

# --------------------------------------------------------------------------- the headline bond
# Copied from quantlib-migration (QLM) at commit 3cae5679a32b50d833d518aab402c13238dcff30:
# README.md:65-67 publishes these literals for the port, and
# tests/meta/test_documentation_set.py::test_the_readme_headline_is_what_the_port_computes_today
# (lines 306-392) pins them to pureql bit for bit. The bond is the README's: a 10-year semiannual
# FixedRateBond, 4% coupon, TARGET / Thirty360(BondBasis), Unadjusted, Backward, 3 settlement days,
# issued 2015-09-15, priced on a flat 3% Actual365Fixed curve at 2015-09-16.
HEADLINE_NPV = 108.36776235612268
HEADLINE_CLEAN = 108.34563953853349
HEADLINE_N_FLOWS = 21


@pytest.fixture(scope="module")
def m():
    model = private_model("BondTest")
    yield model
    model.close()


@pytest.fixture
def pq_settings():
    """pureql Settings, restored EXACTLY afterwards (SavedSettings alone anchors an unset date, Q-08)."""
    before = _state.snapshot_all()
    yield ql.Settings.instance()
    _state.restore_all(before)


def readme_bond():
    """The README headline bond, constructed exactly as QLM's test_documentation_set.py does."""
    from pureql.time.calendars.target import TARGET
    from pureql.time.daycounters.thirty360 import Thirty360

    issue = ql.Date(15, ql.September, 2015)
    schedule = ql.Schedule(issue, ql.Date(15, ql.September, 2025), ql.Period(ql.Semiannual), TARGET(),
                           ql.Unadjusted, ql.Unadjusted, ql.DateGeneration.Backward, False)
    return ql.FixedRateBond(3, 100.0, schedule, [0.04], Thirty360(Thirty360.BondBasis), ql.Following,
                            100.0, issue)


def test_headline_bond_is_the_readme_bond_bit_for_bit(m, pq_settings):
    """(a) The demo row HEADLINE_10Y: 21 flows, each == the README bond's, which prices to the pinned literals."""
    pq_settings.setEvaluationDate(ql.Date(16, ql.September, 2015))
    bond = readme_bond()
    bond.setPricingEngine(ql.DiscountingBondEngine(
        ql.Handle(ql.FlatForward(ql.Date(16, ql.September, 2015), 0.03, ql.Actual365Fixed()))))
    # the reference bond is the one whose NPV and clean price QLM publishes
    assert bond.NPV() == HEADLINE_NPV
    assert bond.cleanPrice() == HEADLINE_CLEAN
    assert len(bond.cashflows()) == HEADLINE_N_FLOWS

    m.Data.input_dir = str(DEMO)
    b = m.Data.bond_keys().index("HEADLINE_10Y")
    mb = m.Bond[b]
    leg = mb.leg()
    assert mb.n_flows() == HEADLINE_N_FLOWS == len(leg)
    for (d, kind, amount, ci), cf in zip(leg, bond.cashflows()):
        assert d == serial(cf.date())
        assert same(amount, cf.amount()), (d, amount, cf.amount())
        assert (ci >= 0) == cf.isCoupon()
    from cashflow_checks import model_leg_records
    assert same(model_leg_records(mb), pq_leg_records(bond))
    assert mb.maturity_date() == serial(bond.maturityDate())
    # 20 coupons of 100 * (1 + 0.04 * 0.5 - 1) and the redemption of 100
    assert [f[1] for f in leg] == [0] * 20 + [2]
    assert leg[-1][2] == 100.0


@pytest.mark.parametrize("input_dir", [DEMO, COVERAGE], ids=["demo", "coverage"])
def test_every_bond_matches_pureql(m, input_dir):
    """(b) Every bond of the demo and the coverage inputs == pureql."""
    errs = portfolio_mismatches(m, input_dir)
    assert not errs, "\n".join(errs[:20])


@pytest.mark.parametrize("input_dir", [DEMO, COVERAGE], ids=["demo", "coverage"])
def test_bond_cells_return_the_contract_types(m, input_dir):
    """Ints are int, floats float, flags 0/1, isRegular bool, records tuples (rule 2 of the contract)."""
    m.Data.input_dir = str(input_dir)
    for b in range(m.Data.n_bonds()):
        mb = m.Bond[b]
        for name in ("bond_type", "settlement_days", "bond_calendar", "issue_date", "spread_index",
                     "effective_date", "termination_date", "tenor_n", "tenor_unit", "convention",
                     "termination_convention", "rule", "end_of_month", "first_date", "next_to_last_date",
                     "accrual_dc", "first_period_dc", "payment_convention", "payment_calendar_in",
                     "maturity_in", "yield_dc", "yield_comp", "yield_freq", "calendar", "maturity_date",
                     "n_flows"):
            assert type(getattr(mb, name)()) is int, name
        for name in ("face_amount", "redemption"):
            assert type(getattr(mb, name)()) is float, name
        s = mb.schedule()
        assert type(s) is tuple and len(s) == 10
        assert all(type(d) is int for d in s[0]) and all(type(r) is bool for r in s[1])
        assert all(type(v) is int for v in s[2:])
        assert len(s[1]) == max(len(s[0]) - 1, 0)
        for c in mb.coupons():
            assert [type(v) for v in c] == [int] * 6 + [float, float, int, int, int]
        assert all(type(a) is float for a in mb.coupon_amounts())
        assert all(type(a) is float for a in mb.accrual_periods())
        for d, kind, amount, ci in mb.leg():
            assert type(d) is int and type(kind) is int and type(amount) is float and type(ci) is int
        ns_dates, ns_notionals = mb.notional_schedule()
        assert all(type(d) is int for d in ns_dates) and all(type(x) is float for x in ns_notionals)
        assert ns_dates[0] == 0 and ns_notionals[-1] == 0.0
        assert type(mb.coupon_rates()) is tuple


def test_leg_is_coupons_then_redemptions_stably_sorted(m):
    """``leg()``: a redemption paid on the last coupon date comes after that coupon."""
    m.Data.input_dir = str(COVERAGE)
    for b in range(m.Data.n_bonds()):
        leg = m.Bond[b].leg()
        assert [f[0] for f in leg] == sorted(f[0] for f in leg)
        n_cp = len(m.Bond[b].coupons())
        assert sorted(f[3] for f in leg if f[3] >= 0) == list(range(n_cp))
        if n_cp:
            assert leg[-1][1] == 2 and leg[-2][3] == n_cp - 1


def test_cashflow_table(m):
    m.Data.input_dir = str(DEMO)
    b = m.Data.bond_keys().index("HEADLINE_10Y")
    df = m.Bond[b].cashflow_table()
    assert list(df.columns) == ["flow", "kind", "date", "amount", "nominal", "rate", "accrual_start",
                                "accrual_end", "ref_start", "ref_end", "accrual_period"]
    assert len(df) == 21
    assert df["date"].iloc[0] == "2016-03-15" and df["kind"].iloc[-1] == "redemption"
    assert df["accrual_start"].iloc[0] == "2015-09-15" and df["accrual_period"].iloc[0] == 0.5
    assert df["ref_end"].iloc[-1] == "" and math.isnan(df["nominal"].iloc[-1])


@pytest.fixture(scope="module")
def generated_2k(tmp_path_factory):
    return write_generated(tmp_path_factory.mktemp("gen2k"), 2000, 20261011)


def test_generated_portfolio_matches_pureql(generated_2k):
    """(c) A seeded 2,000-bond portfolio from generate_inputs.py == pureql, bond by bond."""
    model = private_model("BondGen")
    try:
        model.Data.input_dir = str(generated_2k)
        assert model.Data.check_inputs() is True
        errs = portfolio_mismatches(model, generated_2k, free_items=True)
    finally:
        model.close()
    assert not errs, f"{len(errs)} mismatches:\n" + "\n".join(errs[:20])


@pytest.mark.slow
@pytest.mark.parametrize("seed", [1, 2])
def test_generated_portfolio_20k_matches_pureql(tmp_path, seed):
    """(c, slow) 2 x 10,000 generated bonds == pureql."""
    write_generated(tmp_path, 10000, seed)
    model = private_model("BondGen20k")
    try:
        errs = portfolio_mismatches(model, tmp_path, free_items=True)
    finally:
        model.close()
    assert not errs, f"{len(errs)} mismatches:\n" + "\n".join(errs[:20])


def _fuzz(tmp_path, seed, n):
    gen.write_tables(tmp_path, fuzz_tables(seed, n))
    model = private_model("BondFuzz")
    errs = []
    outcomes = {"ok": 0, "err": 0}
    try:
        model.Data.input_dir = str(tmp_path)
        for b in range(model.Data.n_bonds()):
            errs.extend(fuzz_mismatches(model, b))
            outcomes[run_model(model.Bond[b].leg)[0]] += 1
            del model.Bond[b]
    finally:
        model.close()
    return errs, outcomes


def test_adversarial_bonds_match_pureql(tmp_path):
    """Month ends, stubs anywhere, day/week tenors, eom on any tenor, error paths: == pureql."""
    errs, outcomes = _fuzz(tmp_path, 11, 1000)
    assert not errs, f"{len(errs)} mismatches:\n" + "\n".join(errs[:20])
    # the set exercises both the built and the refused bonds
    assert outcomes["ok"] > 700 and outcomes["err"] > 50, outcomes


@pytest.mark.slow
@pytest.mark.parametrize("seed", [1, 2, 3])
def test_adversarial_bonds_match_pureql_sweep(tmp_path, seed):
    errs, _ = _fuzz(tmp_path, seed, 3000)
    assert not errs, f"{len(errs)} mismatches:\n" + "\n".join(errs[:20])


# --------------------------------------------------------------------------- errors and v1 scope
BOND_HEADER = ",".join(gen.BOND_COLUMNS)


def _one_bond(tmp_path, **cells):
    row = dict.fromkeys(gen.BOND_COLUMNS, "")
    row.update({"bond_key": "X", "bond_type": "FixedRate", "face_amount": "100", "settlement_days": "2",
                "calendar": "TARGET", "effective_date": "2015-01-15", "termination_date": "2020-01-15",
                "tenor": "6M", "coupon_rate": "0.04", "accrual_day_counter": "Actual360"})
    row.update(cells)
    tables = gen.generate(1, 1, 1, 1)
    tables["bonds.csv"] = (gen.BOND_COLUMNS, [row])
    tables["coupon_rates.csv"] = (gen.COUPON_RATE_COLUMNS, [])
    gen.write_tables(tmp_path, tables)
    return tmp_path


def _model_error(model, fn):
    out = run_model(fn)
    assert out[0] == "err", out
    return out[1], out[2]


def test_rules_other_than_backward_are_refused(m, tmp_path):
    m.Data.input_dir = str(_one_bond(tmp_path, rule="Forward"))
    assert _model_error(m, m.Bond[0].schedule) == (ValueError, "rule not supported in this model version")


def test_a_zero_tenor_forces_the_zero_rule_whatever_the_input_rule(m, tmp_path):
    """The Zero arm: Forward with 0D is accepted, as the zero tenor overrides the rule upstream."""
    m.Data.input_dir = str(_one_bond(tmp_path, rule="Forward", tenor="0D"))
    s = m.Bond[0].schedule()
    assert len(s[0]) == 2 and s[1] == (True,)
    assert s[3:5] == (0, 3) and s[8] == 2  # tenor 0 Years, rule Zero
    assert not bond_mismatches(m, 0)


@pytest.mark.parametrize("cells", [
    {"first_date": "2014-12-01"},                      # before the effective date
    {"first_date": "2020-02-01"},                      # after the termination date
    {"next_to_last_date": "2020-01-15", "first_date": "2015-01-15"},  # equal to the ends: ignored
    {"next_to_last_date": "2014-01-01"},
    {"tenor": "0D", "first_date": "2016-01-15"},       # first date with the Zero rule
    {"tenor": "0D", "next_to_last_date": "2016-01-15"},
    {"termination_date": "2015-01-15"},                # effective == termination
    {"termination_date": "2014-01-15"},
    {"tenor": "0D", "end_of_month": "1", "rule": "Zero"},
    {"tenor": "6M", "end_of_month": "1", "rule": "Zero"},  # the upstream-unusable pair: raises on both
    {"effective_date": "2015-01-30", "termination_date": "2015-02-02", "tenor": "1M",
     "convention": "Following", "end_of_month": "1"},
], ids=lambda c: ",".join(f"{k}={v}" for k, v in c.items()))
def test_schedule_errors_and_edge_cases_match_pureql(m, tmp_path, cells):
    m.Data.input_dir = str(_one_bond(tmp_path, **cells))
    errs = bond_mismatches(m, 0)
    assert not errs, "\n".join(errs)


def test_null_effective_date_raises(m, tmp_path, pq_settings):
    """Deviation: upstream's placeholder effective date reads the evaluation date; the model refuses."""
    from pureql.time.calendars.target import TARGET

    m.Data.input_dir = str(_one_bond(tmp_path, effective_date=""))
    assert _model_error(m, m.Bond[0].schedule) == (ValueError, "null effective date")
    # pureql raises the same message whenever the evaluation date is not before the termination date
    pq_settings.setEvaluationDate(ql.Date(16, ql.September, 2015))
    po = run_pq(lambda: ql.Schedule(ql.Date(), ql.Date(15, 1, 1990), ql.Period(6, ql.TimeUnit.Months),
                                    TARGET(), ql.Following, ql.Following, ql.DateGeneration.Backward, False))
    assert po == ("err", ValueError, "null effective date")


def test_zero_coupon_bond(m):
    """ZeroCouponBond: no schedule, no coupons, one redemption on the adjusted maturity."""
    m.Data.input_dir = str(DEMO)
    b = m.Data.bond_keys().index("ZCB_2008")
    mb = m.Bond[b]
    assert mb.schedule()[0:3] == ((), (), 0)
    assert mb.coupons() == () and mb.coupon_amounts() == ()
    bond = pq_bond(m, b)
    (d, kind, amount, ci), = mb.leg()
    assert (d, kind, ci) == (serial(bond.cashflows()[0].date()), 2, -1)
    assert same(amount, bond.cashflows()[0].amount())
    assert mb.maturity_date() == mb.maturity_in() == serial(bond.maturityDate())
    assert d != mb.maturity_date()  # 2008-11-30 is a Sunday: paid on the adjusted date
    assert mb.notional_schedule() == ((0, d), (1000000.0, 0.0))
