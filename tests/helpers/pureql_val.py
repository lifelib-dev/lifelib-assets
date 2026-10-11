"""pureql values of the Valuation space (docs/model-contract.md 4.7), for TESTS ONLY.

An independent oracle for ``Valuation[scen_id, t]``: every number is computed
by pureql from the model's OWN parsed inputs (``model.Data`` arrays, and the
bond built by :func:`helpers.pureql_ref.pq_bond`), so that a mismatch points at
the Valuation transcription and not at CSV parsing (tested in
``tests/unit/test_data.py``) or leg generation (``tests/cashflows``).

Two independent pureql computations of the same outputs:

**(A) Settings-moved, engine form** (:func:`pq_values_engine`). Inside
:func:`pq_settings`, which saves and EXACTLY restores pureql's process state,
``Settings.evaluationDate = vdate`` and the two flags R/T come from
``model.Data``; a ``DiscountingBondEngine`` on the plain or the spreaded curve
(``includeSettlementDateFlows`` from F) prices the bond and the no-argument
methods are read: ``NPV()``, ``settlementValue()``, ``dirtyPrice()``,
``cleanPrice()``, ``accruedAmount()``, ``settlementDate()``, ``notional()``,
``isExpired()``. This is what quantlib-migration's README headline does.

**(B) explicit-date form** (:func:`pq_values_explicit`). No evaluation date:
``s = bond.settlementDate(vdate)``, ``CashFlows.npv(leg, curve, flag, vdate,
vdate)``, ``CashFlows.npv(leg, curve, False, s, s)``,
``BondFunctions.dirtyPrice/cleanPrice(bond, curve, s)``,
``bond.accruedAmount(s)``, ``bond.notional(s)``,
``CashFlows.isExpired(leg, R, vdate)``. R and F are passed as explicit
arguments. The one setting no explicit argument can carry is
``includeTodaysCashFlows`` (T): ``CashFlow.hasOccurred`` overrides the flag
from the setting whenever the reference date IS the evaluation date
(``cashflow.cpp:35-41``; pureql's own STATE READ note says so). So (B) never
moves the evaluation date when T is -1 (None), and sets ``evaluationDate =
vdate`` plus T when T is set. In both cases the Settings flag R is forced to
its default (False): (B) passes R explicitly, so a leak of the setting into
it would show up as an (A) != (B) mismatch whenever R = 1.

:func:`pq_bond_values` runs both and asserts that (A) and (B) agree BIT FOR BIT
on every output both compute (:func:`form_mismatches`), as a self-check of
the harness, then returns (A).

Every output is an *outcome*: ``("ok", value)`` or ``("err", type,
message)``, with pureql's ``Error`` mapped to ``ValueError`` (contract 3.6).
"""

from __future__ import annotations

import itertools
import math
import struct
from contextlib import contextmanager

from helpers.pureql_ref import (  # noqa: F401  (ql re-exported for the tests)
    BOND_ZERO,
    pq_bond,
    pq_comp,
    pq_date,
    pq_daycounter,
    pq_freq,
    ql,
    serial,
)
from pureql import _state
from pureql.cashflows.cashflows import CashFlows
from pureql.handle import Handle
from pureql.math.interpolations.linearinterpolation import Linear
from pureql.pricingengines.bond.bondfunctions import BondFunctions
from pureql.pricingengines.bond.discountingbondengine import DiscountingBondEngine
from pureql.quote import Quote
from pureql.quotes.simplequote import SimpleQuote
from pureql.termstructures.yield_.flatforward import FlatForward
from pureql.termstructures.yield_.zerocurve import ZeroCurve
from pureql.termstructures.yield_.zerospreadedtermstructure import ZeroSpreadedTermStructure
from pureql.termstructures.yieldtermstructure import YieldTermStructure

# model codes (docs/model-contract.md section 2)
CURVE_ZERO, CURVE_FLAT = 0, 1
ROLE_ENGINE, ROLE_SETTLE, ROLE_EXPIRY = 0, 1, 2
ROLES = (ROLE_ENGINE, ROLE_SETTLE, ROLE_EXPIRY)
NT_ENGINE, NT_RAISE = 0, 1
MAX_SERIAL = 109574

#: tri-state code -> pureql optional<bool>
TRI = {-1: None, 0: False, 1: True}

#: The outputs per bond that both forms compute and that must agree bitwise.
BOND_KEYS = (
    "settle", "notional_s", "is_tradable", "is_expired", "has_spread", "spread",
    "npv", "npv_base", "settlement_value", "accrued_cash", "accrued_amount",
    "dirty_price", "clean_price", "market_value",
)
#: Outputs per (bond, role).
ROLE_KEYS = ("first_live", "pv_base", "pv_sprd", "zdisc_npv")
#: Outputs per (bond, z).
Z_KEYS = ("pv_z", "dirty_from_z", "clean_from_z")


# --------------------------------------------------------------------------- outcomes
def run_pq(fn, *args):
    """("ok", value) or ("err", type, message); pureql's Error maps to ValueError."""
    try:
        return ("ok", fn(*args))
    except ql.Error as e:
        return ("err", ValueError, str(e))
    except (ArithmeticError, ValueError) as e:  # e.g. OverflowError, ZeroDivisionError
        return ("err", type(e), str(e))


def ok(value):
    return ("ok", value)


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


def same_outcome(a, b):
    """Two outcomes agree: same kind; an error by type and message; a value by :func:`same`."""
    if a[0] != b[0]:
        return False
    if a[0] == "err":
        return a[1] is b[1] and a[2] == b[2]
    return same(a[1], b[1])


def show(outcome):
    if outcome[0] == "err":
        return f"raises {outcome[1].__name__}({outcome[2]!r})"
    v = outcome[1]
    return f"{v!r} ({type(v).__name__})"


# --------------------------------------------------------------------------- inputs (from model.Data)
def flags(model):
    """(R, T, F) from the model's Data References."""
    d = model.Data
    return (int(d.include_reference_date_events), int(d.include_todays_cashflows),
            int(d.engine_include_settlement_flows))


def curve_inputs(model, scen_id, t):
    """The (scen_id, t) curve inputs as plain Python values, read from ``model.Data``."""
    d = model.Data
    r = scen_id - 1
    lo, cnt = int(d.n_lo_arr()[r, t]), int(d.n_cnt_arr()[r, t])
    return {
        "vdate": int(d.val_date_arr()[t]),
        "type": int(d.c_type_arr()[r, t]),
        "dc": int(d.c_dc_arr()[r, t]),
        "comp": int(d.c_comp_arr()[r, t]),
        "freq": int(d.c_freq_arr()[r, t]),
        "extrap": int(d.c_extrap_arr()[r, t]),
        "flat": float(d.c_flat_arr()[r, t]),
        "sp_comp": int(d.c_sp_comp_arr()[r, t]),
        "sp_freq": int(d.c_sp_freq_arr()[r, t]),
        "node_lo": lo,
        "node_dates": [int(d.n_date_arr()[lo + k]) for k in range(cnt)],
        "node_rates": [float(d.n_rate_arr()[lo + k]) for k in range(cnt)],
    }


def bond_spread(model, scen_id, t, b):
    """The zero spread of bond ``b`` at (scen_id, t), or None for a plain-curve bond."""
    d = model.Data
    idx = int(d.b_spread_idx_arr()[b])
    if idx < 0:
        return None
    return float(d.sp_arr()[scen_id - 1, t, idx])


# --------------------------------------------------------------------------- curves
def pq_curve(model, scen_id, t, c=None):
    """The pureql curve of (scen_id, t), with its reference date at ``val_date(t)``.

    FlatForward: ``FlatForward(vdate, rate, dc, comp, freq)`` (the fixed-date,
    bare-``Rate`` form, ``flatforward.cpp:37-44``). ZeroCurve: the
    seven-argument form ``ZeroCurve(dates, rates, dc, NullCalendar(), Linear(),
    comp, freq)`` (``zerocurve.hpp:55-62``, the form the 1.41 oracle binds);
    its reference date is ``dates[0]``. ``enableExtrapolation()`` when the
    input says so.
    """
    c = curve_inputs(model, scen_id, t) if c is None else c
    dc = pq_daycounter(c["dc"])
    if c["type"] == CURVE_FLAT:
        curve = FlatForward(pq_date(c["vdate"]), float(c["flat"]), dc, pq_comp(c["comp"]), pq_freq(c["freq"]))
    elif c["type"] == CURVE_ZERO:
        curve = ZeroCurve([pq_date(x) for x in c["node_dates"]], list(c["node_rates"]), dc,
                          ql.NullCalendar(), Linear(), pq_comp(c["comp"]), pq_freq(c["freq"]))
    else:
        raise ValueError(f"unknown curve type {c['type']}")
    if c["extrap"]:
        curve.enableExtrapolation()
    return curve


def pq_spreaded(curve, z, comp, freq):
    """``ZeroSpreadedTermStructure(Handle(curve), Handle(SimpleQuote(z)), comp, freq)``.

    Built exactly as ``CashFlows.npv``'s z-spread form builds it
    (``cashflows.cpp:1146-1175``), with codes for ``comp`` and ``freq``.
    """
    return ZeroSpreadedTermStructure(Handle[YieldTermStructure](curve), Handle[Quote](SimpleQuote(float(z))),
                                     pq_comp(comp), pq_freq(freq))


# --------------------------------------------------------------------------- Settings
@contextmanager
def pq_settings(vdate=None, R=0, T=-1):
    """pureql Settings for one computation, restored EXACTLY afterwards.

    ``_state.snapshot_all`` / ``restore_all`` rather than ``SavedSettings``:
    the latter stores the EFFECTIVE evaluation date and so leaves an unset
    date anchored to today (QUIRK Q-08), as ``tests/unit/test_lib.py`` notes.
    ``vdate=None`` leaves the evaluation date untouched.
    """
    before = _state.snapshot_all()
    try:
        s = ql.Settings.instance()
        if vdate is not None:
            s.setEvaluationDate(pq_date(vdate))
        s.setIncludeReferenceDateEvents(bool(R))
        s.setIncludeTodaysCashFlows(TRI[int(T)])
        yield s
    finally:
        _state.restore_all(before)


# --------------------------------------------------------------------------- bond values
def _first_live(leg, lo, ref, include):
    """``lo`` + the index of the first flow of ``leg`` that has NOT occurred at ``ref``."""
    for i, cf in enumerate(leg):
        if not cf.hasOccurred(ref, include):
            return lo + i
    return lo + len(leg)


def _setup(model, scen_id, t, b, c=None):
    c = curve_inputs(model, scen_id, t) if c is None else c
    spread = bond_spread(model, scen_id, t, b)
    lo = int(model.Legs.cf_lo_arr()[b])
    return c, spread, lo


def _nt(outcome, policy):
    """The model's NT policy (contract 4.7) applied to a pureql ``*_from_z`` outcome.

    pureql raises "non tradable at ..." when N == 0. Under NT_ENGINE the model
    returns 0.0 there instead; under NT_RAISE it raises pureql's message.
    """
    if policy == NT_ENGINE and outcome[0] == "err" and outcome[2].startswith("non tradable at "):
        return ("ok", 0.0)
    return outcome


def pq_values_engine(model, scen_id, t, b, zs=(), c=None, flag_values=None):
    """(A): the Settings-moved, engine-form pureql values of bond ``b`` at (scen_id, t).

    Returns ``{"bond": {key: outcome}, "role": {(key, role): outcome},
    "z": {(key, z): outcome}}`` with the RAW pureql outcomes (the NT policy is
    applied by :func:`expected_values`).
    """
    R, T, F = flags(model) if flag_values is None else flag_values
    c, spread, lo = _setup(model, scen_id, t, b, c)
    out_b, out_r, out_z = {}, {}, {}
    with pq_settings(c["vdate"], R, T):
        settings = ql.Settings.instance()
        bond = pq_bond(model, b)
        leg = bond.cashflows()
        try:
            curve = pq_curve(model, scen_id, t, c)
        except ql.Error as e:  # curve construction refused: every curve output raises the same
            curve, curve_err = None, ("err", ValueError, str(e))
        else:
            curve_err = None

        out_b["settle"] = run_pq(lambda: serial(bond.settlementDate()))
        out_b["notional_s"] = run_pq(bond.notional)
        out_b["is_tradable"] = run_pq(bond.isTradable)
        out_b["is_expired"] = run_pq(bond.isExpired)
        out_b["has_spread"] = ok(spread is not None)
        if spread is not None:
            out_b["spread"] = ok(spread)
        out_b["accrued_amount"] = run_pq(bond.accruedAmount)
        s = bond.settlementDate()
        out_b["accrued_cash"] = run_pq(CashFlows.accruedAmount, leg, False, s)

        ev = settings.evaluationDate()
        F_opt = TRI[F]
        engine_flag = F_opt if F_opt is not None else settings.includeReferenceDateEvents()
        out_r[("first_live", ROLE_ENGINE)] = ok(_first_live(leg, lo, ev, engine_flag))
        out_r[("first_live", ROLE_SETTLE)] = ok(_first_live(leg, lo, s, False))
        out_r[("first_live", ROLE_EXPIRY)] = ok(_first_live(leg, lo, ev, None))

        if curve is None:
            for k in ("npv", "npv_base", "settlement_value", "dirty_price", "clean_price", "market_value"):
                out_b[k] = curve_err
            for role in (ROLE_ENGINE, ROLE_SETTLE):
                out_r[("pv_base", role)] = curve_err
                if spread is not None:
                    out_r[("pv_sprd", role)] = curve_err
                    out_r[("zdisc_npv", role)] = curve_err
            for z in zs:
                for k in Z_KEYS:
                    out_z[(k, z)] = curve_err
            return {"bond": out_b, "role": out_r, "z": out_z}

        engine_curve = curve if spread is None else pq_spreaded(curve, spread, c["sp_comp"], c["sp_freq"])
        bond.setPricingEngine(DiscountingBondEngine(Handle[YieldTermStructure](engine_curve), F_opt))
        out_b["npv"] = run_pq(bond.NPV)
        out_b["settlement_value"] = run_pq(bond.settlementValue)
        out_b["dirty_price"] = run_pq(bond.dirtyPrice)
        out_b["clean_price"] = run_pq(bond.cleanPrice)
        out_b["market_value"] = out_b["npv"]  # DECISIONS.md D-4

        # the role values: CashFlows.npv as the engine calls it, dates from Settings
        out_r[("pv_base", ROLE_ENGINE)] = run_pq(CashFlows.npv, leg, curve, engine_flag, ql.Date(), ql.Date())
        out_r[("pv_base", ROLE_SETTLE)] = run_pq(CashFlows.npv, leg, curve, False, s, ql.Date())
        if spread is not None:
            out_r[("pv_sprd", ROLE_ENGINE)] = run_pq(CashFlows.npv, leg, engine_curve, engine_flag,
                                                    ql.Date(), ql.Date())
            out_r[("pv_sprd", ROLE_SETTLE)] = run_pq(CashFlows.npv, leg, engine_curve, False, s, ql.Date())
            out_r[("zdisc_npv", ROLE_ENGINE)] = run_pq(engine_curve.discount, ev)
            out_r[("zdisc_npv", ROLE_SETTLE)] = run_pq(engine_curve.discount, s)

        for z in zs:
            out_z[("pv_z", z)] = run_pq(CashFlows.npv, leg, curve, float(z), pq_comp(c["sp_comp"]),
                                        pq_freq(c["sp_freq"]), False, s, s)
            out_z[("dirty_from_z", z)] = run_pq(BondFunctions.dirtyPrice, bond, curve, float(z),
                                                pq_comp(c["sp_comp"]), pq_freq(c["sp_freq"]))
            out_z[("clean_from_z", z)] = run_pq(BondFunctions.cleanPrice, bond, curve, float(z),
                                                pq_comp(c["sp_comp"]), pq_freq(c["sp_freq"]))

        # npv_base: the same engine on the PLAIN curve (identical to npv for a plain-curve bond)
        if spread is None:
            out_b["npv_base"] = out_b["npv"]
        else:
            bond.setPricingEngine(DiscountingBondEngine(Handle[YieldTermStructure](curve), F_opt))
            out_b["npv_base"] = run_pq(bond.NPV)
    return {"bond": out_b, "role": out_r, "z": out_z}


def pq_values_explicit(model, scen_id, t, b, zs=(), c=None, flag_values=None):
    """(B): the explicit-date pureql values of bond ``b`` at (scen_id, t); see the module docstring."""
    R, T, F = flags(model) if flag_values is None else flag_values
    c, spread, lo = _setup(model, scen_id, t, b, c)
    out_b, out_r, out_z = {}, {}, {}
    # T is the one flag no argument carries; with T unset nothing global is read.
    with pq_settings(c["vdate"] if T != -1 else None, 0, T):
        bond = pq_bond(model, b)
        leg = bond.cashflows()
        v = pq_date(c["vdate"])
        s = bond.settlementDate(v)
        N = bond.notional(s)
        tradable = BondFunctions.isTradable(bond, s)
        engine_flag = bool(F if F != -1 else R)
        expired = CashFlows.isExpired(leg, bool(R), v)

        out_b["settle"] = ok(serial(s))
        out_b["notional_s"] = ok(N)
        out_b["is_tradable"] = ok(tradable)
        out_b["is_expired"] = ok(expired)
        out_b["has_spread"] = ok(spread is not None)
        if spread is not None:
            out_b["spread"] = ok(spread)
        out_b["accrued_amount"] = run_pq(bond.accruedAmount, s)
        out_b["accrued_cash"] = run_pq(CashFlows.accruedAmount, leg, False, s)
        out_r[("first_live", ROLE_ENGINE)] = ok(_first_live(leg, lo, v, engine_flag))
        out_r[("first_live", ROLE_SETTLE)] = ok(_first_live(leg, lo, s, False))
        out_r[("first_live", ROLE_EXPIRY)] = ok(_first_live(leg, lo, v, bool(R)))

        try:
            curve = pq_curve(model, scen_id, t, c)
        except ql.Error as e:  # as in form (A): every curve output raises the same
            err = ("err", ValueError, str(e))
            for k in ("npv", "npv_base", "settlement_value", "dirty_price", "clean_price", "market_value"):
                out_b[k] = err
            for role in (ROLE_ENGINE, ROLE_SETTLE):
                out_r[("pv_base", role)] = err
                if spread is not None:
                    out_r[("pv_sprd", role)] = err
                    out_r[("zdisc_npv", role)] = err
            for z in zs:
                for k in Z_KEYS:
                    out_z[(k, z)] = err
            return {"bond": out_b, "role": out_r, "z": out_z}
        engine_curve = curve if spread is None else pq_spreaded(curve, spread, c["sp_comp"], c["sp_freq"])
        value = run_pq(CashFlows.npv, leg, engine_curve, engine_flag, v, v)
        out_b["npv"] = ok(0.0) if expired else value
        out_b["market_value"] = out_b["npv"]
        base = run_pq(CashFlows.npv, leg, curve, engine_flag, v, v)
        out_b["npv_base"] = ok(0.0) if expired else base
        sv = run_pq(CashFlows.npv, leg, engine_curve, False, s, s)
        out_b["settlement_value"] = ok(0.0) if expired else sv
        if tradable:
            out_b["dirty_price"] = run_pq(BondFunctions.dirtyPrice, bond, engine_curve, s)
            out_b["clean_price"] = run_pq(BondFunctions.cleanPrice, bond, engine_curve, s)
        else:  # Bond::dirtyPrice() is 0.0 when the notional is 0 (bond.cpp:179-185)
            out_b["dirty_price"] = ok(0.0)
            accr = run_pq(bond.accruedAmount, s)
            out_b["clean_price"] = ok(0.0 - accr[1]) if accr[0] == "ok" else accr

        out_r[("pv_base", ROLE_ENGINE)] = base
        out_r[("pv_base", ROLE_SETTLE)] = run_pq(CashFlows.npv, leg, curve, False, s, s)
        if spread is not None:
            out_r[("pv_sprd", ROLE_ENGINE)] = value
            out_r[("pv_sprd", ROLE_SETTLE)] = sv
            out_r[("zdisc_npv", ROLE_ENGINE)] = run_pq(engine_curve.discount, v)
            out_r[("zdisc_npv", ROLE_SETTLE)] = run_pq(engine_curve.discount, s)

        for z in zs:
            out_z[("pv_z", z)] = run_pq(CashFlows.npv, leg, pq_spreaded(curve, z, c["sp_comp"], c["sp_freq"]),
                                        False, s, s)
            out_z[("dirty_from_z", z)] = run_pq(BondFunctions.dirtyPrice, bond, curve, float(z),
                                                pq_comp(c["sp_comp"]), pq_freq(c["sp_freq"]), s)
            out_z[("clean_from_z", z)] = run_pq(BondFunctions.cleanPrice, bond, curve, float(z),
                                                pq_comp(c["sp_comp"]), pq_freq(c["sp_freq"]), s)
    return {"bond": out_b, "role": out_r, "z": out_z}


def form_mismatches(a, b):
    """Every output on which the two forms disagree, as messages (empty when they agree bitwise)."""
    out = []
    for group in ("bond", "role", "z"):
        keys = set(a[group]) | set(b[group])
        for k in sorted(keys, key=repr):
            if k not in a[group] or k not in b[group]:
                out.append(f"{group} {k!r}: computed by one form only")
            elif not same_outcome(a[group][k], b[group][k]):
                out.append(f"{group} {k!r}: engine form {show(a[group][k])} vs explicit form {show(b[group][k])}")
    return out


def pq_bond_values(model, scen_id, t, b, zs=(), c=None, flag_values=None, check_forms=True):
    """The pureql values of bond ``b`` at (scen_id, t): form (A), checked against form (B).

    Raises AssertionError if the two pureql forms disagree (a harness defect,
    not a model one).
    """
    a = pq_values_engine(model, scen_id, t, b, zs, c, flag_values)
    if check_forms:
        x = pq_values_explicit(model, scen_id, t, b, zs, c, flag_values)
        bad = form_mismatches(a, x)
        if bad:
            raise AssertionError(f"pureql harness self-check failed for b={b} at ({scen_id}, {t}):\n  "
                                 + "\n  ".join(bad))
    return a


def expected_values(raw, policy=NT_ENGINE):
    """The model's expected outcomes from raw pureql outcomes: the NT policy applied to ``*_from_z``."""
    out = {"bond": dict(raw["bond"]), "role": dict(raw["role"]), "z": {}}
    for (k, z), o in raw["z"].items():
        out["z"][(k, z)] = _nt(o, policy) if k in ("dirty_from_z", "clean_from_z") else o
    return out


# --------------------------------------------------------------------------- curve values
def pq_curve_values(model, scen_id, t, kds, zs=(), c=None):
    """pureql values of the curve Cells of ``Valuation[scen_id, t]``.

    ``{"ctx": {name: outcome}, "node": {(name, nd): outcome}, "kd": {(name,
    kd): outcome}, "kdz": {(name, kd, z): outcome}}`` for the context Cells,
    the ZeroCurve node Cells, the day-offset Cells and ``zs_discount_kd``.
    ``zero_c`` and ``discount_core`` are given only where the range check
    passes (they are the implementations behind it); ``zs_base`` only for
    ``t > 0``, where the contract defines it.
    """
    c = curve_inputs(model, scen_id, t) if c is None else c
    R, T, F = flags(model)
    curve = pq_curve(model, scen_id, t, c)
    ctx = {
        "vdate": ok(c["vdate"]),
        "srow": ok(scen_id - 1),
        "curve_type": ok(c["type"]),
        "curve_dc": ok(c["dc"]),
        "curve_comp": ok(c["comp"]),
        "curve_freq": ok(c["freq"]),
        "spread_comp": ok(c["sp_comp"]),
        "spread_freq": ok(c["sp_freq"]),
        "curve_extrapolate": ok(bool(c["extrap"])),
        "engine_flag": ok(F if F != -1 else R),
        "todays": ok(T),
        "ref_events": ok(R),
        "max_time": run_pq(curve.maxTime),
        "curve_ok": ok(True),
    }
    node = {}
    if c["type"] == CURVE_FLAT:
        ctx["flat_rate"] = ok(c["flat"])
    else:
        ctx["node_lo"] = ok(c["node_lo"])
        ctx["n_nodes"] = ok(len(c["node_dates"]))
        times = curve.times()
        zc = curve.zeroRates()
        slopes = curve._interpolation._impl._s  # LinearInterpolationImpl.update (linearinterpolation.py:145-171)
        for nd in range(len(c["node_dates"])):
            node[("node_date", nd)] = ok(c["node_dates"][nd])
            node[("node_rate_in", nd)] = ok(c["node_rates"][nd])
            node[("node_time", nd)] = ok(times[nd])
            node[("node_zc", nd)] = ok(zc[nd])
            if nd < len(c["node_dates"]) - 1:
                node[("node_slope", nd)] = ok(slopes[nd])
    kd_out, kdz_out = {}, {}
    for kd in kds:
        d = pq_date(c["vdate"] + kd)
        tt = curve.timeFromReference(d)
        kd_out[("curve_time", kd)] = ok(tt)
        rng = run_pq(curve.checkRange, tt, False)  # as YieldTermStructure.discount(d) calls it
        kd_out[("range_ok", kd)] = ok(True) if rng[0] == "ok" else rng
        kd_out[("discount", kd)] = run_pq(curve.discount, d)
        if rng[0] == "ok":
            kd_out[("discount_core", kd)] = run_pq(curve.discountImpl, tt)
            if c["type"] == CURVE_ZERO:
                kd_out[("zero_c", kd)] = run_pq(curve.zeroYieldImpl, tt)
        if tt > 0.0:
            kd_out[("zs_base", kd)] = run_pq(lambda: curve.zeroRate(tt, pq_comp(c["sp_comp"]),
                                                                    pq_freq(c["sp_freq"]), True).rate())
        for z in zs:
            kdz_out[("zs_discount_kd", kd, z)] = run_pq(pq_spreaded(curve, z, c["sp_comp"], c["sp_freq"]).discount, d)
    return {"ctx": ctx, "node": node, "kd": kd_out, "kdz": kdz_out}


def curve_kds(model, scen_id, t, c=None, extra=()):
    """Day offsets worth probing at (scen_id, t): every live flow date, the nodes and the edges."""
    c = curve_inputs(model, scen_id, t) if c is None else c
    v = c["vdate"]
    kds = {0, 1, 2, 3, 7, 30, 365}
    for d in model.Legs.cf_date_arr().tolist():
        if v <= d:
            kds.add(int(d) - v)
    for d in c["node_dates"]:
        for e in (-1, 0, 1):
            if v <= d + e:
                kds.add(int(d) + e - v)
    if c["node_dates"]:
        last = c["node_dates"][-1] - v
        kds.update({last + 400, last + 3653})
    kds.add(MAX_SERIAL - v)
    kds.update(extra)
    return sorted(k for k in kds if 0 <= k <= MAX_SERIAL - v)


# --------------------------------------------------------------------------- the model, in the same shape
_MODEL_COUNT = itertools.count()


def private_model(prefix, input_dir=None, **refs):
    """A model instance of its own (the caller closes it); ``refs`` are set on ``Data`` before any calculation."""
    import modelx as mx

    from helpers.model import MODEL_DIR
    m = mx.read_model(MODEL_DIR, name=f"{prefix}{next(_MODEL_COUNT)}")
    if input_dir is not None:
        m.Data.input_dir = str(input_dir)
    for k, v in refs.items():
        setattr(m.Data, k, v)
    return m


def run_model(fn, *args):
    """("ok", value) or ("err", type, message) with the ORIGINAL exception of a formula.

    modelx wraps an exception raised inside a formula in a ``FormulaError``;
    ``mx.get_error()`` is the original one.
    """
    import modelx as mx
    from modelx.core.errors import FormulaError
    try:
        return ("ok", fn(*args))
    except FormulaError:
        e = mx.get_error()
        return ("err", type(e), str(e))


def model_cells(item, name):
    """The Cells ``name`` of a Valuation item, or a clear failure naming the contract."""
    if name not in item.cells:
        raise AssertionError(f"Valuation has no Cells {name!r} (docs/model-contract.md 4.7)")
    return item.cells[name]


def model_values(item, b, expected):
    """The model's outcomes for every key of ``expected`` (the shape of :func:`pq_values_engine`)."""
    out = {"bond": {}, "role": {}, "z": {}}
    for k in expected["bond"]:
        out["bond"][k] = run_model(model_cells(item, k), b)
    for k, role in expected["role"]:
        out["role"][(k, role)] = run_model(model_cells(item, k), b, role)
    for k, z in expected["z"]:
        out["z"][(k, z)] = run_model(model_cells(item, k), b, float(z))
    return out


def value_mismatches(got, expected, ctx=""):
    """Messages for every output where the model and pureql differ (bitwise, NaN-aware, same type)."""
    out = []
    for group in ("bond", "role", "z"):
        for k, e in expected[group].items():
            g = got[group].get(k)
            if g is None or not same_outcome(g, e):
                out.append(f"{ctx} {k}: model {show(g) if g else 'missing'}"
                           f" vs pureql {show(e)}")
    return out


# --------------------------------------------------------------------------- goldens
def golden_record(values):
    """A JSON-ready form of :func:`pq_values_engine` output (errors as {"error", "message"})."""
    def enc(o):
        if o[0] == "err":
            return {"error": o[1].__name__, "message": o[2]}
        return o[1]
    return {
        "bond": {k: enc(o) for k, o in values["bond"].items()},
        "role": {f"{k}[{role}]": enc(o) for (k, role), o in values["role"].items()},
        "z": {f"{k}[{z!r}]": enc(o) for (k, z), o in values["z"].items()},
    }


#: The z grid of the frozen goldens (tests/data/pv_*.json).
GOLDEN_Z = (-0.0125, 0.0, 0.0075)


def input_hashes(input_dir):
    """sha256 of every CSV file of an input directory, by file name."""
    import hashlib
    import pathlib
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(pathlib.Path(input_dir).glob("*.csv"))}


def golden_values(model, zs=GOLDEN_Z):
    """pureql's values of every bond at every (scen_id, t) of the model's inputs, JSON-ready.

    ``{"<scen_id>,<t>": {bond_key: golden_record}}`` with the RAW pureql
    outcomes (form A, checked against form B), at the model's Data flags.
    """
    keys = list(model.Data.bond_keys())
    out = {}
    for s in range(1, model.Data.n_scen() + 1):
        for t in range(model.Data.n_times()):
            out[f"{s},{t}"] = {keys[b]: golden_record(pq_bond_values(model, s, t, b, zs))
                               for b in range(len(keys))}
    return out


def write_golden(model, input_dir, path, label, zs=GOLDEN_Z, what_it_is=None, generator=None):
    """Freeze :func:`golden_values` of ``input_dir`` into ``path`` with its provenance block.

    ``zs`` (the z grid of the ``*_from_z`` values), ``what_it_is`` (an extra
    sentence for the provenance) and ``generator`` (the regenerating entry
    point, when it is not this function) are optional; their defaults give
    the Phase 2 files unchanged.
    """
    import datetime
    import json
    import pathlib
    import subprocess

    from helpers.pureql_ref import PUREQL_SRC
    qlm = pathlib.Path(PUREQL_SRC).parent
    try:
        head = subprocess.run(["git", "-C", str(qlm), "rev-parse", "HEAD"], capture_output=True, text=True,
                              check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        head = "unknown"
    R, T, F = flags(model)
    what = (f"pureql values of every bond of the {label} input set at every (scen_id, t): the "
            "contract-4.7 outputs (docs/model-contract.md), computed by tests/helpers/pureql_val.py "
            "in the Settings-moved engine form and checked bit for bit against the explicit-date "
            "form. Raw pureql outcomes: '*_from_z' keep pureql's 'non tradable' raise (the model's "
            "NT_ENGINE policy turns it into 0.0).")
    if what_it_is:
        what = what + " " + what_it_is
    doc = {
        "schema": "bondportfolio-pv-golden/1",
        "provenance": {
            "what_it_is": what,
            "generator": generator or "tests/helpers/pureql_val.py::write_golden",
            "oracle": "pureql (quantlib-migration src/pureql, a port of QuantLib v1.43)",
            "quantlib_migration_head": head,
            "frozen_on": datetime.date.today().isoformat(),
            "input_dir": label,
            "input_sha256": input_hashes(input_dir),
            "flags": {"include_reference_date_events": R, "include_todays_cashflows": T,
                      "engine_include_settlement_flows": F},
            "z_grid": list(zs),
            "role_codes": {"0": "ROLE_ENGINE", "1": "ROLE_SETTLE", "2": "ROLE_EXPIRY"},
            "tier": "exact (bitwise; DECISIONS.md D-2)",
            "licence": "data computed with pureql (BSD-3-Clause, derived from QuantLib); see NOTICE.md",
        },
        "values": golden_values(model, zs),
    }
    pathlib.Path(path).write_text(json.dumps(doc, indent=1, sort_keys=False) + "\n", encoding="utf-8")
    return doc


# --------------------------------------------------------------------------- Phase 3 (future t) additions
# Used by tests/future: input sets written into tmp_path, and the model compared
# with EACH pureql form separately (model == engine form AND model == explicit
# form), so that a mismatch names the form it was found against.
_GENERATOR = None


def generator():
    """The ``bond_portfolio/generate_inputs.py`` module (loaded once, not imported as a package)."""
    global _GENERATOR
    if _GENERATOR is None:
        import importlib.util

        from helpers.model import SAMPLE_INPUTS
        spec = importlib.util.spec_from_file_location("generate_inputs", SAMPLE_INPUTS / "generate_inputs.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _GENERATOR = mod
    return _GENERATOR


def write_inputs(out, bonds, vdates, params, nodes=(), spreads=(), coupon_rates=(), prices=None, yields=None):
    """Write an input set (the schema of ``bond_portfolio/inputs.md``) into ``out``; return ``out``.

    ``bonds``, ``params``, ``nodes``, ``spreads`` and ``coupon_rates`` are
    lists of row dicts (missing columns are blank); ``vdates`` is the list of
    ISO valuation dates, ``t`` = position. ``prices`` and ``yields`` (Phase 4)
    are written to prices.csv / yields.csv only when given.
    """
    gen = generator()
    tables = {
        "bonds.csv": (gen.BOND_COLUMNS, list(bonds)),
        "coupon_rates.csv": (gen.COUPON_RATE_COLUMNS, list(coupon_rates)),
        "valuation_dates.csv": (gen.VAL_DATE_COLUMNS,
                                [{"t": str(t), "val_date": v} for t, v in enumerate(vdates)]),
        "curve_params.csv": (gen.CURVE_PARAM_COLUMNS, list(params)),
        "curve_nodes.csv": (gen.CURVE_NODE_COLUMNS, list(nodes)),
        "spreads.csv": (gen.SPREAD_COLUMNS, list(spreads)),
    }
    if prices is not None:
        tables["prices.csv"] = (gen.PRICE_COLUMNS, list(prices))
    if yields is not None:
        tables["yields.csv"] = (gen.YIELD_COLUMNS, list(yields))
    gen.write_tables(out, tables)
    return out


def two_form_mismatches(model, item, scen_id, t, b, zs=(), policy=NT_ENGINE, flag_values=None, c=None, ctx=""):
    """The model against EACH pureql form, as ``(messages, expected)``.

    Computes form (A) (Settings moved, engine) and form (B) (explicit
    dates) independently; the messages list every output where the model
    differs from (A) (suffix ``[engine form]``) or from (B) (suffix
    ``[explicit form]``), and every output where (A) and (B) differ from each
    other (prefix ``HARNESS``: a defect of the oracle, not of the model).
    ``expected`` is form (A) with the NT policy applied.
    """
    a = pq_values_engine(model, scen_id, t, b, zs, c, flag_values)
    x = pq_values_explicit(model, scen_id, t, b, zs, c, flag_values)
    out = [f"HARNESS {ctx}: {m}" for m in form_mismatches(a, x)]
    ea, ex = expected_values(a, policy), expected_values(x, policy)
    got = model_values(item, b, ea)
    out += [m + " [engine form]" for m in value_mismatches(got, ea, ctx)]
    out += [m + " [explicit form]" for m in value_mismatches(got, ex, ctx)]
    return out, ea


def report_mismatches(bad, label):
    """Fail once with every mismatch message (the first ones shown), or pass."""
    from helpers.approx import soft
    with soft(label) as s:
        s.checks = len(bad)
        for msg in bad:
            s.error(msg)


def decode_golden(v):
    """A golden JSON value back to an outcome (an error record is ``{"error", "message"}``)."""
    return ("err", ValueError, v["message"]) if isinstance(v, dict) else ("ok", v)


def golden_mismatches(model, values, policy=NT_ENGINE, label=""):
    """The model against frozen :func:`golden_values` (bitwise; the NT policy applied to ``*_from_z``)."""
    keys = list(model.Data.bond_keys())
    bad = []
    for point, recs in values.items():
        s, t = (int(x) for x in point.split(","))
        item = model.Valuation[s, t]
        for key, rec in recs.items():
            b = keys.index(key)
            for k, v in rec["bond"].items():
                e = decode_golden(v)
                g = run_model(model_cells(item, k), b)
                if not same_outcome(g, e):
                    bad.append(f"{label} {point} {key} {k}: model {show(g)} vs golden {show(e)}")
            for kr, v in rec["role"].items():
                k, role = kr[:-3], int(kr[-2])
                e = decode_golden(v)
                g = run_model(model_cells(item, k), b, role)
                if not same_outcome(g, e):
                    bad.append(f"{label} {point} {key} {kr}: model {show(g)} vs golden {show(e)}")
            for kz, v in rec["z"].items():
                k, z = kz.split("[")
                z = float(z[:-1])
                e = decode_golden(v)
                if k in ("dirty_from_z", "clean_from_z"):
                    e = _nt(e, policy)
                g = run_model(model_cells(item, k), b, z)
                if not same_outcome(g, e):
                    bad.append(f"{label} {point} {key} {kz}: model {show(g)} vs golden {show(e)}")
    return bad


# --------------------------------------------------------------------------- Phase 3 fuzz portfolios
#: The generate_inputs.py portfolios of the future-t fuzz (name -> generate() arguments):
#: * ``long``: 60 valuation dates 400 days apart from 2000-01-03 to 2064, so
#:   that every generated bond (effective dates 2000..2030, up to 30Y 11M) is
#:   seen before issue, alive and after maturity, on every weekday;
#: * ``dense``: 90 dates 4 days apart from 2019-12-27, which lands on coupon
#:   and maturity dates, on the days around them, and on weekends.
#: Both curve types (70% ZeroCurve), extrapolation on and off, random curve
#: and spread conventions, ~70% of the bonds with a spread.
FUZZ_SETS = {
    "long": dict(n_bonds=600, n_scen=2, n_times=60, seed=20261012, base="2000-01-03", step="400D"),
    "dense": dict(n_bonds=400, n_scen=2, n_times=90, seed=20261013, base="2019-12-27", step="4D"),
}
#: Pairs per set (10,000 in all), and the prefix of each that runs by default.
FUZZ_PAIRS = {"long": 6000, "dense": 4000}
FUZZ_DEFAULT = {"long": 1800, "dense": 1200}
FUZZ_SEED = 31
#: Share of the sample drawn from each event class of :func:`pair_category` (the rest is uniform).
CATEGORY_SHARE = {"flow_on_v": 0.12, "flow_soon": 0.18, "maturity_soon": 0.08, "before_issue": 0.08,
                  "expired": 0.06}
CATEGORIES = ("flow_on_v", "flow_soon", "maturity_soon", "before_issue", "expired", "alive")


def write_fuzz_inputs(out, name):
    """Write the fuzz portfolio ``name`` of :data:`FUZZ_SETS` into ``out``; return ``out``."""
    gen = generator()
    kw = FUZZ_SETS[name]
    gen.write_tables(out, gen.generate(kw["n_bonds"], kw["n_scen"], kw["n_times"], kw["seed"], kw["base"],
                                       kw["step"]))
    return out


def pair_category(model, b, t, cache):
    """The event class of the (bond ``b``, valuation date ``t``) pair, from the model's leg arrays.

    ``before_issue`` (issue date after v), ``expired`` (the last flow before
    v), ``maturity_soon`` (the last flow in [v-3, v+10]), ``flow_on_v`` (a
    flow dated v), ``flow_soon`` (a flow in (v, v+7], where (v, s] may hold
    it), else ``alive``; the first that applies. ``cache`` is a dict the
    caller keeps between calls.
    """
    import bisect
    if "dates" not in cache:
        cache["dates"] = model.Legs.cf_date_arr().tolist()
        cache["lo"] = model.Legs.cf_lo_arr().tolist()
        cache["issue"] = model.Legs.bk_issue_arr().tolist()
        cache["vd"] = model.Data.val_date_arr().tolist()
    dates, lo = cache["dates"], cache["lo"]
    v = cache["vd"][t]
    flows = dates[lo[b]:lo[b + 1]]
    last = flows[-1]
    if cache["issue"][b] > v:
        return "before_issue"
    if last < v:
        return "expired"
    if v - 3 <= last <= v + 10:
        return "maturity_soon"
    i = bisect.bisect_left(flows, v)
    if i < len(flows) and flows[i] == v:
        return "flow_on_v"
    if i < len(flows) and flows[i] <= v + 7:
        return "flow_soon"
    return "alive"


def sample_pairs(model, n, seed):
    """``n`` distinct (bond, t) pairs as ``(scen_id, t, b, z, category)``, stratified, in a seeded order.

    :data:`CATEGORY_SHARE` of the sample comes from each event class, the
    rest uniformly from all pairs; ``scen_id`` is uniform and ``z`` (for the
    ``*_from_z`` prices) uniform in [-1%, 3%]. The order is a seeded shuffle,
    so any prefix is itself a stratified sample.
    """
    import random
    rng = random.Random(seed)
    cache = {}
    S, T, N = model.Data.n_scen(), model.Data.n_times(), model.Data.n_bonds()
    by_cat = {}
    for b in range(N):
        for t in range(T):
            by_cat.setdefault(pair_category(model, b, t, cache), []).append((b, t))
    chosen = set()
    for cat, share in CATEGORY_SHARE.items():
        pool = by_cat.get(cat, [])
        chosen.update(rng.sample(pool, min(len(pool), int(share * n))))
    everything = [bt for cat in sorted(by_cat) for bt in by_cat[cat]]
    while len(chosen) < n:
        chosen.add(everything[rng.randrange(len(everything))])
    pairs = sorted(chosen)
    rng.shuffle(pairs)
    out = []
    for b, t in pairs:
        s = rng.randint(1, S)
        z = round(rng.uniform(-0.01, 0.03), 6)
        out.append((s, t, b, z, pair_category(model, b, t, cache)))
    return out


# =========================================================================== Phase 4 analytics (contract 4.8)
# The pureql reference of the analytics Cells of ``Valuation[scen_id, t]``
# (docs/model-contract.md 4.8): yields (NewtonSafe and the Brent option),
# z-spreads, the risk measures, prices from a yield, the stepwise npv and its
# step times. Everything is pureql's own PUBLIC entry point with EXPLICIT
# dates, ``s = bond.settlementDate(vdate)``:
#
# * ``BondFunctions.bondYield(bond, Bond.Price(price, type), ydc, ycomp, yfreq,
#   s, accuracy, maxEvaluations, guess)`` (NewtonSafe, v1.43 IrrFinder), and the
#   solver-taking overload ``BondFunctions.bondYield(Brent(), bond, price, ydc,
#   ycomp, yfreq, s, accuracy, guess)`` after ``setMaxEvaluations`` (the form
#   the 1.41 oracle binds as ``yieldBrent``);
# * ``BondFunctions.zSpread(bond, price, curve, spread_comp, spread_freq, s,
#   accuracy, maxEvaluations, guess)`` on the PLAIN curve;
# * ``BondFunctions.duration / convexity / basisPointValue /
#   yieldValueBasisPoint / dirtyPrice / cleanPrice(bond, InterestRate(y, ydc,
#   ycomp, yfreq), [type,] s)``;
# * ``CashFlows.npv / duration / convexity / basisPointValue /
#   yieldValueBasisPoint(leg, InterestRate, False, s, s)`` for the [D] Cells.
#
# The price a yield is solved for is the input price (prices.csv) if there is
# one, else the ENGINE clean price, read from ``bond.cleanPrice()`` with a
# DiscountingBondEngine and Settings moved to vdate (form (A) above), as
# ``Bond.bondYield`` takes it. The whole computation runs inside
# ``pq_settings(vdate, R, T)`` so that the T override of ``hasOccurred``
# applies to the settlement-date flows exactly as in the model's SETTLE role;
# with T unset (the default) nothing global is read by the explicit-date calls.
#
# The model's policies (contract 4.8 "Policies") are applied to pureql's raw
# outcomes here, in ONE place:
# * NT (N == 0): NT_ENGINE gives NaN for ytm, zspread, risk_yield and the risk
#   measures and 0.0 for the prices from a yield; NT_RAISE gives pureql's
#   "non tradable at ..." raise. The [D] ``*_y`` Cells transcribe CashFlows
#   functions, which have no tradability gate, and are compared ungated.
# * ERR: the three solver failures (no bracket, maximum evaluations, checkSign)
#   are NaN under ERR_NAN and pureql's raise under ERR_RAISE; any other error
#   (a curve range error, ...) is raised under both.
# * Macaulay duration with a non-Compounded yield: NaN under ERR_NAN, pureql's
#   "compounded rate required" under ERR_RAISE.
# * zspread needs an input price, or with ``zspread_price_source = 1`` the
#   engine clean price when there is no input price; else NaN (before the NT gate).
# * risk_yield is NT-gated like ytm (NaN under NT_ENGINE, pureql's "non
#   tradable" raise under NT_RAISE, even when an input yield exists), else the
#   input yield if present, else ytm.
from pureql.cashflows.cashflows import IrrFinder, _getStepwiseDiscountTime, _sign  # noqa: E402,F401
from pureql.cashflows.duration import Duration  # noqa: E402
from pureql.instruments.bond import Bond  # noqa: E402
from pureql.interestrate import InterestRate  # noqa: E402
from pureql.math.solvers1d.brent import Brent  # noqa: E402

PRICE_DIRTY, PRICE_CLEAN = 0, 1
COMP_SIMPLE, COMP_COMPOUNDED, COMP_CONTINUOUS, COMP_SIMPLE_THEN_COMPOUNDED, COMP_COMPOUNDED_THEN_SIMPLE = 0, 1, 2, 3, 4
COMPOUNDINGS = (COMP_SIMPLE, COMP_COMPOUNDED, COMP_CONTINUOUS, COMP_SIMPLE_THEN_COMPOUNDED,
                COMP_COMPOUNDED_THEN_SIMPLE)
ERR_RAISE, ERR_NAN = 0, 1
SOLVE_YIELD, SOLVE_ZSPREAD = 0, 1
#: ``Data.yield_solver`` codes. The contract (4.8) names the option but not its
#: codes; 0 is the default and must reproduce ``BondFunctions.bondYield``
#: (NewtonSafe), so the Brent option is taken to be 1.
YIELD_NEWTON, YIELD_BRENT = 0, 1
NAN = float("nan")

#: The analytics References of Data with the contract defaults (4.3).
ANALYTICS_DEFAULTS = {
    "nontradable_policy": NT_ENGINE, "solver_error_policy": ERR_RAISE, "yield_solver": YIELD_NEWTON,
    "yield_accuracy": 1e-10, "yield_max_evaluations": 100, "yield_guess": 0.05,
    "zspread_accuracy": 1e-10, "zspread_max_evaluations": 100, "zspread_guess": 0.0,
    "zspread_price_source": 0,
}

#: The message openings of the solver failures the ERR policy covers.
SOLVER_FAILURES = ("unable to bracket root in ", "maximum number of function evaluations (",
                   "the given cash flows cannot result in the given market price due to their sign")

#: Per-bond analytics Cells [C over b] (contract 4.8), in the order they are reported.
ANALYTICS_BOND_KEYS = (
    "price_in", "price_type_in", "yield_in", "ydc", "ycomp", "yfreq", "y_price", "y_price_type",
    "y_target", "sign_ok", "z_target", "ytm", "zspread", "risk_yield", "duration_simple",
    "duration_modified", "duration_macaulay", "convexity", "bpv", "yvbp", "dirty_at_yield_in",
    "clean_at_yield_in",
)
#: The [D] Cells over (b, y).
ANALYTICS_Y_KEYS = ("npv_yield", "simple_duration_y", "modified_duration_y", "macaulay_duration_y",
                    "convexity_y", "bpv_y", "yvbp_y", "dirty_from_yield", "clean_from_yield")
#: The risk measures [C over b], taken at ``risk_yield(b)``.
RISK_KEYS = ("duration_simple", "duration_modified", "duration_macaulay", "convexity", "bpv", "yvbp")


def _risk_fn(name):
    return {
        "duration_simple": lambda bond, ir, s: BondFunctions.duration(bond, ir, Duration.Simple, s),
        "duration_modified": lambda bond, ir, s: BondFunctions.duration(bond, ir, Duration.Modified, s),
        "duration_macaulay": lambda bond, ir, s: BondFunctions.duration(bond, ir, Duration.Macaulay, s),
        "convexity": BondFunctions.convexity,
        "bpv": BondFunctions.basisPointValue,
        "yvbp": BondFunctions.yieldValueBasisPoint,
    }[name]


def analytics_settings(model, **overrides):
    """The analytics References of ``model.Data`` (contract defaults for any not defined), with overrides."""
    d = model.Data
    out = {k: (getattr(d, k) if hasattr(d, k) else v) for k, v in ANALYTICS_DEFAULTS.items()}
    out.update(overrides)
    return out


def is_solver_failure(outcome):
    return outcome[0] == "err" and outcome[2].startswith(SOLVER_FAILURES)


def err_policy(outcome, err):
    """The ERR policy on a raw pureql solver outcome."""
    if err == ERR_NAN and is_solver_failure(outcome):
        return ("ok", NAN)
    return outcome


def price_type_code(s):
    s = s.strip()
    if s in ("", "Clean"):
        return PRICE_CLEAN
    if s == "Dirty":
        return PRICE_DIRTY
    raise ValueError(f"unknown price type {s!r}")


def quote_inputs(model):
    """The prices and yields of the model's inputs, read from ``Data.price_table()`` / ``yield_table()`` (strings).

    ``{"price": {(scen_id, t, bond_key): (price, type code)}, "yield":
    {(scen_id, t, bond_key): yield}}``; a blank price type is Clean
    (bond_portfolio/inputs.md). Parsed here, independently of the model's
    Phase 4 ``px_*`` / ``yl_*`` arrays, which are tested against it.
    """
    px, yl = {}, {}
    for r in model.Data.price_table().to_dict("records"):
        px[(int(r["scen_id"]), int(r["t"]), r["bond_key"])] = (float(r["price"]),
                                                              price_type_code(r.get("price_type", "")))
    for r in model.Data.yield_table().to_dict("records"):
        yl[(int(r["scen_id"]), int(r["t"]), r["bond_key"])] = float(r["yield"])
    return {"price": px, "yield": yl}


def pq_bond_yield(bond, amount, ptype, dc, comp, freq, s, st):
    """pureql's yield of ``bond`` at a price: NewtonSafe (``bondYield``) or Brent (the solver overload)."""
    price = Bond.Price(float(amount), Bond.Price.Type(int(ptype)))
    if int(st["yield_solver"]) == YIELD_BRENT:
        solver = Brent()
        solver.setMaxEvaluations(int(st["yield_max_evaluations"]))
        return BondFunctions.bondYield(solver, bond, price, dc, comp, freq, s, float(st["yield_accuracy"]),
                                       float(st["yield_guess"]))
    return BondFunctions.bondYield(bond, price, dc, comp, freq, s, float(st["yield_accuracy"]),
                                   int(st["yield_max_evaluations"]), float(st["yield_guess"]))


def pq_zspread(bond, amount, ptype, curve, comp, freq, s, st):
    """``BondFunctions.zSpread`` of ``bond`` at a price over the plain ``curve``."""
    return BondFunctions.zSpread(bond, Bond.Price(float(amount), Bond.Price.Type(int(ptype))), curve,
                                 pq_comp(comp), pq_freq(freq), s, float(st["zspread_accuracy"]),
                                 int(st["zspread_max_evaluations"]), float(st["zspread_guess"]))


def pq_analytics(model, scen_id, t, b, ys=(), settings=None, quotes=None, c=None, flag_values=None,
                 risk_yield=None, steps=True):
    """The pureql values of the contract-4.8 Cells of bond ``b`` at (scen_id, t), with the policies applied.

    ``{"bond": {name: outcome}, "y": {(name, y): outcome}, "p": {("ystep", p):
    outcome}, "k": {("solve", kind): outcome}, "facts": {...}}``. ``ys`` are
    the yields of the [D] Cells; ``settings`` the analytics References
    (default: the model's); ``risk_yield`` an outcome at which to take the
    risk measures INSTEAD of the expected ``risk_yield`` (to check them at the
    model's own yield). ``macaulay_duration_y`` is given for Compounded
    yields only (the model gates the others before the [D] call).
    ``y_target`` and ``sign_ok`` are given for tradable bonds whose price
    exists, ``z_target`` where a z-spread is solved, ``solve`` where pureql's
    solver returns a root.
    """
    st = analytics_settings(model) if settings is None else dict(ANALYTICS_DEFAULTS, **settings)
    R, T, F = flags(model) if flag_values is None else flag_values
    c = curve_inputs(model, scen_id, t) if c is None else c
    q = quote_inputs(model) if quotes is None else quotes
    d = model.Data
    key = d.bond_keys()[b]
    px = q["price"].get((scen_id, t, key))
    yl = q["yield"].get((scen_id, t, key))
    ydc, ycomp, yfreq = int(d.b_ydc_arr()[b]), int(d.b_ycomp_arr()[b]), int(d.b_yfreq_arr()[b])
    nt, err = int(st["nontradable_policy"]), int(st["solver_error_policy"])
    lo = int(model.Legs.cf_lo_arr()[b])
    out_b, out_y, out_p, out_k = {}, {}, {}, {}

    with pq_settings(c["vdate"], R, T):
        bond = pq_bond(model, b)
        leg = bond.cashflows()
        s = bond.settlementDate(pq_date(c["vdate"]))
        tradable = BondFunctions.isTradable(bond, s)
        dc_y, comp_y, freq_y = pq_daycounter(ydc), pq_comp(ycomp), pq_freq(yfreq)
        try:
            curve, curve_err = pq_curve(model, scen_id, t, c), None
        except ql.Error as e:
            curve, curve_err = None, ("err", ValueError, str(e))

        # the engine clean price (Settings moved): the yield target without an input price
        if not tradable:
            clean_engine = ok(0.0)  # Bond::dirtyPrice() is 0.0 at a zero notional, and so is accruedAmount()
        elif curve is None:
            clean_engine = curve_err
        else:
            spread = bond_spread(model, scen_id, t, b)
            engine_curve = curve if spread is None else pq_spreaded(curve, spread, c["sp_comp"], c["sp_freq"])
            bond.setPricingEngine(DiscountingBondEngine(Handle[YieldTermStructure](engine_curve), TRI[F]))
            clean_engine = run_pq(bond.cleanPrice)

        out_b["price_in"] = ok(px[0] if px else NAN)
        out_b["price_type_in"] = ok(px[1] if px else -1)
        out_b["yield_in"] = ok(yl if yl is not None else NAN)
        out_b["ydc"], out_b["ycomp"], out_b["yfreq"] = ok(ydc), ok(ycomp), ok(yfreq)
        yprice = (ok(px[0]), px[1]) if px else (clean_engine, PRICE_CLEAN)
        out_b["y_price"], out_b["y_price_type"] = yprice[0], ok(yprice[1])

        def target(p):
            # bondfunctions.py:1157-1162 / :1526-1528, the same three statements
            amount = p[0][1]
            if p[1] == PRICE_CLEAN:
                amount += bond.accruedAmount(s)
            amount /= 100.0 / bond.notional(s)
            return amount

        sign = None
        if tradable and yprice[0][0] == "ok":
            amount = target(yprice)
            out_b["y_target"] = ok(amount)
            sign = run_pq(IrrFinder, leg, amount, dc_y, comp_y, freq_y, False, s, s)
            out_b["sign_ok"] = ok(sign[0] == "ok") if (sign[0] == "ok" or is_solver_failure(sign)) else sign

        # ytm
        if not tradable:
            ytm = ok(NAN) if nt == NT_ENGINE else run_pq(
                pq_bond_yield, bond, yprice[0][1] if yprice[0][0] == "ok" else 0.0, yprice[1], dc_y, comp_y, freq_y,
                s, st)
        elif yprice[0][0] == "err":
            ytm = yprice[0]
        else:
            raw = run_pq(pq_bond_yield, bond, yprice[0][1], yprice[1], dc_y, comp_y, freq_y, s, st)
            ytm = err_policy(raw, err)
            if raw[0] == "ok":
                out_k[("solve", SOLVE_YIELD)] = raw
        out_b["ytm"] = ytm

        # zspread
        source = int(st["zspread_price_source"])
        zprice = (ok(px[0]), px[1]) if px else ((clean_engine, PRICE_CLEAN) if source == 1 else None)
        if zprice is None:
            zs = ok(NAN)
        elif not tradable:
            zs = ok(NAN) if nt == NT_ENGINE else run_pq(pq_zspread, bond, 0.0, zprice[1], curve, c["sp_comp"],
                                                        c["sp_freq"], s, st)
        elif zprice[0][0] == "err":
            zs = zprice[0]
        else:
            out_b["z_target"] = ok(target(zprice))
            if curve is None:
                zs = curve_err
            else:
                raw = run_pq(pq_zspread, bond, zprice[0][1], zprice[1], curve, c["sp_comp"], c["sp_freq"], s, st)
                zs = err_policy(raw, err)
                if raw[0] == "ok":
                    out_k[("solve", SOLVE_ZSPREAD)] = raw
        out_b["zspread"] = zs

        # risk_yield and the risk measures (NT-gated like ytm: NaN, or pureql's "non tradable" raise)
        if not tradable:
            ry = ytm
        elif yl is not None:
            ry = ok(yl)
        else:
            ry = ytm
        out_b["risk_yield"] = ry
        at = ry if risk_yield is None else risk_yield
        for name in RISK_KEYS:
            if not tradable and nt == NT_ENGINE:
                o = ok(NAN)
            elif at[0] == "err":
                o = at
            elif math.isnan(at[1]):
                o = ok(NAN)
            elif name == "duration_macaulay" and ycomp != COMP_COMPOUNDED and tradable and err == ERR_NAN:
                o = ok(NAN)
            else:
                o = run_pq(_risk_fn(name), bond, InterestRate(float(at[1]), dc_y, comp_y, freq_y), s)
            out_b[name] = o

        # prices at the input yield
        for name, fn in (("dirty_at_yield_in", BondFunctions.dirtyPrice),
                         ("clean_at_yield_in", BondFunctions.cleanPrice)):
            if yl is None:
                out_b[name] = ok(NAN)
            elif not tradable and nt == NT_ENGINE:
                out_b[name] = ok(0.0)
            else:
                out_b[name] = run_pq(fn, bond, InterestRate(yl, dc_y, comp_y, freq_y), s)

        # the [D] Cells
        for y in ys:
            ir = InterestRate(float(y), dc_y, comp_y, freq_y)
            out_y[("npv_yield", y)] = run_pq(CashFlows.npv, leg, ir, False, s, s)
            out_y[("simple_duration_y", y)] = run_pq(CashFlows.duration, leg, ir, Duration.Simple, False, s, s)
            out_y[("modified_duration_y", y)] = run_pq(CashFlows.duration, leg, ir, Duration.Modified, False, s, s)
            if ycomp == COMP_COMPOUNDED:
                out_y[("macaulay_duration_y", y)] = run_pq(CashFlows.duration, leg, ir, Duration.Macaulay, False,
                                                           s, s)
            out_y[("convexity_y", y)] = run_pq(CashFlows.convexity, leg, ir, False, s, s)
            out_y[("bpv_y", y)] = run_pq(CashFlows.basisPointValue, leg, ir, False, s, s)
            out_y[("yvbp_y", y)] = run_pq(CashFlows.yieldValueBasisPoint, leg, ir, False, s, s)
            for name, fn in (("dirty_from_yield", BondFunctions.dirtyPrice),
                             ("clean_from_yield", BondFunctions.cleanPrice)):
                out_y[(name, y)] = ok(0.0) if (not tradable and nt == NT_ENGINE) else run_pq(fn, bond, ir, s)

        # the step times of the live (SETTLE-role) flows, with npvDate = s and the running lastDate
        if steps:
            last = s
            for i, cf in enumerate(leg):
                if cf.hasOccurred(s, False):
                    continue
                out_p[("ystep", lo + i)] = run_pq(_getStepwiseDiscountTime, cf, dc_y, s, last)
                last = cf.date()

        facts = {"key": key, "tradable": tradable, "settle": serial(s), "ycomp": ycomp, "has_price": px is not None,
                 "has_yield": yl is not None, "sign": sign}
    return {"bond": out_b, "y": out_y, "p": out_p, "k": out_k, "facts": facts}


MISSING = "missing"


def analytics_cell(item, name):
    """The Cells ``name`` of a Valuation item, or None when the model does not define it (yet)."""
    return item.cells[name] if name in item.cells else None


def analytics_model_values(item, b, expected):
    """The model's outcomes for every key of ``expected`` (the shape of :func:`pq_analytics`).

    A Cells the model does not define gives ``("missing", name)``.
    """
    out = {"bond": {}, "y": {}, "p": {}, "k": {}}

    def call(name, *args):
        cell = analytics_cell(item, name)
        return (MISSING, name) if cell is None else run_model(cell, *args)

    for k in expected["bond"]:
        out["bond"][k] = call(k, b)
    for k, y in expected["y"]:
        out["y"][(k, y)] = call(k, b, float(y))
    for k, p in expected["p"]:
        out["p"][(k, p)] = call(k, p)
    for k, kind in expected["k"]:
        out["k"][(k, kind)] = call(k, b, kind)
    return out


def analytics_mismatches(got, expected, ctx=""):
    """Messages for every output where the model differs from pureql (bitwise, NaN-aware, same type).

    A Cells missing from the model gives ``MISSING Valuation.<name>``;
    :func:`report_analytics` folds those to one line per name.
    """
    out = []
    for group in ("bond", "y", "p", "k"):
        for k, e in expected[group].items():
            g = got[group].get(k)
            if g is not None and g[0] == MISSING:
                out.append(f"MISSING Valuation.{g[1]} (docs/model-contract.md 4.8)")
            elif g is None or not same_outcome(g, e):
                out.append(f"{ctx} {k}: model {show(g) if g else 'not computed'} vs pureql {show(e)}")
    return out


def report_analytics(bad, label):
    """Fail once listing every missing contract name first, then the value mismatches; or pass."""
    missing = sorted({m for m in bad if m.startswith("MISSING ")})
    values = [m for m in bad if not m.startswith("MISSING ")]
    report_mismatches(missing + values, label)


def compare_analytics(model, scen_id, t, b, ys=(), settings=None, quotes=None, c=None, risk_yield=None,
                      steps=True):
    """``(messages, expected)``: the model against :func:`pq_analytics` for one bond-point.

    ``settings`` defaults to the model's own Data References (they must be
    the ones the model computes with).
    """
    exp = pq_analytics(model, scen_id, t, b, ys, settings, quotes, c, risk_yield=risk_yield, steps=steps)
    got = analytics_model_values(model.Valuation[scen_id, t], b, exp)
    key = model.Data.bond_keys()[b]
    return analytics_mismatches(got, exp, f"({scen_id}, {t}) b={b} {key}"), exp


# --------------------------------------------------------------------------- analytics goldens
#: Yields of the [D] Cells in the frozen analytics goldens.
GOLDEN_Y = (-0.005, 0.0, 0.0325, 0.11)
#: The settings variants frozen per input set (overrides of the contract defaults).
GOLDEN_VARIANTS = {
    "default": {},
    "brent": {"yield_solver": YIELD_BRENT},
    "roundtrip": {"zspread_price_source": 1},
    "raise_nan": {"nontradable_policy": NT_RAISE, "solver_error_policy": ERR_NAN},
}


def encode_outcome(o):
    if o[0] == "err":
        return {"error": o[1].__name__, "message": o[2]}
    return o[1]


def analytics_golden_values(model, ys=GOLDEN_Y, variants=GOLDEN_VARIANTS):
    """pureql's analytics of every bond at every (scen_id, t), JSON-ready, per settings variant.

    ``{variant: {"<scen_id>,<t>": {bond_key: {"bond": {...}, "y": {"name[y]":
    ...}, "p": {"ystep[p]": ...}}}}}``; ``y`` and ``p`` are frozen in the
    ``default`` variant only.
    """
    keys = list(model.Data.bond_keys())
    q = quote_inputs(model)
    out = {}
    for vname, over in variants.items():
        st = dict(ANALYTICS_DEFAULTS, **over)
        first = vname == "default"
        vals = {}
        for s in range(1, model.Data.n_scen() + 1):
            for t in range(model.Data.n_times()):
                c = curve_inputs(model, s, t)
                rec = {}
                for b, key in enumerate(keys):
                    e = pq_analytics(model, s, t, b, ys if first else (), st, q, c, steps=first)
                    r = {"bond": {k: encode_outcome(o) for k, o in e["bond"].items()}}
                    if first:
                        r["y"] = {f"{k}[{y!r}]": encode_outcome(o) for (k, y), o in e["y"].items()}
                        r["p"] = {f"{k}[{p}]": encode_outcome(o) for (k, p), o in e["p"].items()}
                    rec[key] = r
                vals[f"{s},{t}"] = rec
        out[vname] = vals
    return out


def write_analytics_golden(model, input_dir, path, label, ys=GOLDEN_Y, variants=GOLDEN_VARIANTS):
    """Freeze :func:`analytics_golden_values` of ``input_dir`` into ``path`` with its provenance block.

    The model's Data flags must be the defaults; the analytics settings are
    the contract defaults plus each variant (the model's own analytics
    References are not read).
    """
    import datetime
    import json
    import pathlib
    import subprocess

    from helpers.pureql_ref import PUREQL_SRC
    qlm = pathlib.Path(PUREQL_SRC).parent
    try:
        head = subprocess.run(["git", "-C", str(qlm), "rev-parse", "HEAD"], capture_output=True, text=True,
                              check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        head = "unknown"
    R, T, F = flags(model)
    doc = {
        "schema": "bondportfolio-analytics-golden/1",
        "provenance": {
            "what_it_is": (f"pureql values of the contract-4.8 analytics Cells of every bond of the {label} "
                           "input set at every (scen_id, t), computed by tests/helpers/pureql_val.py::pq_analytics "
                           "(pureql's BondFunctions / CashFlows entry points with explicit settlement dates; the "
                           "engine clean price with Settings moved), with the model's NT / ERR / Macaulay / "
                           "zspread policies applied, once per settings variant. Errors are recorded as "
                           "{error, message}."),
            "generator": "tests/helpers/pureql_val.py::write_analytics_golden",
            "oracle": "pureql (quantlib-migration src/pureql, a port of QuantLib v1.43)",
            "quantlib_migration_head": head,
            "frozen_on": datetime.date.today().isoformat(),
            "input_dir": label,
            "input_sha256": input_hashes(input_dir),
            "flags": {"include_reference_date_events": R, "include_todays_cashflows": T,
                      "engine_include_settlement_flows": F},
            "settings_defaults": ANALYTICS_DEFAULTS,
            "variants": variants,
            "yield_grid": list(ys),
            "codes": {"yield_solver": {"0": "NewtonSafe", "1": "Brent"}, "price_type": {"0": "Dirty", "1": "Clean"},
                      "nontradable_policy": {"0": "NT_ENGINE", "1": "NT_RAISE"},
                      "solver_error_policy": {"0": "ERR_RAISE", "1": "ERR_NAN"}},
            "tier": "exact (bitwise; DECISIONS.md D-2)",
            "licence": "data computed with pureql (BSD-3-Clause, derived from QuantLib); see NOTICE.md",
        },
        "values": analytics_golden_values(model, ys, variants),
    }
    pathlib.Path(path).write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
    return doc


def analytics_golden_mismatches(model, values, label=""):
    """The model (with the variant's settings on its Data) against one frozen variant (bitwise, NaN-aware)."""
    keys = list(model.Data.bond_keys())
    bad = []

    def call(item, name, *args):
        cell = analytics_cell(item, name)
        return (MISSING, name) if cell is None else run_model(cell, *args)

    def check(where, g, v):
        e = decode_golden(v)
        if g[0] == MISSING:
            bad.append(f"MISSING Valuation.{g[1]} (docs/model-contract.md 4.8)")
        elif not same_outcome(g, e):
            bad.append(f"{label} {where}: model {show(g)} vs golden {show(e)}")

    for point, recs in values.items():
        s, t = (int(x) for x in point.split(","))
        item = model.Valuation[s, t]
        for key, rec in recs.items():
            b = keys.index(key)
            for k, v in rec["bond"].items():
                check(f"{point} {key} {k}", call(item, k, b), v)
            for ky, v in rec.get("y", {}).items():
                k, y = ky.split("[")
                check(f"{point} {key} {ky}", call(item, k, b, float(y[:-1])), v)
            for kp, v in rec.get("p", {}).items():
                k, p = kp.split("[")
                check(f"{point} {key} {kp}", call(item, k, int(p[:-1])), v)
    return bad


def live_golden_mismatches(model, values, settings, ys=GOLDEN_Y, label=""):
    """Live pureql (:func:`pq_analytics`) against one frozen variant: a drift check of the oracle, no model Cells."""
    keys = list(model.Data.bond_keys())
    q = quote_inputs(model)
    bad = []
    for point, recs in values.items():
        s, t = (int(x) for x in point.split(","))
        c = curve_inputs(model, s, t)
        for key, rec in recs.items():
            b = keys.index(key)
            with_yp = "y" in rec
            e = pq_analytics(model, s, t, b, ys if with_yp else (), settings, q, c, steps=with_yp)
            frozen = {"bond": {k: decode_golden(v) for k, v in rec["bond"].items()}}
            live = {"bond": e["bond"]}
            if with_yp:
                frozen["y"] = {ky: decode_golden(v) for ky, v in rec["y"].items()}
                frozen["p"] = {kp: decode_golden(v) for kp, v in rec["p"].items()}
                live["y"] = {f"{k}[{y!r}]": o for (k, y), o in e["y"].items()}
                live["p"] = {f"{k}[{p}]": o for (k, p), o in e["p"].items()}
            for group in frozen:
                if set(frozen[group]) != set(live[group]):
                    bad.append(f"{label} {point} {key} {group}: keys {sorted(set(frozen[group]) ^ set(live[group]))}"
                               " differ between the golden and the live oracle")
                for k in frozen[group].keys() & live[group].keys():
                    if not same_outcome(live[group][k], frozen[group][k]):
                        bad.append(f"{label} {point} {key} {k}: live pureql {show(live[group][k])} vs golden "
                                   f"{show(frozen[group][k])}")
    return bad


# --------------------------------------------------------------------------- analytics input sets
def bond_row(key, **kw):
    """A bonds.csv row (dict of strings; missing columns blank)."""
    row = dict.fromkeys(generator().BOND_COLUMNS, "")
    row["bond_key"] = key
    row.update(kw)
    return row


#: The base bonds of the round trips, the policy set and the Q-09 pins:
#: the quantlib-migration README headline bond, the tracer zcb-10y, and a
#: quarterly Actual360 bond with a short first stub on UnitedStates.Settlement
#: (the stub is what takes the first branch of ``_getStepwiseDiscountTime``).
BASE_BONDS = {
    "FRB": dict(bond_type="FixedRate", face_amount="100", settlement_days="3", calendar="TARGET",
                issue_date="2015-09-15", effective_date="2015-09-15", termination_date="2025-09-15", tenor="6M",
                convention="Unadjusted", termination_convention="Unadjusted", rule="Backward", end_of_month="0",
                coupon_rate="0.04", accrual_day_counter="Thirty360.BondBasis", payment_convention="Following"),
    "ZCB": dict(bond_type="ZeroCoupon", face_amount="100", settlement_days="3", calendar="TARGET",
                issue_date="2015-09-16", redemption="100", payment_convention="Following", maturity_date="2025-09-16",
                yield_day_counter="Actual365Fixed", yield_compounding="Compounded", yield_frequency="Annual"),
    "STB": dict(bond_type="FixedRate", face_amount="1000", settlement_days="2", calendar="UnitedStates.Settlement",
                issue_date="2015-06-03", effective_date="2015-06-03", first_date="2015-08-15",
                termination_date="2023-02-15", tenor="3M", convention="ModifiedFollowing", coupon_rate="0.0275",
                accrual_day_counter="Actual360", payment_convention="ModifiedFollowing"),
}

#: quantlib-migration tests/new/instruments/test_fixedratebond_port_only.py:298-305.
Z_GRID = (-0.02, -0.01, -0.0025, 0.0, 0.0025, 0.01, 0.02, 0.05)
#: The four (day counter, compounding, frequency) conventions of the same test
#: (``_YIELD_CONVENTIONS``). In the model the day counter is the CURVE's and
#: the compounding / frequency are the spread conventions of curve_params.csv.
#: ActualActual.ISDA is outside v1 (DECISIONS.md D-3): the fourth convention
#: substitutes Thirty360.USA, a v1 day counter none of the other three uses.
Z_CONVENTIONS = (("Actual360", "Compounded", "Semiannual"), ("Actual365Fixed", "Compounded", "Annual"),
                 ("Thirty360.BondBasis", "Continuous", "Annual"), ("Thirty360.USA", "Simple", "Annual"))
#: quantlib-migration's ``_Y_GRID`` (monotonicity), and the yields of the y -> P -> y round trip.
Y_GRID_MONO = (-0.01, 0.0, 0.01, 0.02, 0.03, 0.045, 0.06, 0.10, 0.25)
Y_GRID_RT = (-0.005, 0.0, 0.02, 0.045, 0.09)
#: t = 0 and a future t (mid coupon period of every base bond).
RT_VDATES = ("2015-09-16", "2018-03-14")
#: The tracer's ZeroCurve (quantlib-migration tests/helpers/market.py ZERO_CURVE), by tenor from each val date.
ZERO_NODES = (("0D", "0.005"), ("1Y", "0.009"), ("2Y", "0.014"), ("5Y", "0.0205"), ("10Y", "0.0265"),
              ("15Y", "0.029"))
COMP_NAMES = ("Simple", "Compounded", "Continuous", "SimpleThenCompounded", "CompoundedThenSimple")
#: A frequency for each compounding of the y round trip (Simple and Continuous do not read it).
Y_RT_CONVENTIONS = (("Actual365Fixed", "Simple", "Annual"), ("Thirty360.BondBasis", "Compounded", "Semiannual"),
                    ("Actual360", "Continuous", "Annual"), ("Actual365Fixed", "SimpleThenCompounded", "Quarterly"),
                    ("Thirty360.European", "CompoundedThenSimple", "Semiannual"))


def _curve_param(s, t, ctype, dc, comp="Continuous", freq="Annual", extrap="1", flat="", sp_comp="", sp_freq=""):
    return {"scen_id": str(s), "t": str(t), "curve_type": ctype, "day_counter": dc, "compounding": comp,
            "frequency": freq, "extrapolate": extrap, "flat_rate": flat, "spread_compounding": sp_comp,
            "spread_frequency": sp_freq}


def _zero_nodes(s, t):
    return [{"scen_id": str(s), "t": str(t), "node": str(k), "date": "", "tenor": tenor, "rate": rate}
            for k, (tenor, rate) in enumerate(ZERO_NODES)]


def z_roundtrip_bonds():
    """``[(bond_key, base, z, price_type)]`` of the z round trip: every base bond x z grid x (Clean, Dirty)."""
    return [(f"{base}_Z{k}_{ptype[0]}", base, z, ptype) for base in BASE_BONDS for k, z in enumerate(Z_GRID)
            for ptype in ("Clean", "Dirty")]


def z_roundtrip_scenarios():
    """``{scen_id: (curve type, (dc, spread comp, spread freq))}``: 4 conventions x (FlatForward, ZeroCurve)."""
    out = {}
    for j, ctype in enumerate(("FlatForward", "ZeroCurve")):
        for k, conv in enumerate(Z_CONVENTIONS):
            out[1 + 4 * j + k] = (ctype, conv)
    return out


def write_z_roundtrip_inputs(out, prices=None):
    """The z round-trip input set: :func:`z_roundtrip_bonds` (no spreads) under :func:`z_roundtrip_scenarios`
    at :data:`RT_VDATES`; ``prices`` is ``{(scen_id, t, bond_key): price}`` (with each bond's price type)."""
    bonds = [bond_row(key, **BASE_BONDS[base]) for key, base, _, _ in z_roundtrip_bonds()]
    params, nodes = [], []
    for s, (ctype, (dc, comp, freq)) in z_roundtrip_scenarios().items():
        for t in range(len(RT_VDATES)):
            if ctype == "FlatForward":
                params.append(_curve_param(s, t, ctype, dc, flat="0.03", sp_comp=comp, sp_freq=freq))
            else:
                params.append(_curve_param(s, t, ctype, dc, sp_comp=comp, sp_freq=freq))
                nodes += _zero_nodes(s, t)
    ptypes = {key: ptype for key, _, _, ptype in z_roundtrip_bonds()}
    rows = None if prices is None else [
        {"scen_id": str(s), "t": str(t), "bond_key": key, "price": repr(float(p)), "price_type": ptypes[key]}
        for (s, t, key), p in sorted(prices.items())]
    return write_inputs(out, bonds, RT_VDATES, params, nodes, prices=rows, yields=[] if prices is not None else None)


def y_roundtrip_bonds():
    """``[(bond_key, base, (dc, comp, freq), y, price_type)]``: base bonds x 5 yield conventions x yields x types."""
    return [(f"{base}_{conv[1]}_Y{k}_{ptype[0]}", base, conv, y, ptype)
            for base in BASE_BONDS for conv in Y_RT_CONVENTIONS for k, y in enumerate(Y_GRID_RT)
            for ptype in ("Clean", "Dirty")]


def write_y_roundtrip_inputs(out, prices=None):
    """The y round-trip input set: one scenario (a flat 3% curve, which a yield never reads) at :data:`RT_VDATES`."""
    bonds = []
    for key, base, (dc, comp, freq), _, _ in y_roundtrip_bonds():
        kw = dict(BASE_BONDS[base])
        kw.update(yield_day_counter=dc, yield_compounding=comp, yield_frequency=freq)
        bonds.append(bond_row(key, **kw))
    params = [_curve_param(1, t, "FlatForward", "Actual365Fixed", flat="0.03") for t in range(len(RT_VDATES))]
    ptypes = {key: ptype for key, _, _, _, ptype in y_roundtrip_bonds()}
    rows = None if prices is None else [
        {"scen_id": str(s), "t": str(t), "bond_key": key, "price": repr(float(p)), "price_type": ptypes[key]}
        for (s, t, key), p in sorted(prices.items())]
    return write_inputs(out, bonds, RT_VDATES, params, prices=rows, yields=[] if prices is not None else None)


#: The policy set: prices that drive each solver failure, and a matured bond (N == 0) with quotes.
#: Measured with pureql (2026-10-11): a ZCB at 1e6 or 5e5 does not bracket a yield (IEEE-05: the
#: bracket walks through 1 + y/f = 0) and its z-spread objective raises "positive compound
#: factor required"; a price of 0 or below fails IrrFinder.checkSign; a price of 0 or 1e-8 on the
#: coupon bond solves to an absurd yield / z-spread; small evaluation budgets give both
#: "unable to bracket root in n function evaluations" and "maximum number of function
#: evaluations (n) exceeded".
POLICY_PRICES = {"Z_HI": ("ZCB", 1e6), "Z_5E5": ("ZCB", 5e5), "Z_ZERO": ("ZCB", 0.0), "Z_NEG": ("ZCB", -5.0),
                 "Z_OK": ("ZCB", 80.0), "Z_TINY": ("ZCB", 1e-8), "F_HI": ("FRB", 1e6), "F_ZERO": ("FRB", 0.0),
                 "F_NEG": ("FRB", -1.0), "F_OK": ("FRB", 104.0), "F_TINY": ("FRB", 1e-8),
                 "S_OK": ("STB", 99.0)}
POLICY_VDATES = ("2015-09-16", "2019-06-14")


def write_policy_inputs(out):
    """The NT / ERR / Macaulay policy set (two valuation dates, flat 3% curve, one spread)."""
    bonds = [bond_row(k, **BASE_BONDS[base]) for k, (base, _) in POLICY_PRICES.items()]
    simple = dict(BASE_BONDS["FRB"], yield_compounding="Simple")
    bonds.append(bond_row("F_SIMPLE_YLD", **simple))
    bonds.append(bond_row("F_SPREAD", **dict(BASE_BONDS["FRB"], spread_id="SP")))
    matured = dict(BASE_BONDS["ZCB"], issue_date="2010-01-04", maturity_date="2014-01-06")
    bonds.append(bond_row("Z_MATURED", **matured))
    bonds.append(bond_row("Z_MATURED_NOQ", **matured))
    params = [_curve_param(1, t, "FlatForward", "Actual365Fixed", extrap="0", flat="0.03", sp_comp="Compounded",
                           sp_freq="Annual") for t in range(len(POLICY_VDATES))]
    spreads = [{"scen_id": "1", "t": str(t), "spread_id": "SP", "spread": "0.0125"} for t in range(len(POLICY_VDATES))]
    prices, yields = [], []
    for t in range(len(POLICY_VDATES)):
        for k, (_, p) in POLICY_PRICES.items():
            prices.append({"scen_id": "1", "t": str(t), "bond_key": k, "price": repr(p),
                           "price_type": "Dirty" if k == "S_OK" else "Clean"})
        prices.append({"scen_id": "1", "t": str(t), "bond_key": "F_SIMPLE_YLD", "price": "101.0", "price_type": ""})
        prices.append({"scen_id": "1", "t": str(t), "bond_key": "Z_MATURED", "price": "99.0", "price_type": "Clean"})
        for k, y in (("F_OK", "0.035"), ("F_SIMPLE_YLD", "0.031"), ("Z_MATURED", "0.02"), ("S_OK", "-0.004")):
            yields.append({"scen_id": "1", "t": str(t), "bond_key": k, "yield": y})
    return write_inputs(out, bonds, POLICY_VDATES, params, spreads=spreads, prices=prices, yields=yields)


def write_compounding_variants(out, src):
    """``src`` (an input set) with every bond repeated once per yield compounding, keys ``<key>__<comp>``.

    Coupon rates, prices and yields are repeated for every copy; the yield day
    counter and frequency stay as given (a blank frequency takes Data's default).
    """
    import csv
    import pathlib

    src = pathlib.Path(src)
    gen = generator()

    def rows(name):
        p = src / name
        if not p.exists():
            return []
        with open(p, newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))

    bonds, coupons, prices, yields = [], [], [], []
    for comp in COMP_NAMES:
        for r in rows("bonds.csv"):
            bonds.append(dict(r, bond_key=f"{r['bond_key']}__{comp}", yield_compounding=comp))
        coupons += [dict(r, bond_key=f"{r['bond_key']}__{comp}") for r in rows("coupon_rates.csv")]
        prices += [dict(r, bond_key=f"{r['bond_key']}__{comp}") for r in rows("prices.csv")]
        yields += [dict(r, bond_key=f"{r['bond_key']}__{comp}") for r in rows("yields.csv")]
    gen.write_tables(out, {
        "bonds.csv": (gen.BOND_COLUMNS, bonds),
        "coupon_rates.csv": (gen.COUPON_RATE_COLUMNS, coupons),
        "valuation_dates.csv": (gen.VAL_DATE_COLUMNS, rows("valuation_dates.csv")),
        "curve_params.csv": (gen.CURVE_PARAM_COLUMNS, rows("curve_params.csv")),
        "curve_nodes.csv": (gen.CURVE_NODE_COLUMNS, rows("curve_nodes.csv")),
        "spreads.csv": (gen.SPREAD_COLUMNS, rows("spreads.csv")),
        "prices.csv": (gen.PRICE_COLUMNS, prices),
        "yields.csv": (gen.YIELD_COLUMNS, yields),
    })
    return out


#: The Q-09 pins: the headline bond with a Simple and a Compounded (Semiannual) yield on
#: Thirty360(BondBasis), and the zcb-10y with a Simple yield, at 2015-09-16 (s = 2015-09-21).
Q09_BONDS = {
    "Q09_FRB_SIMPLE": dict(BASE_BONDS["FRB"], yield_compounding="Simple"),
    "Q09_FRB_COMPOUNDED": dict(BASE_BONDS["FRB"], yield_compounding="Compounded", yield_frequency="Semiannual"),
    "Q09_ZCB_SIMPLE": dict(BASE_BONDS["ZCB"], yield_compounding="Simple"),
}
Q09_YIELDS = (0.03, 0.10)


def write_q09_inputs(out):
    params = [_curve_param(1, 0, "FlatForward", "Actual365Fixed", flat="0.03")]
    return write_inputs(out, [bond_row(k, **kw) for k, kw in Q09_BONDS.items()], ("2015-09-16",), params)


def pq_q09(model, b, y):
    """pureql's two discounting schemes of QUIRK Q-09 for bond ``b`` at yield ``y`` at (1, 0).

    ``P_step`` is ``CashFlows.npv(leg, InterestRate, False, s, s)`` (a running
    product of one-step factors); ``P_acc`` is the price the durations and the
    convexity are built on (``cashflows.py:411-434``): the sum of ``c *
    y.discountFactor(t)`` over the ACCUMULATED step time ``t``, written here
    with pureql's own ``_getStepwiseDiscountTime`` and ``InterestRate``.
    Also the modified duration (accumulated) and the central finite-difference
    log-derivative of ``P_step`` (h = 1e-6).
    """
    d = model.Data
    ydc, ycomp, yfreq = int(d.b_ydc_arr()[b]), int(d.b_ycomp_arr()[b]), int(d.b_yfreq_arr()[b])
    c = curve_inputs(model, 1, 0)
    R, T, F = flags(model)
    with pq_settings(c["vdate"], R, T):
        bond = pq_bond(model, b)
        leg = bond.cashflows()
        s = bond.settlementDate(pq_date(c["vdate"]))
        dc = pq_daycounter(ydc)

        def ir(r):
            return InterestRate(float(r), dc, pq_comp(ycomp), pq_freq(yfreq))

        p_step = CashFlows.npv(leg, ir(y), False, s, s)
        p_acc, tt, last = 0.0, 0.0, s
        for cf in leg:
            if cf.hasOccurred(s, False):
                continue
            tt += _getStepwiseDiscountTime(cf, dc, s, last)
            p_acc += cf.amount() * ir(y).discountFactor(tt)
            last = cf.date()
        h = 1e-6
        up, down = CashFlows.npv(leg, ir(y + h), False, s, s), CashFlows.npv(leg, ir(y - h), False, s, s)
        fd = -(up - down) / (2 * h) / p_step
        dmod = CashFlows.duration(leg, ir(y), Duration.Modified, False, s, s)
        dirty = BondFunctions.dirtyPrice(bond, ir(y), s)
    return {"P_step": p_step, "P_acc": p_acc, "gap": p_step - p_acc, "modified_duration": dmod,
            "fd_log_derivative": fd, "fd_vs_modified_rel": abs(fd - dmod) / dmod, "dirty_from_yield": dirty}


def write_analytics_pins(path, demo_model, q09_model):
    """Freeze the headline yield and the Q-09 pins (tests/data/analytics_pins.json) with provenance.

    ``demo_model`` reads bond_portfolio/ (default Data References);
    ``q09_model`` reads :func:`write_q09_inputs`.
    """
    import datetime
    import json
    import pathlib
    import subprocess

    from helpers.model import SAMPLE_INPUTS
    from helpers.pureql_ref import PUREQL_SRC
    qlm = pathlib.Path(PUREQL_SRC).parent
    try:
        head = subprocess.run(["git", "-C", str(qlm), "rev-parse", "HEAD"], capture_output=True, text=True,
                              check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        head = "unknown"

    # the headline: Bond.bondYield parity (accuracy 1e-8, engine clean price), then the risk at that yield
    m = demo_model
    b = list(m.Data.bond_keys()).index("HEADLINE_10Y")
    st = dict(ANALYTICS_DEFAULTS, yield_accuracy=1e-8)
    e = pq_analytics(m, 1, 0, b, (), st, steps=False)
    ytm = e["bond"]["ytm"][1]
    c = curve_inputs(m, 1, 0)
    with pq_settings(c["vdate"], 0, -1):
        bond = pq_bond(m, b)
        bond.setPricingEngine(DiscountingBondEngine(Handle[YieldTermStructure](pq_curve(m, 1, 0, c))))
        x = bond_inputs_of(m, b)
        parity = bond.bondYield(pq_daycounter(x[0]), pq_comp(x[1]), pq_freq(x[2]))
    assert parity == ytm == 0.030250400779423203, (parity, ytm)
    ey = pq_analytics(m, 1, 0, b, (ytm,), st, steps=False)
    headline = {
        "bond_key": "HEADLINE_10Y", "input_dir": "bond_portfolio", "point": "1,0",
        "settings": {"yield_accuracy": 1e-8},
        "readme_literal": 0.030250400779423203,
        "bond_bondYield": parity,
        "bond": {k: encode_outcome(o) for k, o in e["bond"].items()},
        "y_at_ytm": {k: encode_outcome(o) for (k, _), o in ey["y"].items()},
        "ytm_default_accuracy": encode_outcome(pq_analytics(m, 1, 0, b, (), None, steps=False)["bond"]["ytm"]),
    }
    q09 = {}
    keys = list(q09_model.Data.bond_keys())
    for key in Q09_BONDS:
        for y in Q09_YIELDS:
            q09[f"{key}@{y!r}"] = pq_q09(q09_model, keys.index(key), y)
    doc = {
        "schema": "bondportfolio-analytics-pins/1",
        "provenance": {
            "what_it_is": ("pureql values pinned for Phase 4: (1) the quantlib-migration README headline yield "
                           "0.030250400779423203 (Bond.bondYield parity: NewtonSafe, accuracy 1e-8, the engine "
                           "clean price; README.md:60-79, tests/meta/test_documentation_set.py:306-392) for the "
                           "demo HEADLINE_10Y at (1, 0), with the risk measures and prices at that yield; "
                           "(2) QUIRK Q-09: the stepwise npv (CashFlows.npv at an InterestRate) against the "
                           "accumulated-time price behind the durations, for the input set of "
                           "tests/helpers/pureql_val.py::write_q09_inputs."),
            "generator": "tests/helpers/pureql_val.py::write_analytics_pins",
            "oracle": "pureql (quantlib-migration src/pureql, a port of QuantLib v1.43)",
            "quantlib_migration_head": head,
            "frozen_on": datetime.date.today().isoformat(),
            "input_sha256": {"bond_portfolio": input_hashes(SAMPLE_INPUTS)},
            "tier": "exact (bitwise; DECISIONS.md D-2); fd_* are measurements (central difference, h = 1e-6)",
            "licence": "data computed with pureql (BSD-3-Clause, derived from QuantLib); see NOTICE.md",
        },
        "headline": headline,
        "q09": q09,
    }
    pathlib.Path(path).write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
    return doc


def bond_inputs_of(model, b):
    """``(ydc, ycomp, yfreq)`` of bond ``b`` from the model's Data arrays."""
    d = model.Data
    return int(d.b_ydc_arr()[b]), int(d.b_ycomp_arr()[b]), int(d.b_yfreq_arr()[b])
