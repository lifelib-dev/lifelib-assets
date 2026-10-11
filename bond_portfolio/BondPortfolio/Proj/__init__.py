# modelx: pseudo-python
# This file is part of a modelx model.
# It can be imported as a Python module, but functions defined herein
# are model formulas and may not be executable as standard Python.

"""Cash flows bucketed into projection periods.

A flow falls in the period in which it leaves the NPV set, using the
same occurrence rule as the valuation.

Derived from QuantLib (BSD-3-Clause); see NOTICE.md."""

from modelx.serialize.jsonvalues import *

_formula = None

_bases = []

_allow_none = None

_spaces = []

# ---------------------------------------------------------------------------
# Cells

def engine_include():
    """The include flag of the ENGINE occurrence role: F if set, else R (tri-state, -1 = None).

    ``includeSettlementDateFlows_ ? *includeSettlementDateFlows_ :
    Settings::includeReferenceDateEvents()``, with F =
    ``data.engine_include_settlement_flows`` and R =
    ``data.include_reference_date_events``.

    Derived from QuantLib (BSD-3-Clause); see NOTICE.md.
    """
    # ported from pureql/pricingengines/bond/discountingbondengine.py (ql/discountingbondengine.cpp:36-67), QuantLib v1.43, BSD-3-Clause
    F = data.engine_include_settlement_flows
    R = data.include_reference_date_events
    return F if F != -1 else R


def bucket_arr():
    """The projection period ``per`` of each flow ``p``, int64 [P].

    ``per`` is the first ``t`` in ``0..T-1`` at which the flow has occurred
    for the engine, ``lib.has_occurred(cf_date, v_t, engine_include(), v_t,
    T, R)`` (reference date and evaluation date both ``v_t``, so the
    includeTodaysCashFlows override applies), or ``T`` if it never has.
    Bucket 0 holds the flows already occurred at ``v_0``. The predicate is
    monotone in ``t`` (the valuation dates increase strictly), so ``t`` is
    found by bisection.
    """
    P = legs.n_flows()
    T = data.n_times()
    inc = engine_include()
    todays = data.include_todays_cashflows
    refev = data.include_reference_date_events
    out = np.zeros(P, dtype=np.int64)
    for p in range(P):
        d = int(legs.cf_date_arr()[p])
        lo = 0
        hi = T
        while lo < hi:
            mid = (lo + hi) // 2  # int>=0
            v = int(data.val_date_arr()[mid])
            if lib.has_occurred(d, v, inc, v, todays, refev):
                hi = mid
            else:
                lo = mid + 1
        out[p] = lo
    return out


def bucket_sums():
    """Flow amounts summed by period and kind, float64 [T+1, 3].

    Columns: coupon, amortizing, redemption (``CF_*``). One pass over the
    flows in global order with sequential ``+=``.
    """
    T = data.n_times()
    out = np.zeros((T + 1, 3), dtype=np.float64)
    for p in range(legs.n_flows()):
        out[int(bucket_arr()[p]), int(legs.cf_kind_arr()[p])] += float(legs.cf_amount_arr()[p])
    return out


def coupon_cf(per):
    """Coupons paid in period ``per`` (summed over the portfolio)."""
    return float(bucket_sums()[per, CF_COUPON])


def amortization_cf(per):
    """Amortizing payments in period ``per`` (summed over the portfolio)."""
    return float(bucket_sums()[per, CF_AMORTIZING])


def redemption_cf(per):
    """Redemptions in period ``per`` (summed over the portfolio)."""
    return float(bucket_sums()[per, CF_REDEMPTION])


def total_cf(per):
    """All flows of period ``per``: ``coupon_cf + amortization_cf + redemption_cf``, in that order."""
    return coupon_cf(per) + amortization_cf(per) + redemption_cf(per)


def period_start(per):
    """Start of period ``per``: ``v_{per-1}``, or the null date (0) for period 0.

    Period ``per`` holds the flows that have not occurred at
    ``period_start(per)`` (for ``per >= 1``) and have occurred at
    ``period_end(per)`` (for ``per < T``): with the default flags, the flows
    dated in ``(period_start, period_end]``.
    """
    if per == 0:
        return NULL_DATE
    return int(data.val_date_arr()[per - 1])


def period_end(per):
    """End of period ``per``: ``v_per``, or ``MAX_SERIAL`` for the open period ``T``."""
    if per >= data.n_times():
        return MAX_SERIAL
    return int(data.val_date_arr()[per])


def bond_cf_table():
    """Per-bond period cash flows in long format: one row per (bond, period) that has flows.

    Columns: ``bond_key``, ``per``, ``coupon``, ``amortization``,
    ``redemption``. Rows are in bond then period order; each amount is a
    sequential ``+=`` over the bond's flows in leg order.
    """
    keys = data.bond_keys()
    rows = {}
    order = []
    for p in range(legs.n_flows()):
        bo = int(legs.cf_owner_arr()[p])
        per = int(bucket_arr()[p])
        key = (bo, per)
        if key not in rows:
            rows[key] = [0.0, 0.0, 0.0]
            order.append(key)
        rows[key][int(legs.cf_kind_arr()[p])] += float(legs.cf_amount_arr()[p])
    order.sort()
    bond_key = []
    pers = []
    coupon = []
    amortization = []
    redemption = []
    for key in order:
        bond_key.append(keys[key[0]])
        pers.append(key[1])
        coupon.append(rows[key][CF_COUPON])
        amortization.append(rows[key][CF_AMORTIZING])
        redemption.append(rows[key][CF_REDEMPTION])
    return pd.DataFrame({
        "bond_key": bond_key,
        "per": np.array(pers, dtype=np.int64),
        "coupon": np.array(coupon, dtype=np.float64),
        "amortization": np.array(amortization, dtype=np.float64),
        "redemption": np.array(redemption, dtype=np.float64),
    })


def period_table():
    """Portfolio cash flows per period ``0..T``, with the period bounds in ISO format.

    Columns: ``per``, ``period_start``, ``period_end`` (blank for the null
    date and for the open end of period ``T``), ``coupon``,
    ``amortization``, ``redemption``, ``total``.
    """
    base = datetime.date(1899, 12, 30)
    rows = []
    for per in range(data.n_times() + 1):
        s = period_start(per)
        e = period_end(per)
        rows.append([
            per,
            (base + datetime.timedelta(days=s)).isoformat() if s != NULL_DATE else "",
            (base + datetime.timedelta(days=e)).isoformat() if per < data.n_times() else "",
            coupon_cf(per), amortization_cf(per), redemption_cf(per), total_cf(per)])
    return pd.DataFrame(rows, columns=["per", "period_start", "period_end", "coupon",
                                       "amortization", "redemption", "total"])


# ---------------------------------------------------------------------------
# References

data = ("Interface", ("..", "Data"), "auto")

lib = ("Interface", ("..", "Lib"), "auto")

dates = ("Interface", ("..", "Dates"), "auto")

legs = ("Interface", ("..", "Legs"), "auto")
