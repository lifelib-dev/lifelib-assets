"""Identities across valuation dates (plan Phase 3 exit, Verification L6): tier T2, no QuantLib oracle.

The input set (:func:`write_identity_inputs`): the headline bond with and
without a spread plus 80 ``generate_inputs.py`` bonds, 45 valuation dates
97 days apart from 16-Sep-2015 (to 2027), two scenarios:

1. ``FlatForward(v_t, r, Actual365Fixed, Continuous)`` with the SAME r = 3.25%
   at every t, and constant zero spreads with Continuous spread compounding.
   On this family the curve at t is the t = 0 curve rolled forward: for
   d >= v_t, ``D_t(d) = D_0(d) / D_0(v_t)`` (exactly in real arithmetic; to
   rounding in floating point), and a spread curve is again such a flat
   curve at r + z.
2. The same with r = 0 and every spread 0: every discount factor is exactly
   1.0, so NPVs are plain sums of the live amounts.

**Forward-implied identity** (scenario 1). For every bond and t with a
tradable settlement date s_t, the model's ``dirty_price`` at t equals
pureql's ``BondFunctions.dirtyPrice(bond, curve_0, s_t)``: the forward price
from the t = 0 curve (the spreaded curve_0 for a spread bond); likewise
``clean_price`` and, for a live bond, ``npv`` against ``CashFlows.npv(leg,
curve_0, flag, v_t, v_t)``. T2 (relative 1e-12, absolute floor 1e-14); the
exploration measured a maximum relative error of 3.9e-16 over 45 dates.

**Roll-forward identity against the Proj buckets** (scenario 1). With
``bucket(p)`` from ``Proj.bucket_arr`` (the first t at which flow p has
occurred for the engine) and the engine curve ``D_{t-1}`` at t-1, for every
bond and t = 1..T-1::

    NPV_{t-1} = sum_{p of the bond, bucket(p) = t} amount_p * D_{t-1}(d_p)
                + D_{t-1}(v_t) * NPV_t

Why it holds, and the conventions it needs (spelled out because they are
QuantLib's, not the model's):

* ``NPV_t`` is ``Bond.NPV()`` at v_t: the DiscountingBondEngine sums the flows
  NOT occurred at v_t under ``hasOccurred(v_t, F if F set else R)`` with the
  includeTodaysCashFlows override (the reference date IS the evaluation date),
  divided by ``D_t(v_t) = 1``. ``Proj.bucket_arr`` uses exactly this
  predicate (the ENGINE role), so bucket t holds the flows live at v_{t-1}
  and occurred at v_t, and buckets > t the flows live at v_t.
* ``Instrument.NPV()`` is 0 when the bond is expired, and ``isExpired`` uses
  the include flag None, i.e. R (the EXPIRY role), not F. The identity
  therefore holds for every (R, T) when F is None or F == R; when F is set
  and differs from R, a bond whose last flow falls ON a valuation date is
  expired for the instrument but still live for the engine, and the
  identity breaks by exactly that flow
  (:func:`test_roll_forward_breaks_when_f_differs_from_r` pins it; model
  == pureql there).
* The settlement date plays no role: NPV is taken at v_t, not s_t.

**Zero-rate reconciliation** (scenario 2). With every discount factor 1.0 the
roll-forward is undiscounted, so the portfolio NPV reconciles with the
aggregated buckets: ``npv_total_{t-1} = Proj.total_cf(t) + npv_total_t``,
``npv_total_0 = sum_{per >= 1} total_cf(per)`` and ``npv_total_{T-1} =
total_cf(T)`` (the open bucket); per bond against ``Proj.bond_cf_table``.

Plus the bucket convention itself: ``Proj.bucket_arr`` == the first t at which
pureql's ``CashFlow.hasOccurred(v_t, engine flag)`` holds with
``Settings.evaluationDate = v_t`` (exact), under several flag sets.
"""

import datetime

import pytest

from helpers import pureql_val as pv
from helpers.approx import T2_ABSOLUTE, T2_RELATIVE, soft
from helpers.pureql_ref import pq_date, ql, serial
from pureql.cashflows.cashflows import CashFlows
from pureql.pricingengines.bond.bondfunctions import BondFunctions

N_GEN, GEN_SEED = 80, 20261014
N_DATES, BASE, STEP_DAYS = 45, "2015-09-16", 97
RATE = "0.0325"
SPREADS = {"AAA": "0.002", "AA": "0.004", "A": "0.007", "BBB": "0.012", "BB": "0.025", "S": "0.01"}
SCEN_FWD, SCEN_ZERO_RATE = 1, 2

HEADLINE = {"bond_key": "HEADLINE_10Y", "bond_type": "FixedRate", "face_amount": "100", "settlement_days": "3",
            "calendar": "TARGET", "issue_date": "2015-09-15", "redemption": "100",
            "effective_date": "2015-09-15", "termination_date": "2025-09-15", "tenor": "6M",
            "convention": "Unadjusted", "termination_convention": "Unadjusted", "rule": "Backward",
            "end_of_month": "0", "coupon_rate": "0.04", "accrual_day_counter": "Thirty360.BondBasis",
            "payment_convention": "Following"}
#: (R, T, F) sets with F None or F == R, where the roll-forward identity holds (the first three by default).
CONSISTENT_FLAGS = [(0, -1, -1), (0, 1, -1), (1, -1, 1), (1, -1, -1), (1, 0, -1), (0, 0, -1), (1, 1, -1),
                    (0, -1, 0), (1, 1, 1)]


def flag_params(flag_sets, n_default):
    """``pytest.param`` per (R, T, F); all but the first ``n_default`` are ``slow``."""
    return [pytest.param(f, id="R{}-T{}-F{}".format(*f), marks=() if k < n_default else pytest.mark.slow)
            for k, f in enumerate(flag_sets)]


def vdates():
    b = datetime.date.fromisoformat(BASE)
    return [(b + datetime.timedelta(days=STEP_DAYS * k)).isoformat() for k in range(N_DATES)]


def write_identity_inputs(out):
    gen = pv.generator()
    tables = gen.generate(N_GEN, 1, 1, GEN_SEED)
    bonds = [HEADLINE, dict(HEADLINE, bond_key="HEADLINE_10Y_SPRD", spread_id="S")] + list(tables["bonds.csv"][1])
    params, spreads = [], []
    for t in range(N_DATES):
        for s, rate, zero in ((SCEN_FWD, RATE, False), (SCEN_ZERO_RATE, "0", True)):
            params.append({"scen_id": str(s), "t": str(t), "curve_type": "FlatForward",
                           "day_counter": "Actual365Fixed", "compounding": "Continuous", "frequency": "Annual",
                           "extrapolate": "0", "flat_rate": rate, "spread_compounding": "Continuous",
                           "spread_frequency": ""})
            for sid, z in SPREADS.items():
                spreads.append({"scen_id": str(s), "t": str(t), "spread_id": sid, "spread": "0" if zero else z})
    return pv.write_inputs(out, bonds, vdates(), params, (), spreads, tables["coupon_rates.csv"][1])


@pytest.fixture(scope="module")
def ident_inputs(tmp_path_factory):
    return write_identity_inputs(tmp_path_factory.mktemp("future_identities"))


@pytest.fixture(scope="module")
def m(set_model, ident_inputs):
    return set_model("identities", ident_inputs)


def engine_curve(model, scen_id, t, b):
    """pureql's engine curve of bond ``b`` at (scen_id, t): the plain curve, or ZeroSpreaded on it."""
    c = pv.curve_inputs(model, scen_id, t)
    curve = pv.pq_curve(model, scen_id, t, c)
    z = pv.bond_spread(model, scen_id, t, b)
    return curve if z is None else pv.pq_spreaded(curve, z, c["sp_comp"], c["sp_freq"])


def t2_ok(a, b):
    bound = max(T2_ABSOLUTE, T2_RELATIVE * max(abs(a), abs(b)))
    return abs(a - b) <= bound


def rel_err(a, b):
    scale = max(abs(a), abs(b))
    return 0.0 if a == b else abs(a - b) / scale


# --------------------------------------------------------------------------- the inputs
def test_identity_inputs(m):
    """One flat Act365F Continuous rate at every t (and 0 in scenario 2); constant Continuous spreads."""
    assert m.Data.n_times() == N_DATES and m.Data.n_bonds() == N_GEN + 2
    for t in range(N_DATES):
        for s, r in ((SCEN_FWD, float(RATE)), (SCEN_ZERO_RATE, 0.0)):
            c = pv.curve_inputs(m, s, t)
            assert (c["type"], c["dc"], c["comp"], c["flat"], c["sp_comp"]) == (pv.CURVE_FLAT, 2, 2, r, 2)
    n_spread = sum(1 for b in range(m.Data.n_bonds()) if pv.bond_spread(m, SCEN_FWD, 0, b) is not None)
    assert 10 < n_spread < m.Data.n_bonds()


# --------------------------------------------------------------------------- forward-implied
def test_forward_implied_prices(m):
    """dirty / clean at t == BondFunctions on the t = 0 curve at s_t; NPV at t == CashFlows.npv on it at v_t (T2)."""
    worst = 0.0
    compared = 0
    with soft("forward-implied identity") as s, pv.pq_settings():
        for b in range(m.Data.n_bonds()):
            bond = pv.pq_bond(m, b)
            leg = bond.cashflows()
            curve0 = engine_curve(m, SCEN_FWD, 0, b)
            for t in range(N_DATES):
                item = m.Valuation[SCEN_FWD, t]
                v = pq_date(int(m.Data.val_date_arr()[t]))
                st = bond.settlementDate(v)
                key = f"b={b} {m.Data.bond_keys()[b]} t={t}"
                if BondFunctions.isTradable(bond, st):
                    for cell, fn in (("dirty_price", BondFunctions.dirtyPrice),
                                     ("clean_price", BondFunctions.cleanPrice)):
                        want = fn(bond, curve0, st)
                        got = pv.model_cells(item, cell)(b)
                        s.check(t2_ok(got, want), f"{key} {cell}: model {got!r} vs forward {want!r}")
                        worst = max(worst, rel_err(got, want))
                        compared += 1
                if not CashFlows.isExpired(leg, False, v):
                    want = CashFlows.npv(leg, curve0, False, v, v)
                    got = pv.model_cells(item, "npv")(b)
                    s.check(t2_ok(got, want), f"{key} npv: model {got!r} vs forward {want!r}")
                    worst = max(worst, rel_err(got, want))
                    compared += 1
    assert compared > 3000, compared
    assert worst <= T2_RELATIVE, worst


def test_forward_implied_headline_dates(m):
    """The headline bond at all 45 dates: the forward identity on dirty price (the exploration's measurement)."""
    b = 0
    with pv.pq_settings():
        bond = pv.pq_bond(m, b)
        curve0 = engine_curve(m, SCEN_FWD, 0, b)
        errs = []
        for t in range(N_DATES):
            v = pq_date(int(m.Data.val_date_arr()[t]))
            st = bond.settlementDate(v)
            if not BondFunctions.isTradable(bond, st):
                continue
            errs.append(rel_err(pv.model_cells(m.Valuation[SCEN_FWD, t], "dirty_price")(b),
                                BondFunctions.dirtyPrice(bond, curve0, st)))
    assert len(errs) == 38  # 16-Sep-2015 + 97k days, k = 0..37: settlement before the 15-Sep-2025 maturity
    assert max(errs) <= T2_RELATIVE, max(errs)


# --------------------------------------------------------------------------- the buckets are the engine occurrence
@pytest.mark.parametrize("flag_values", [(0, -1, -1), (1, -1, -1), (0, 1, -1), (1, 0, -1), (0, -1, 1), (1, -1, 0)],
                         ids=lambda f: "R{}-T{}-F{}".format(*f))
def test_buckets_are_the_engine_occurrence(new_model, ident_inputs, flag_values):
    """``Proj.bucket_arr()[p]`` == the first t with pureql ``cf.hasOccurred(v_t, F or R)``, Settings at v_t (exact)."""
    R, T, F = flag_values
    mm = new_model("FutureBuckets", ident_inputs, include_reference_date_events=R, include_todays_cashflows=T,
                   engine_include_settlement_flows=F)
    inc = bool(F if F != -1 else R)
    legs = [pv.pq_bond(mm, b).cashflows() for b in range(mm.Data.n_bonds())]
    flows = [cf for leg in legs for cf in leg]
    want = [N_DATES] * len(flows)
    for t in reversed(range(N_DATES)):
        v = int(mm.Data.val_date_arr()[t])
        with pv.pq_settings(v, R, T):
            for p, cf in enumerate(flows):
                if cf.hasOccurred(pq_date(v), inc):
                    want[p] = t
    got = [int(x) for x in mm.Proj.bucket_arr().tolist()]
    assert len(got) == len(want)
    bad = [p for p in range(len(got)) if got[p] != want[p]]
    assert not bad, f"{len(bad)} buckets differ, e.g. p={bad[0]}: model {got[bad[0]]} vs pureql {want[bad[0]]}"
    assert len(set(got)) > N_DATES // 2  # the buckets are spread over the dates


# --------------------------------------------------------------------------- roll-forward against the buckets
def roll_forward_residuals(model, scen_id):
    """{(b, t): (lhs, rhs)} of the roll-forward identity for t = 1..T-1, from the model and pureql curves."""
    owner = model.Legs.cf_owner_arr().tolist()
    dates = model.Legs.cf_date_arr().tolist()
    amounts = model.Legs.cf_amount_arr().tolist()
    bucket = model.Proj.bucket_arr().tolist()
    by_bond = {}
    for p in range(len(owner)):
        by_bond.setdefault(owner[p], []).append(p)
    vd = model.Data.val_date_arr().tolist()
    out = {}
    with pv.pq_settings():
        for b in range(model.Data.n_bonds()):
            npvs = [pv.model_cells(model.Valuation[scen_id, t], "npv")(b) for t in range(len(vd))]
            for t in range(1, len(vd)):
                curve = engine_curve(model, scen_id, t - 1, b)
                rhs = 0.0
                for p in by_bond[b]:
                    if bucket[p] == t:
                        rhs += amounts[p] * curve.discount(pq_date(dates[p]))
                rhs += curve.discount(pq_date(vd[t])) * npvs[t]
                out[(b, t)] = (npvs[t - 1], rhs)
    return out


@pytest.mark.parametrize("flag_values", flag_params(CONSISTENT_FLAGS, 1))
def test_roll_forward_identity(new_model, ident_inputs, flag_values):
    """NPV_{t-1} == bucket-t flows discounted on the t-1 curve + D_{t-1}(v_t) * NPV_t, every bond and t (T2)."""
    R, T, F = flag_values
    mm = new_model("FutureRoll", ident_inputs, include_reference_date_events=R, include_todays_cashflows=T,
                   engine_include_settlement_flows=F)
    res = roll_forward_residuals(mm, SCEN_FWD)
    keys = mm.Data.bond_keys()
    with soft(f"roll-forward R={R} T={T} F={F}") as s:
        for (b, t), (lhs, rhs) in res.items():
            s.check(t2_ok(lhs, rhs), f"{keys[b]} t={t}: NPV_(t-1) {lhs!r} vs roll-forward {rhs!r}")
    nontrivial = sum(1 for lhs, rhs in res.values() if lhs != 0.0)
    assert nontrivial > 1000, nontrivial


def test_roll_forward_spans_the_events(m):
    """The identity is not vacuous: buckets with coupons, redemptions, expiries and forward starts all occur."""
    bucket = m.Proj.bucket_arr().tolist()
    kind = m.Legs.cf_kind_arr().tolist()
    assert any(0 < bucket[p] < N_DATES and kind[p] == 0 for p in range(len(bucket)))
    assert any(0 < bucket[p] < N_DATES and kind[p] == 2 for p in range(len(bucket)))
    assert any(x == 0 for x in bucket) and any(x == N_DATES for x in bucket)
    issue = m.Legs.bk_issue_arr().tolist()
    assert any(issue[b] > int(m.Data.val_date_arr()[N_DATES // 2]) for b in range(m.Data.n_bonds()))


# --------------------------------------------------------------------------- zero rates: the aggregated buckets
@pytest.mark.parametrize("flag_values", flag_params([(0, -1, -1), (1, 0, 1), (1, -1, -1), (0, 1, -1)], 1))
def test_zero_rate_roll_forward_against_proj_totals(new_model, ident_inputs, flag_values):
    """With every discount factor 1.0: npv_total_(t-1) == Proj.total_cf(t) + npv_total_t, and the end buckets (T2)."""
    R, T, F = flag_values
    mm = new_model("FutureZeroRate", ident_inputs, include_reference_date_events=R, include_todays_cashflows=T,
                   engine_include_settlement_flows=F)
    totals = [pv.model_cells(mm.Valuation[SCEN_ZERO_RATE, t], "npv_total")() for t in range(N_DATES)]
    cf = [mm.Proj.total_cf(per) for per in range(N_DATES + 1)]
    with soft(f"zero-rate totals R={R} T={T} F={F}") as s:
        for t in range(1, N_DATES):
            s.check(t2_ok(totals[t - 1], cf[t] + totals[t]),
                    f"t={t}: npv_total {totals[t - 1]!r} vs total_cf {cf[t]!r} + npv_total {totals[t]!r}")
        tail = 0.0
        for per in range(1, N_DATES + 1):
            tail += cf[per]
        s.check(t2_ok(totals[0], tail), f"npv_total_0 {totals[0]!r} vs sum of buckets 1..T {tail!r}")
        s.check(t2_ok(totals[N_DATES - 1], cf[N_DATES]),
                f"npv_total_(T-1) {totals[N_DATES - 1]!r} vs open bucket {cf[N_DATES]!r}")
    assert cf[0] > 0.0 and cf[N_DATES] > 0.0 and sum(1 for x in cf[1:N_DATES] if x > 0.0) > N_DATES // 2


def test_zero_rate_roll_forward_per_bond(m):
    """Per bond against ``Proj.bond_cf_table``: NPV_(b,t-1) == bucket-t amounts of b + NPV_(b,t) (T2)."""
    table = m.Proj.bond_cf_table()
    keys = list(m.Data.bond_keys())
    amounts = {}
    for row in table.itertuples(index=False):
        amounts[(row.bond_key, int(row.per))] = row.coupon + row.amortization + row.redemption
    with soft("zero-rate per bond") as s:
        for b, key in enumerate(keys):
            npvs = [pv.model_cells(m.Valuation[SCEN_ZERO_RATE, t], "npv")(b) for t in range(N_DATES)]
            for t in range(1, N_DATES):
                rhs = amounts.get((key, t), 0.0) + npvs[t]
                s.check(t2_ok(npvs[t - 1], rhs), f"{key} t={t}: NPV {npvs[t - 1]!r} vs {rhs!r}")
            s.check(t2_ok(npvs[N_DATES - 1], amounts.get((key, N_DATES), 0.0)), f"{key}: open bucket")


# --------------------------------------------------------------------------- where the identity does NOT hold
def test_roll_forward_breaks_when_f_differs_from_r(new_model, tmp_path):
    """F = True, R = False, a zero maturing ON v_1: the instrument is expired (R), the engine still counts the flow (F).

    ``Proj.bucket_arr`` puts the redemption in bucket 2 (the engine's
    predicate, F), while ``npv`` is 0.0 at v_1 (``isExpired`` uses R): the
    zero-rate roll-forward misses exactly the redemption at t = 1 and at
    t = 2. That is QuantLib's behaviour (the model == pureql, both forms),
    which is why the identity is asserted only for F None or F == R.
    """
    bonds = [{"bond_key": "ZCB_ON_V1", "bond_type": "ZeroCoupon", "face_amount": "100", "settlement_days": "0",
              "calendar": "NullCalendar", "issue_date": "2015-01-05", "maturity_date": "2016-01-05",
              "payment_convention": "Unadjusted"}]
    vds = ["2015-07-06", "2016-01-05", "2016-07-05"]
    params = [{"scen_id": "1", "t": str(t), "curve_type": "FlatForward", "day_counter": "Actual365Fixed",
               "compounding": "Continuous", "extrapolate": "0", "flat_rate": "0"} for t in range(3)]
    d = pv.write_inputs(tmp_path, bonds, vds, params)
    mm = new_model("FutureBreak", d, include_reference_date_events=0, engine_include_settlement_flows=1)
    assert [int(x) for x in mm.Proj.bucket_arr().tolist()] == [2]
    npvs = []
    for t in range(3):
        item = mm.Valuation[1, t]
        got, _ = pv.two_form_mismatches(mm, item, 1, t, 0, (0.0,), ctx=f"t={t}")
        assert not got, got
        npvs.append(pv.model_cells(item, "npv")(0))
    redemption = float(mm.Legs.cf_amount_arr()[0])
    assert pv.model_cells(mm.Valuation[1, 1], "is_expired")(0)
    assert pv.model_cells(mm.Valuation[1, 1], "first_live")(0, pv.ROLE_ENGINE) == 0  # live for the engine
    assert npvs == [redemption, 0.0, 0.0]
    cf = [mm.Proj.total_cf(per) for per in range(4)]
    assert cf == [0.0, 0.0, redemption, 0.0]
    assert npvs[0] - (cf[1] + npvs[1]) == redemption       # t = 1 misses the redemption ...
    assert npvs[1] - (cf[2] + npvs[2]) == -redemption      # ... and t = 2 counts it once too often
