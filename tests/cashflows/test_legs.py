"""The Legs Space (docs/model-contract.md 4.5): the portfolio leg in CSR form and the cash-flow frame.

The CSR columns are checked against the Bond items they are gathered from
(exactly), the array Cells against the columns (identity, dtype, shape,
C order), ``cashflow_frame()`` against the columns, and ``check_limits()``
against the model-level sizes.
"""

import math

import numpy as np
import pytest

from cashflow_checks import COVERAGE, DEMO, private_model, run_model, same, write_generated

INT_COLS = ("cf_owner", "cf_date", "cf_kind", "cf_coupon_idx", "cf_acc_start", "cf_acc_end", "cf_ref_start",
            "cf_ref_end", "cf_dc", "cf_comp", "cf_freq", "cf_ex_date", "ns_date", "bk_cal", "bk_settle_days", "bk_issue", "bk_maturity",
            "bk_type", "bk_spread_idx", "bk_ydc", "bk_ycomp", "bk_yfreq", "cf_lo", "ns_lo")
FLOAT_COLS = ("cf_amount", "cf_nominal", "cf_rate", "cf_accrual_period", "ns_notional", "bk_face")


@pytest.fixture(scope="module")
def m():
    model = private_model("LegsTest")
    yield model
    model.close()


def expected_columns(m):
    """The CSR columns rebuilt here from the Bond items, independently of Legs."""
    cols = {k: [] for k in INT_COLS + FLOAT_COLS}
    cols["cf_lo"].append(0)
    cols["ns_lo"].append(0)
    for b in range(m.Data.n_bonds()):
        mb = m.Bond[b]
        cps, aps = mb.coupons(), mb.accrual_periods()
        for d, kind, amount, ci in mb.leg():
            c = cps[ci] if ci >= 0 else None
            for k, v in (("cf_owner", b), ("cf_date", d), ("cf_kind", kind), ("cf_amount", amount),
                         ("cf_coupon_idx", ci),
                         ("cf_acc_start", c[1] if c else 0), ("cf_acc_end", c[2] if c else 0),
                         ("cf_ref_start", c[3] if c else 0), ("cf_ref_end", c[4] if c else 0),
                         ("cf_dc", c[10] if c else 0), ("cf_comp", c[8] if c else -1),
                         ("cf_freq", c[9] if c else -1), ("cf_ex_date", c[5] if c else 0),
                         ("cf_nominal", c[6] if c else math.nan),
                         ("cf_rate", c[7] if c else math.nan),
                         ("cf_accrual_period", aps[ci] if c else math.nan)):
                cols[k].append(v)
        cols["cf_lo"].append(len(cols["cf_date"]))
        nd, nn = mb.notional_schedule()
        cols["ns_date"].extend(nd)
        cols["ns_notional"].extend(nn)
        cols["ns_lo"].append(len(cols["ns_date"]))
        for k, v in (("bk_cal", mb.calendar()), ("bk_settle_days", mb.settlement_days()),
                     ("bk_issue", mb.issue_date()), ("bk_maturity", mb.maturity_date()),
                     ("bk_type", mb.bond_type()), ("bk_spread_idx", mb.spread_index()),
                     ("bk_ydc", mb.yield_dc()), ("bk_ycomp", mb.yield_comp()), ("bk_yfreq", mb.yield_freq()),
                     ("bk_face", mb.face_amount())):
            cols[k].append(v)
    return cols


@pytest.mark.parametrize("input_dir", [DEMO, COVERAGE], ids=["demo", "coverage"])
def test_leg_columns_gather_the_bond_items(m, input_dir):
    m.Data.input_dir = str(input_dir)
    cols = m.Legs.leg_columns()
    assert set(cols) == set(INT_COLS) | set(FLOAT_COLS)
    exp = expected_columns(m)
    for k in INT_COLS:
        assert cols[k].dtype == np.int64, k
        assert cols[k].tolist() == exp[k], k
    for k in FLOAT_COLS:
        assert cols[k].dtype == np.float64, k
        assert same(cols[k].tolist(), exp[k]), k
    N, P = m.Data.n_bonds(), m.Legs.n_flows()
    assert type(P) is int and P == len(exp["cf_date"])
    for k in cols:
        n = N + 1 if k in ("cf_lo", "ns_lo") else (N if k.startswith("bk_") else None)
        if n is not None:
            assert cols[k].shape == (n,), k
        elif k.startswith("cf_"):
            assert cols[k].shape == (P,), k
    assert cols["ns_date"].shape == cols["ns_notional"].shape == (int(cols["ns_lo"][-1]),)


def test_array_cells_are_the_columns(m):
    m.Data.input_dir = str(COVERAGE)
    cols = m.Legs.leg_columns()
    for k in cols:
        a = getattr(m.Legs, k + "_arr")()
        assert a is cols[k], k
        assert a.flags["C_CONTIGUOUS"], k


def test_cashflow_frame(m):
    m.Data.input_dir = str(COVERAGE)
    cols = m.Legs.leg_columns()
    df = m.Legs.cashflow_frame()
    assert list(df.columns) == ["bond_key", "flow", "kind", "date", "amount", "nominal", "rate", "accrual_start",
                                "accrual_end", "ref_start", "ref_end", "accrual_period"]
    P = m.Legs.n_flows()
    assert len(df) == P
    keys = m.Data.bond_keys()
    kinds = ("coupon", "amortizing", "redemption")
    import datetime

    def iso(d):
        return "" if d == 0 else (datetime.date(1899, 12, 30) + datetime.timedelta(days=int(d))).isoformat()

    for p in range(P):
        b = int(cols["cf_owner"][p])
        r = df.iloc[p]
        assert r["bond_key"] == keys[b]
        assert r["flow"] == p - int(cols["cf_lo"][b])
        assert r["kind"] == kinds[int(cols["cf_kind"][p])]
        assert r["date"] == iso(cols["cf_date"][p])
        for c, k in (("accrual_start", "cf_acc_start"), ("accrual_end", "cf_acc_end"),
                     ("ref_start", "cf_ref_start"), ("ref_end", "cf_ref_end")):
            assert r[c] == iso(cols[k][p])
    for c, k in (("amount", "cf_amount"), ("nominal", "cf_nominal"), ("rate", "cf_rate"),
                 ("accrual_period", "cf_accrual_period")):
        assert same(df[c].tolist(), cols[k].tolist()), c


def test_check_limits(tmp_path):
    model = private_model("LegsLimits")
    try:
        model.Data.input_dir = str(COVERAGE)
        assert model.Legs.check_limits() is True
        most = int(np.diff(model.Legs.leg_columns()["cf_lo"]).max())
        model.MAX_SCHED = most - 1
        out = run_model(model.Legs.check_limits)
        assert out[0] == "err" and out[1] is ValueError and f"flows exceed MAX_SCHED ({most - 1})" in out[2]
        model.MAX_SCHED = 1200
        model.MAX_FLOWS = model.Legs.n_flows() - 1
        out = run_model(model.Legs.check_limits)
        assert out[0] == "err" and "flows exceed MAX_FLOWS" in out[2]
    finally:
        model.close()


def test_generated_portfolio_legs(tmp_path):
    """Legs over a generated portfolio: CSR consistent with the Bond items, frame complete."""
    write_generated(tmp_path, 300, 99)
    model = private_model("LegsGen")
    try:
        model.Data.input_dir = str(tmp_path)
        cols = model.Legs.leg_columns()
        exp = expected_columns(model)
        for k in INT_COLS:
            assert cols[k].tolist() == exp[k], k
        for k in FLOAT_COLS:
            assert same(cols[k].tolist(), exp[k]), k
        assert model.Legs.check_limits() is True
        assert len(model.Legs.cashflow_frame()) == model.Legs.n_flows() == int(cols["cf_lo"][-1])
    finally:
        model.close()
