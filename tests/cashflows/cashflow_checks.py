"""Shared checks of the cash-flow tests: one model bond against its pureql twin.

Everything is compared EXACTLY: ints and dates with ``==``, floats bit for
bit with the same Python type (NaN matches NaN), errors by type and message
(pureql's ``Error`` is the model's ``ValueError``).
"""

import importlib.util
import itertools
import math
import pathlib
import struct

import modelx as mx
from modelx.core.errors import FormulaError

from helpers.model import MODEL_DIR
from helpers.pureql_ref import (
    BOND_ZERO,
    bond_inputs,
    pq_bond,
    pq_calendar,
    pq_coupon_records,
    pq_daycounter,
    pq_leg_records,
    pq_notional_schedule,
    pq_schedule,
    pq_schedule_record,
    ql,
    serial,
)

ROOT = MODEL_DIR.parents[1]
DEMO = ROOT / "bond_portfolio"
COVERAGE = ROOT / "tools" / "cy" / "sample_inputs"

_spec = importlib.util.spec_from_file_location("generate_inputs", DEMO / "generate_inputs.py")
gen = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gen)

_COUNT = itertools.count()


def private_model(prefix="CashflowTest"):
    """A model instance of its own (the caller closes it)."""
    return mx.read_model(MODEL_DIR, name=f"{prefix}{next(_COUNT)}")


def run_model(fn, *args):
    """("ok", value) or ("err", type, message) with the ORIGINAL exception of a formula."""
    try:
        return ("ok", fn(*args))
    except FormulaError:
        e = mx.get_error()
        return ("err", type(e), str(e))


def run_pq(fn, *args):
    """("ok", value) or ("err", type, message); pureql's Error maps to ValueError."""
    try:
        return ("ok", fn(*args))
    except ql.Error as e:
        return ("err", ValueError, str(e))


def same(a, b):
    """Exact equality with the same Python type; floats bit for bit, NaN-aware; tuples element-wise."""
    if isinstance(a, (tuple, list)) and isinstance(b, (tuple, list)):
        return len(a) == len(b) and all(same(x, y) for x, y in zip(a, b))
    if type(a) is not type(b):
        return False
    if isinstance(a, float):
        if math.isnan(a):
            return math.isnan(b)
        return struct.pack("<d", a) == struct.pack("<d", b)
    return a == b


def model_leg_records(mb):
    """The model bond's leg in the shape of ``pq_leg_records``."""
    cps = mb.coupons()
    aps = mb.accrual_periods()
    out = []
    for d, kind, amount, ci in mb.leg():
        if ci >= 0:
            c = cps[ci]
            out.append((d, kind, amount, c[1], c[2], c[3], c[4], c[6], c[7], aps[ci]))
        else:
            out.append((d, kind, amount, 0, 0, 0, 0, None, None, None))
    return out


def model_coupon_records(mb):
    """The model bond's coupons with the day-counter code replaced by the pureql name.

    In the order of ``bond.cashflows()``: the build order stable-sorted by
    payment date (they differ only for a schedule whose dates are not
    increasing, which pureql builds as well).
    """
    recs = [c[:10] + (pq_daycounter(c[10]).name(),) for c in mb.coupons()]
    return sorted(recs, key=lambda r: r[0])


def pq_schedule_full(model, b, x):
    """``(dates, is_regular, meta)`` of the pureql schedule, ``meta`` in the order of the model's tuple."""
    s = pq_schedule(model, b, x)
    sdates, sreg = pq_schedule_record(s)
    meta = (1, s.tenor().length(), int(s.tenor().units()), s.calendar().name(),
            int(s.businessDayConvention()), int(s.terminationDateBusinessDayConvention()),
            int(s.rule()), int(s.endOfMonth()))
    return (sdates, sreg, meta)


def model_schedule_full(mb):
    ms = mb.schedule()
    return (ms[0], ms[1], ms[2:5] + (pq_calendar(ms[5]).name(),) + ms[6:10])


def bond_mismatches(model, b):
    """Every difference between ``model.Bond[b]`` and the pureql bond built from the same inputs.

    Returns a list of messages (empty when the two agree exactly). Each
    quantity is compared as an outcome: both sides give the same value, or
    both raise the same error. When pureql refuses to construct the bond,
    the model's ``schedule()`` (Schedule errors) or ``leg()`` must raise the
    same error. pureql computes coupon amounts lazily, so a coupon whose
    amount raises fails ``leg`` on both sides (the model's leg holds the
    amounts) while the schedule, the coupons and the notionals still compare.
    """
    x = bond_inputs(model, b)
    key = model.Data.bond_keys()[b]
    mb = model.Bond[b]
    errs = []

    def check(what, mv, pv):
        if same(mv, pv):
            return
        if isinstance(mv, (tuple, list)) and isinstance(pv, (tuple, list)):
            for i, (u, v) in enumerate(zip(mv, pv)):
                if not same(u, v):
                    errs.append(f"{key} {what}[{i}]: model {u!r} vs pureql {v!r}")
                    return
            errs.append(f"{key} {what}: lengths {len(mv)} (model) vs {len(pv)} (pureql)")
            return
        errs.append(f"{key} {what}: model {mv!r} vs pureql {pv!r}")

    def check_outcome(what, mo, po):
        if mo[0] != po[0] or (mo[0] == "err" and (mo[1] is not po[1] or mo[2] != po[2])):
            errs.append(f"{key} {what}: model {mo!r:.300} vs pureql {po!r:.300}")
        elif mo[0] == "ok":
            check(what, mo[1], po[1])

    pq = run_pq(pq_bond, model, b, x)
    if pq[0] == "err":
        check_outcome("construction", run_model(mb.leg), pq)
        return errs
    bond = pq[1]

    if x["type"] != BOND_ZERO:
        check_outcome("schedule", run_model(model_schedule_full, mb), run_pq(pq_schedule_full, model, b, x))
    else:
        check("schedule (none)", mb.schedule()[0:2], ((), ()))
    check("calendar", pq_calendar(mb.calendar()).name(), bond.calendar().name())
    check_outcome("coupons", run_model(model_coupon_records, mb), run_pq(pq_coupon_records, bond))
    leg_outcome = run_model(model_leg_records, mb)
    check_outcome("leg", leg_outcome, run_pq(pq_leg_records, bond))
    check_outcome("notional schedule", run_model(mb.notional_schedule), run_pq(pq_notional_schedule, bond))
    check("maturity", mb.maturity_date(), serial(bond.maturityDate()))
    if leg_outcome[0] == "ok":
        check("n_flows", mb.n_flows(), len(bond.cashflows()))
    check("issue date", mb.issue_date(), serial(bond.issueDate()))
    check("settlement days", mb.settlement_days(), bond.settlementDays())
    return errs


def portfolio_mismatches(model, input_dir, free_items=False):
    """``bond_mismatches`` over every bond of ``input_dir``; Bond items are deleted as they go if asked."""
    model.Data.input_dir = str(input_dir)
    errs = []
    for b in range(model.Data.n_bonds()):
        errs.extend(bond_mismatches(model, b))
        if free_items:
            del model.Bond[b]
    return errs


def write_generated(out, n_bonds, seed, n_scen=1, n_times=2):
    """A generated input set (generate_inputs.py) in ``out``."""
    gen.write_tables(out, gen.generate(n_bonds, n_scen, n_times, seed))
    return pathlib.Path(out)


# --------------------------------------------------------------------------- adversarial bonds
FUZZ_TENORS = ("0D", "1D", "2D", "5D", "1W", "2W", "3W", "4W", "1M", "2M", "3M", "4M", "5M", "6M",
               "7M", "12M", "13M", "18M", "24M", "1Y", "2Y", "3Y")


def fuzz_tables(seed, n_bonds):
    """Random bonds that reach the corners of Schedule and FixedRateLeg, and their error paths.

    Unlike generate_inputs.py (whose bonds are all constructible), these
    rows mix month ends, February ends, day and week tenors, first and
    next-to-last dates anywhere around the schedule (including out of
    range and equal to the ends), every convention pair, the end-of-month
    flag on any tenor, very short schedules, a few Forward and Zero rules,
    step-up vectors and ZeroCoupon bonds. Returned as generate_inputs
    tables (one scenario, one date: only bonds.csv and coupon_rates.csv
    matter here).
    """
    import datetime
    import numpy as np

    rng = np.random.default_rng(seed)

    def pick(seq):
        return seq[int(rng.integers(0, len(seq)))]

    def u():
        return float(rng.random())

    def month_end(d):
        return gen.month_end(d)

    bonds, coupon_rows = [], []
    for i in range(n_bonds):
        key = f"F{i + 1:06d}"
        row = dict.fromkeys(gen.BOND_COLUMNS, "")
        row["bond_key"] = key
        row["face_amount"] = pick(("100", "1000", "250000"))
        row["settlement_days"] = str(int(rng.integers(0, 4)))
        row["calendar"] = pick(gen.CALENDARS)
        if u() < 0.15:
            row["redemption"] = pick(("99.5", "101", "100", "0"))
        if u() < 0.1:
            row["bond_type"] = "ZeroCoupon"
            mat = datetime.date(1990, 1, 1) + datetime.timedelta(days=int(rng.integers(0, 365 * 60)))
            if u() < 0.3:
                mat = month_end(mat)
            row["maturity_date"] = mat.isoformat()
            row["issue_date"] = (mat - datetime.timedelta(days=int(rng.integers(1, 3000)))).isoformat() \
                if u() < 0.8 else ""
            row["payment_convention"] = pick(gen.BDCS) if u() < 0.8 else ""
            bonds.append(row)
            continue
        row["bond_type"] = "FixedRate"
        tenor = pick(FUZZ_TENORS)
        unit = tenor[-1]
        eff = datetime.date(1990, 1, 1) + datetime.timedelta(days=int(rng.integers(0, 365 * 50)))
        r = u()
        if r < 0.3:
            eff = month_end(eff)
        elif r < 0.4:
            eff = datetime.date(eff.year, 2, pick((27, 28)))
        if unit == "D":
            span = int(rng.integers(1, 120))
        elif unit == "W":
            span = int(rng.integers(1, 700))
        else:
            span = int(rng.integers(1, 365 * 12)) if u() < 0.9 else int(rng.integers(1, 60))
        term = eff + datetime.timedelta(days=span)
        if u() < 0.3 and unit in ("M", "Y"):
            term = month_end(term)
        row["effective_date"] = eff.isoformat()
        row["termination_date"] = term.isoformat()
        row["tenor"] = tenor
        row["convention"] = pick(gen.BDCS)
        row["termination_convention"] = pick(gen.BDCS) if u() < 0.6 else ""
        r = u()
        row["rule"] = "Backward" if r < 0.9 else ("Forward" if r < 0.95 else "Zero")
        row["end_of_month"] = "1" if u() < 0.35 else ("0" if u() < 0.5 else "")
        if u() < 0.25:
            fd = eff + datetime.timedelta(days=int(rng.integers(-20, span + 20)))
            if u() < 0.3:
                fd = month_end(fd)
            if u() < 0.1:
                fd = eff
            row["first_date"] = fd.isoformat()
        if u() < 0.25:
            nd = term - datetime.timedelta(days=int(rng.integers(-20, span + 20)))
            if u() < 0.3:
                nd = month_end(nd)
            if u() < 0.1:
                nd = term
            row["next_to_last_date"] = nd.isoformat()
        if u() < 0.15:
            for k in range(int(rng.integers(1, 6))):
                coupon_rows.append({"bond_key": key, "k": str(k), "rate": gen.fmt_rate(0.01 + 0.005 * k)})
        else:
            row["coupon_rate"] = gen.fmt_rate(0.00125 * int(rng.integers(0, 80)))
        row["accrual_day_counter"] = pick(gen.DAY_COUNTERS)
        if u() < 0.2:
            row["first_period_day_counter"] = pick(gen.DAY_COUNTERS)
        row["payment_convention"] = pick(gen.BDCS) if u() < 0.8 else ""
        if u() < 0.2:
            row["payment_calendar"] = pick(gen.CALENDARS)
        row["issue_date"] = eff.isoformat() if u() < 0.7 else ""
        bonds.append(row)
    tables = gen.generate(1, 1, 1, 1)
    tables["bonds.csv"] = (gen.BOND_COLUMNS, bonds)
    tables["coupon_rates.csv"] = (gen.COUPON_RATE_COLUMNS, coupon_rows)
    return tables


def fuzz_mismatches(model, b):
    """``bond_mismatches``, except that a rule other than Backward on a non-zero tenor must raise v1's error."""
    x = bond_inputs(model, b)
    if x["type"] != BOND_ZERO and x["tenor_n"] != 0 and x["rule"] not in (0, 2):
        mo = run_model(model.Bond[b].leg)
        expected = ("err", ValueError, "rule not supported in this model version")
        if mo[0] != "err" or mo[1] is not ValueError or mo[2] != expected[2]:
            # the checks that precede the rule test may raise first, as in pureql
            pq = run_pq(pq_bond, model, b, x)
            if not (pq[0] == "err" and mo[0] == "err" and mo[2] == pq[2]):
                return [f"{model.Data.bond_keys()[b]}: rule {x['rule']} gives {mo}"]
        return []
    return bond_mismatches(model, b)
