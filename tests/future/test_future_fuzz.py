"""Fuzz at future valuation dates (plan Phase 3 exit, Verification L5): the model == pureql, bit for bit.

~10,000 random (bond, valuation date) pairs from two ``generate_inputs.py``
portfolios (``pureql_val.FUZZ_SETS``): a long grid of 60 dates from 2000 to
2064 that sees every bond before issue, alive and after maturity, and a dense
grid of 90 dates 4 days apart that lands on coupon and maturity dates, the
days around them and weekends. Both curve types, extrapolation on and off,
random curve and spread conventions, bonds with and without a spread. The
sample is stratified by event class (``pureql_val.pair_category``): a flow on
the valuation date, a flow in the following week (so in (v, s] for T+n
bonds), maturity close to v, v before issue, expired.

For every pair the model's ``Valuation[scen_id, t]`` outputs (every per-bond
output, ``first_live`` / ``pv_base`` / ``pv_sprd`` / ``zdisc_npv`` per role,
and the ``*_from_z`` prices at a random z) are compared EXACTLY (floats bit
for bit and of type ``float``, NaN-aware; a pureql raise must be the same
``ValueError`` message) with

* pureql's explicit-date form (no evaluation date; ``s_t =
  bond.settlementDate(v_t)``, ``CashFlows.npv(leg, curve, flag, v_t, v_t)``,
  ``BondFunctions.*(bond, curve, s_t)``), and
* pureql's Settings-moved engine form (``Settings.evaluationDate = v_t``, a
  ``DiscountingBondEngine`` and the no-argument ``Bond`` methods),

separately (``pureql_val.two_form_mismatches``); the two forms are also
checked against each other (a harness defect would show as ``HARNESS``).

By default the first 3,000 pairs run (1,800 long + 1,200 dense); the full
10,000 run under ``slow``. The QuantLib 1.41 subset is in
``test_future_oracle.py``.
"""

import pytest

from helpers import pureql_val as pv
from helpers.pureql_val import CATEGORIES, FUZZ_DEFAULT, FUZZ_PAIRS, FUZZ_SETS

CHUNK = 300


def chunks(slow):
    out = []
    for name in sorted(FUZZ_SETS):
        lo, hi = (FUZZ_DEFAULT[name], FUZZ_PAIRS[name]) if slow else (0, FUZZ_DEFAULT[name])
        for k in range(lo, hi, CHUNK):
            out.append((name, k, min(k + CHUNK, hi)))
    return out


def run_chunk(model, pairs):
    bad = []
    items = {}
    for s, t, b, z, cat in pairs:
        item = items.get((s, t))
        if item is None:
            item = items[(s, t)] = model.Valuation[s, t]
        got, _ = pv.two_form_mismatches(model, item, s, t, b, (z,), ctx=f"({s}, {t}) b={b} [{cat}]")
        bad += got
    return bad


@pytest.mark.parametrize("name,lo,hi", chunks(False), ids=[f"{n}-{a}" for n, a, _ in chunks(False)])
def test_fuzz(fuzz_models, fuzz_pairs, name, lo, hi):
    pv.report_mismatches(run_chunk(fuzz_models[name], fuzz_pairs[name][lo:hi]), f"fuzz {name} [{lo}:{hi}]")


@pytest.mark.slow
@pytest.mark.parametrize("name,lo,hi", chunks(True), ids=[f"{n}-{a}" for n, a, _ in chunks(True)])
def test_fuzz_full(fuzz_models, fuzz_pairs, name, lo, hi):
    pv.report_mismatches(run_chunk(fuzz_models[name], fuzz_pairs[name][lo:hi]), f"fuzz {name} [{lo}:{hi}]")


def test_fuzz_sample_covers_the_cases(fuzz_models, fuzz_pairs):
    """The default sample is only as good as its cases: check that they are there (pureql, no model Cells).

    Both curve types, extrapolation on and off, with and without spread,
    every event class, expired / non-tradable / forward-start points, and a
    flow in (v, s]. Curve range errors are not required here (the
    generated curves reach 60Y); the edge grid has them.
    """
    seen = set()
    for name, m in fuzz_models.items():
        for s, t, b, z, cat in fuzz_pairs[name][:FUZZ_DEFAULT[name]]:
            c = pv.curve_inputs(m, s, t)
            seen.add(("curve", c["type"]))
            seen.add(("extrapolate", c["extrap"]))
            seen.add(("cat", cat))
            raw = pv.pq_values_explicit(m, s, t, b)["bond"]
            seen.add(("spread", raw["has_spread"][1]))
            seen.add(("expired", raw["is_expired"][1]))
            seen.add(("tradable", raw["is_tradable"][1]))
            if raw["settle"][1] == int(m.Legs.bk_issue_arr()[b]) and raw["settle"][1] > c["vdate"]:
                seen.add(("forward start",))
            lo, hi = int(m.Legs.cf_lo_arr()[b]), int(m.Legs.cf_lo_arr()[b + 1])
            if any(c["vdate"] < int(m.Legs.cf_date_arr()[p]) <= raw["settle"][1] for p in range(lo, hi)):
                seen.add(("flow in (v, s]",))
    want = {("curve", 0), ("curve", 1), ("extrapolate", 0), ("extrapolate", 1), ("spread", True),
            ("spread", False), ("expired", True), ("expired", False), ("tradable", True), ("tradable", False),
            ("forward start",), ("flow in (v, s]",)}
    want |= {("cat", c) for c in CATEGORIES}
    assert want <= seen, f"the fuzz sample misses {want - seen}"


def test_fuzz_sizes(fuzz_pairs):
    """~10,000 pairs in all (plan Phase 3 exit), distinct within each set."""
    assert sum(len(p) for p in fuzz_pairs.values()) == 10000
    for name, pairs in fuzz_pairs.items():
        assert len({(t, b) for _, t, b, _, _ in pairs}) == len(pairs) == FUZZ_PAIRS[name]
