"""The Proj Space (docs/model-contract.md 4.6): projection buckets and their sums.

* ``bucket_arr()`` == a brute-force search for the first t at which the
  flow has occurred (``lib.has_occurred`` with the ENGINE flags) under every
  combination of the three flags, and == pureql's
  ``CashFlow.hasOccurred`` under the corresponding Settings.
* ``bucket_sums()`` == the same sums recomputed here in the same order
  (bitwise), and the sum over buckets == the sum over flows per kind at the
  T2 tier (an identity across two summation orders, DECISIONS D-2).
* ``period_start`` / ``period_end`` bracket every flow of their bucket.
* ``bond_cf_table()`` == per-bond sums recomputed here (bitwise).
"""

import itertools

import numpy as np
import pytest

from cashflow_checks import COVERAGE, DEMO, gen, private_model, same
from helpers.approx import assert_t2
from helpers.pureql_ref import pq_date, ql
from pureql import _state

TRI = {-1: None, 0: False, 1: True}


@pytest.fixture(scope="module")
def m():
    model = private_model("ProjTest")
    yield model
    model.close()


@pytest.fixture(scope="module")
def monthly_inputs(tmp_path_factory):
    """150 generated bonds valued at 25 monthly dates (many flows in each bucket)."""
    out = tmp_path_factory.mktemp("proj_monthly")
    gen.write_tables(out, gen.generate(150, 1, 25, 5, base="2015-09-16", step="1M"))
    return out


def set_flags(m, R, T, F):
    m.Data.include_reference_date_events = R
    m.Data.include_todays_cashflows = T
    m.Data.engine_include_settlement_flows = F


def brute_force_buckets(m):
    """First t with lib.has_occurred(cf_date, v_t, inc, v_t, T, R), else T, by a linear scan."""
    R = m.Data.include_reference_date_events
    T = m.Data.include_todays_cashflows
    F = m.Data.engine_include_settlement_flows
    inc = F if F != -1 else R
    vd = [int(v) for v in m.Data.val_date_arr()]
    out = []
    for d in m.Legs.cf_date_arr().tolist():
        per = len(vd)
        for t, v in enumerate(vd):
            if m.Lib.has_occurred(d, v, inc, v, T, R):
                per = t
                break
        out.append(per)
    return out


FLAGS = list(itertools.product((0, 1), (-1, 0, 1), (-1, 0, 1)))


@pytest.mark.parametrize("input_dir", [DEMO, COVERAGE], ids=["demo", "coverage"])
@pytest.mark.parametrize("R,T,F", FLAGS)
def test_bucket_is_the_first_occurrence(m, input_dir, R, T, F):
    m.Data.input_dir = str(input_dir)
    set_flags(m, R, T, F)
    try:
        b = m.Proj.bucket_arr()
        assert b.dtype == np.int64 and b.shape == (m.Legs.n_flows(),)
        assert b.tolist() == brute_force_buckets(m)
        assert m.Proj.engine_include() == (F if F != -1 else R)
    finally:
        set_flags(m, 0, -1, -1)


@pytest.mark.parametrize("R,T,F", [(0, -1, -1), (1, -1, -1), (0, 1, -1), (0, -1, 1), (1, 0, 0)])
def test_bucket_on_a_monthly_grid(m, monthly_inputs, R, T, F):
    m.Data.input_dir = str(monthly_inputs)
    set_flags(m, R, T, F)
    try:
        assert m.Proj.bucket_arr().tolist() == brute_force_buckets(m)
    finally:
        set_flags(m, 0, -1, -1)


@pytest.mark.parametrize("R,T,F", [(0, -1, -1), (1, -1, -1), (0, 1, -1), (1, 0, 1), (0, -1, 1)])
def test_bucket_is_pureql_engine_occurrence(m, R, T, F):
    """The bucket predicate is pureql's: ``cf.hasOccurred(v_t, F ?: R)`` with Settings at v_t."""
    m.Data.input_dir = str(COVERAGE)
    set_flags(m, R, T, F)
    before = _state.snapshot_all()
    try:
        vd = [int(v) for v in m.Data.val_date_arr()]
        inc = TRI[F] if F != -1 else bool(R)
        s = ql.Settings.instance()
        s.setIncludeReferenceDateEvents(bool(R))
        s.setIncludeTodaysCashFlows(TRI[T])
        expected = []
        for d in m.Legs.cf_date_arr().tolist():
            per = len(vd)
            for t, v in enumerate(vd):
                s.setEvaluationDate(pq_date(v))
                if ql.SimpleCashFlow(1.0, pq_date(d)).hasOccurred(pq_date(v), inc):
                    per = t
                    break
            expected.append(per)
        assert m.Proj.bucket_arr().tolist() == expected
    finally:
        _state.restore_all(before)
        set_flags(m, 0, -1, -1)


@pytest.mark.parametrize("which", ["demo", "coverage", "monthly"])
def test_bucket_sums(m, monthly_inputs, which):
    m.Data.input_dir = str({"demo": DEMO, "coverage": COVERAGE, "monthly": monthly_inputs}[which])
    T = m.Data.n_times()
    kinds = m.Legs.cf_kind_arr().tolist()
    amounts = m.Legs.cf_amount_arr().tolist()
    buckets = m.Proj.bucket_arr().tolist()
    # the same sums, in the same (global flow) order
    exp = [[0.0, 0.0, 0.0] for _ in range(T + 1)]
    for per, k, a in zip(buckets, kinds, amounts):
        exp[per][k] += a
    bs = m.Proj.bucket_sums()
    assert bs.dtype == np.float64 and bs.shape == (T + 1, 3)
    assert same(bs.tolist(), exp)
    for per in range(T + 1):
        c, a, r = m.Proj.coupon_cf(per), m.Proj.amortization_cf(per), m.Proj.redemption_cf(per)
        assert same([c, a, r], exp[per])
        assert same(m.Proj.total_cf(per), c + a + r)
    # sum over buckets == sum over flows, per kind (two summation orders: T2)
    for k in range(3):
        by_flow = 0.0
        for kk, a in zip(kinds, amounts):
            if kk == k:
                by_flow += a
        by_bucket = 0.0
        for per in range(T + 1):
            by_bucket += exp[per][k]
        assert_t2(by_bucket, by_flow, f"kind {k}")


@pytest.mark.parametrize("which", ["coverage", "monthly"])
@pytest.mark.parametrize("R,T,F", [(0, -1, -1), (1, -1, -1), (0, 1, 1)])
def test_periods_bracket_their_flows(m, monthly_inputs, which, R, T, F):
    m.Data.input_dir = str({"coverage": COVERAGE, "monthly": monthly_inputs}[which])
    set_flags(m, R, T, F)
    try:
        n_t = m.Data.n_times()
        vd = [int(v) for v in m.Data.val_date_arr()]
        assert m.Proj.period_start(0) == 0 and m.Proj.period_end(n_t) == 109574
        for per in range(n_t + 1):
            assert type(m.Proj.period_start(per)) is int and type(m.Proj.period_end(per)) is int
            if per < n_t:
                assert m.Proj.period_end(per) == vd[per] == m.Proj.period_start(per + 1)
        inc = m.Proj.engine_include()
        for d, per in zip(m.Legs.cf_date_arr().tolist(), m.Proj.bucket_arr().tolist()):
            s, e = m.Proj.period_start(per), m.Proj.period_end(per)
            if per < n_t:
                assert m.Lib.has_occurred(d, e, inc, e, T, R)
            if per > 0:
                assert not m.Lib.has_occurred(d, s, inc, s, T, R)
            # with the include flag resolved, the period is (start, end] or [start, end)
            incl = T if T != -1 else inc
            if incl:
                assert (per == 0 or s <= d) and (per == n_t or d < e)
            else:
                assert (per == 0 or s < d) and (per == n_t or d <= e)
    finally:
        set_flags(m, 0, -1, -1)


@pytest.mark.parametrize("which", ["coverage", "monthly"])
def test_bond_cf_table(m, monthly_inputs, which):
    m.Data.input_dir = str({"coverage": COVERAGE, "monthly": monthly_inputs}[which])
    keys = m.Data.bond_keys()
    exp = {}
    for b, per, k, a in zip(m.Legs.cf_owner_arr().tolist(), m.Proj.bucket_arr().tolist(),
                            m.Legs.cf_kind_arr().tolist(), m.Legs.cf_amount_arr().tolist()):
        exp.setdefault((b, per), [0.0, 0.0, 0.0])[k] += a
    df = m.Proj.bond_cf_table()
    assert list(df.columns) == ["bond_key", "per", "coupon", "amortization", "redemption"]
    rows = sorted(exp)
    assert df["bond_key"].tolist() == [keys[b] for b, _ in rows]
    assert df["per"].tolist() == [per for _, per in rows]
    for j, col in enumerate(("coupon", "amortization", "redemption")):
        assert same(df[col].tolist(), [exp[r][j] for r in rows]), col
    # the portfolio total of each period and kind, across bonds (another order: T2)
    bs = m.Proj.bucket_sums()
    for per in range(m.Data.n_times() + 1):
        for j, col in enumerate(("coupon", "amortization", "redemption")):
            tot = 0.0
            for v in df.loc[df["per"] == per, col].tolist():
                tot += v
            assert_t2(tot, float(bs[per, j]), f"per {per} {col}")


def test_period_table(m):
    m.Data.input_dir = str(DEMO)
    df = m.Proj.period_table()
    T = m.Data.n_times()
    assert list(df.columns) == ["per", "period_start", "period_end", "coupon", "amortization", "redemption",
                                "total"]
    assert df["per"].tolist() == list(range(T + 1))
    assert df["period_start"].iloc[0] == "" and df["period_end"].iloc[T] == ""
    assert df["period_end"].iloc[0] == "2015-09-16" and df["period_start"].iloc[1] == "2015-09-16"
    assert same(df["total"].tolist(), [m.Proj.total_cf(per) for per in range(T + 1)])
