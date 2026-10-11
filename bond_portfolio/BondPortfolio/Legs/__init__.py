# modelx: pseudo-python
# This file is part of a modelx model.
# It can be imported as a Python module, but functions defined herein
# are model formulas and may not be executable as standard Python.

"""The portfolio leg in flat (CSR) arrays, and the cash-flow table.

Derived from QuantLib (BSD-3-Clause); see NOTICE.md."""

from modelx.serialize.jsonvalues import *

_formula = None

_bases = []

_allow_none = None

_spaces = []

# ---------------------------------------------------------------------------
# Cells

def leg_columns():
    """The legs of all bonds as flat numpy arrays (CSR by bond), keyed by column name.

    Built in one loop over ``bond[b]`` for ``b`` in ``range(data.n_bonds())``;
    flows are in bond order and, within a bond, in leg order (the global
    flow index ``p``).

    * ``cf_lo`` (int64 [N+1]): the flows of bond ``b`` are
      ``cf_lo[b] <= p < cf_lo[b+1]``.
    * Per flow (int64 [P]): ``cf_owner`` (b), ``cf_date``, ``cf_kind``
      (``CF_*``), ``cf_coupon_idx`` (index into ``bond[b].coupons()``, -1
      for a redemption), ``cf_acc_start``, ``cf_acc_end``, ``cf_ref_start``,
      ``cf_ref_end``, ``cf_dc`` (0 for a redemption), ``cf_comp`` and
      ``cf_freq`` (the compounding and ``frequency()`` of the coupon's
      InterestRate; -1 for a redemption), ``cf_ex_date`` (the coupon's
      ex-coupon date; 0, the null date, for a redemption and for every v1
      coupon, which has no ex-coupon period).
    * Per flow (float64 [P]): ``cf_amount``, ``cf_nominal``, ``cf_rate``,
      ``cf_accrual_period`` (NaN for a redemption).
    * Notional schedule (CSR by bond): ``ns_lo`` (int64 [N+1]), ``ns_date``
      (int64), ``ns_notional`` (float64).
    * Per bond (int64 [N]): ``bk_cal`` (the bond's calendar, ``bond[b].calendar()``),
      ``bk_settle_days``, ``bk_issue``, ``bk_maturity``, ``bk_type``,
      ``bk_spread_idx``, ``bk_ydc``, ``bk_ycomp``, ``bk_yfreq``; ``bk_face``
      (float64 [N]).
    """
    int_cols = ("cf_owner", "cf_date", "cf_kind", "cf_coupon_idx", "cf_acc_start", "cf_acc_end",
                "cf_ref_start", "cf_ref_end", "cf_dc", "cf_comp", "cf_freq", "cf_ex_date", "ns_date",
                "bk_cal", "bk_settle_days", "bk_issue", "bk_maturity", "bk_type",
                "bk_spread_idx", "bk_ydc", "bk_ycomp", "bk_yfreq")
    float_cols = ("cf_amount", "cf_nominal", "cf_rate", "cf_accrual_period", "ns_notional", "bk_face")
    cols = {"cf_lo": [0], "ns_lo": [0]}
    for name in int_cols + float_cols:
        cols[name] = []
    nan = lib.nan_value()
    for b in range(data.n_bonds()):
        bnd = bond[b]
        cps = bnd.coupons()
        aps = bnd.accrual_periods()
        for f in bnd.leg():
            cols["cf_owner"].append(b)
            cols["cf_date"].append(f[0])
            cols["cf_kind"].append(f[1])
            cols["cf_amount"].append(f[2])
            cols["cf_coupon_idx"].append(f[3])
            if f[3] >= 0:
                cp = cps[f[3]]
                cols["cf_acc_start"].append(cp[1])
                cols["cf_acc_end"].append(cp[2])
                cols["cf_ref_start"].append(cp[3])
                cols["cf_ref_end"].append(cp[4])
                cols["cf_dc"].append(cp[10])
                cols["cf_comp"].append(cp[8])
                cols["cf_freq"].append(cp[9])
                cols["cf_ex_date"].append(cp[5])
                cols["cf_nominal"].append(cp[6])
                cols["cf_rate"].append(cp[7])
                cols["cf_accrual_period"].append(aps[f[3]])
            else:
                cols["cf_acc_start"].append(NULL_DATE)
                cols["cf_acc_end"].append(NULL_DATE)
                cols["cf_ref_start"].append(NULL_DATE)
                cols["cf_ref_end"].append(NULL_DATE)
                cols["cf_dc"].append(0)
                cols["cf_comp"].append(-1)
                cols["cf_freq"].append(-1)
                cols["cf_ex_date"].append(NULL_DATE)
                cols["cf_nominal"].append(nan)
                cols["cf_rate"].append(nan)
                cols["cf_accrual_period"].append(nan)
        cols["cf_lo"].append(len(cols["cf_date"]))
        ns = bnd.notional_schedule()
        for k in range(len(ns[0])):
            cols["ns_date"].append(ns[0][k])
            cols["ns_notional"].append(ns[1][k])
        cols["ns_lo"].append(len(cols["ns_date"]))
        cols["bk_cal"].append(bnd.calendar())
        cols["bk_settle_days"].append(bnd.settlement_days())
        cols["bk_issue"].append(bnd.issue_date())
        cols["bk_maturity"].append(bnd.maturity_date())
        cols["bk_type"].append(bnd.bond_type())
        cols["bk_spread_idx"].append(bnd.spread_index())
        cols["bk_ydc"].append(bnd.yield_dc())
        cols["bk_ycomp"].append(bnd.yield_comp())
        cols["bk_yfreq"].append(bnd.yield_freq())
        cols["bk_face"].append(bnd.face_amount())
    out = {}
    for name in cols:
        if name in float_cols:
            out[name] = np.array(cols[name], dtype=np.float64)
        else:
            out[name] = np.array(cols[name], dtype=np.int64)
    return out


def cf_lo_arr():
    """CSR offsets of the flows of each bond, int64 [N+1]."""
    return leg_columns()["cf_lo"]


def cf_owner_arr():
    """Bond index ``b`` of each flow, int64 [P]."""
    return leg_columns()["cf_owner"]


def cf_date_arr():
    """Payment date serial of each flow, int64 [P]."""
    return leg_columns()["cf_date"]


def cf_kind_arr():
    """Kind of each flow (``CF_COUPON`` / ``CF_AMORTIZING`` / ``CF_REDEMPTION``), int64 [P]."""
    return leg_columns()["cf_kind"]


def cf_coupon_idx_arr():
    """Index of each flow in its bond's coupons (-1 for a redemption), int64 [P]."""
    return leg_columns()["cf_coupon_idx"]


def cf_acc_start_arr():
    """Accrual start date serial of each flow (0 for a redemption), int64 [P]."""
    return leg_columns()["cf_acc_start"]


def cf_acc_end_arr():
    """Accrual end date serial of each flow (0 for a redemption), int64 [P]."""
    return leg_columns()["cf_acc_end"]


def cf_ref_start_arr():
    """Reference period start serial of each flow (0 for a redemption), int64 [P]."""
    return leg_columns()["cf_ref_start"]


def cf_ref_end_arr():
    """Reference period end serial of each flow (0 for a redemption), int64 [P]."""
    return leg_columns()["cf_ref_end"]


def cf_dc_arr():
    """Day-counter code of each coupon's rate (0 for a redemption), int64 [P]."""
    return leg_columns()["cf_dc"]


def cf_comp_arr():
    """Compounding of each coupon's rate (-1 for a redemption), int64 [P]."""
    return leg_columns()["cf_comp"]


def cf_freq_arr():
    """Frequency (``frequency()``) of each coupon's rate (-1 for a redemption), int64 [P]."""
    return leg_columns()["cf_freq"]


def cf_ex_date_arr():
    """Ex-coupon date serial of each flow (0 = none), int64 [P]."""
    return leg_columns()["cf_ex_date"]


def cf_amount_arr():
    """Amount of each flow, float64 [P]."""
    return leg_columns()["cf_amount"]


def cf_nominal_arr():
    """Nominal of each coupon (NaN for a redemption), float64 [P]."""
    return leg_columns()["cf_nominal"]


def cf_rate_arr():
    """Coupon rate of each coupon (NaN for a redemption), float64 [P]."""
    return leg_columns()["cf_rate"]


def cf_accrual_period_arr():
    """Accrual period (year fraction) of each coupon (NaN for a redemption), float64 [P]."""
    return leg_columns()["cf_accrual_period"]


def ns_lo_arr():
    """CSR offsets of the notional schedule of each bond, int64 [N+1]."""
    return leg_columns()["ns_lo"]


def ns_date_arr():
    """Notional schedule dates (the first of each bond is the null date), int64."""
    return leg_columns()["ns_date"]


def ns_notional_arr():
    """Notional schedule values (the last of each bond is 0.0), float64."""
    return leg_columns()["ns_notional"]


def bk_cal_arr():
    """The calendar of each bond (settlement and payments; ``bond[b].calendar()``), int64 [N]."""
    return leg_columns()["bk_cal"]


def bk_settle_days_arr():
    """Settlement days of each bond, int64 [N]."""
    return leg_columns()["bk_settle_days"]


def bk_issue_arr():
    """Issue date serial of each bond (0 = none), int64 [N]."""
    return leg_columns()["bk_issue"]


def bk_maturity_arr():
    """Maturity date serial of each bond (``bond[b].maturity_date()``), int64 [N]."""
    return leg_columns()["bk_maturity"]


def bk_type_arr():
    """Bond type code of each bond, int64 [N]."""
    return leg_columns()["bk_type"]


def bk_spread_idx_arr():
    """Spread index of each bond (-1 = no spread), int64 [N]."""
    return leg_columns()["bk_spread_idx"]


def bk_ydc_arr():
    """Yield-quote day-counter code of each bond, int64 [N]."""
    return leg_columns()["bk_ydc"]


def bk_ycomp_arr():
    """Yield-quote compounding of each bond, int64 [N]."""
    return leg_columns()["bk_ycomp"]


def bk_yfreq_arr():
    """Yield-quote frequency of each bond, int64 [N]."""
    return leg_columns()["bk_yfreq"]


def bk_face_arr():
    """Face amount of each bond, float64 [N]."""
    return leg_columns()["bk_face"]


def n_flows():
    """P: the number of flows of the portfolio leg."""
    return len(leg_columns()["cf_date"])


def iso_column(name):
    """The date serials of the ``leg_columns()`` column ``name`` as a list of ISO strings (``''`` for the null date).

    A list, not a numpy string array: modelx-cython 0.1.0 types a Cells that
    returns a non-numeric array as ``str``.
    """
    a = leg_columns()[name]
    s = (np.datetime64("1899-12-30") + a.astype("timedelta64[D]")).astype(str)
    return np.where(a == NULL_DATE, "", s).tolist()


def cashflow_frame():
    """The portfolio cash flows (Goal 1 output): one row per flow, in bond then leg order.

    Columns: ``bond_key``, ``flow`` (index within the bond), ``kind``
    ('coupon' / 'amortizing' / 'redemption'), ``date`` (ISO), ``amount``,
    ``nominal``, ``rate``, ``accrual_start``, ``accrual_end``,
    ``ref_start``, ``ref_end`` (ISO, blank for a redemption) and
    ``accrual_period`` (NaN for a redemption).
    """
    cols = leg_columns()
    keys = data.bond_keys()
    kinds = ("coupon", "amortizing", "redemption")
    owner = cols["cf_owner"]
    lo = cols["cf_lo"]
    bond_key = []
    flow = []
    kind = []
    for p in range(len(owner)):
        bo = int(owner[p])
        bond_key.append(keys[bo])
        flow.append(p - int(lo[bo]))
        kind.append(kinds[int(cols["cf_kind"][p])])
    return pd.DataFrame({
        "bond_key": bond_key,
        "flow": np.array(flow, dtype=np.int64),
        "kind": kind,
        "date": iso_column("cf_date"),
        "amount": cols["cf_amount"],
        "nominal": cols["cf_nominal"],
        "rate": cols["cf_rate"],
        "accrual_start": iso_column("cf_acc_start"),
        "accrual_end": iso_column("cf_acc_end"),
        "ref_start": iso_column("cf_ref_start"),
        "ref_end": iso_column("cf_ref_end"),
        "accrual_period": cols["cf_accrual_period"],
    })


def check_limits():
    """True if the portfolio and the scenario grid fit the compile-time sizes, else raises ``ValueError`` listing every excess.

    The compiled model holds its Valuation Cells in C arrays sized by the
    model-level ``MAX_*`` References (``tools/build_cy.py`` ``SPEC_MAP``), so
    an index past a size raises ``IndexError`` there. Checked:

    * N <= ``MAX_BONDS`` (the bond index ``b``) and P <= ``MAX_FLOWS`` (the
      flow index ``p``); at most ``MAX_SCHED`` flows per bond;
    * settlement days in 0..``MAX_SETTLE_DAYS`` and calendar codes below
      ``CAL_MAX`` (``settle_cal(cal, nsd)``);
    * T <= ``MAX_T`` (the projection period ``per`` runs 0..T) and
      S <= ``MAX_SCEN``;
    * at most ``MAX_NODES`` nodes per ZeroCurve (the node index ``nd``);
    * the day offset ``kd = d - vdate()`` below ``MAX_KD``. An item
      discounts only dates on or after its own valuation date: the flows not
      yet paid, and the settlement date, the later of the issue date and a
      few business days after ``vdate()``. So the latest flow or issue date
      minus the earliest valuation date must be below ``MAX_KD``.
    """
    cols = leg_columns()
    errs = []
    N = len(cols["bk_type"])
    P = len(cols["cf_date"])
    if N > MAX_BONDS:
        errs.append(str(N) + " bonds exceed MAX_BONDS (" + str(MAX_BONDS) + ")")
    if P > MAX_FLOWS:
        errs.append(str(P) + " flows exceed MAX_FLOWS (" + str(MAX_FLOWS) + ")")
    T = data.n_times()
    S = data.n_scen()
    if T > MAX_T:
        errs.append(str(T) + " valuation dates exceed MAX_T (" + str(MAX_T) + ")")
    if S > MAX_SCEN:
        errs.append(str(S) + " scenarios exceed MAX_SCEN (" + str(MAX_SCEN) + ")")
    ctype = data.curve_columns()["c_type"]
    ncnt = data.node_columns()["n_cnt"]
    for s in range(S):
        for k in range(T):
            nn = int(ncnt[s, k])
            if int(ctype[s, k]) == CURVE_ZERO and nn > MAX_NODES:
                errs.append("the ZeroCurve of (scen_id " + str(s + 1) + ", t " + str(k) + ") has " + str(nn)
                            + " nodes, more than MAX_NODES (" + str(MAX_NODES) + ")")
    if T > 0 and (P > 0 or N > 0):
        vmin = int(data.val_date_arr()[0])
        for k in range(1, T):
            vk = int(data.val_date_arr()[k])
            if vk < vmin:
                vmin = vk
        dmax = NULL_DATE
        if P > 0:
            dmax = int(cols["cf_date"].max())
        if N > 0:
            dmax = max(dmax, int(cols["bk_issue"].max()))
        if dmax - vmin >= MAX_KD:
            errs.append("the latest flow or issue date (" + lib.long_date(dmax) + ") is " + str(dmax - vmin)
                        + " days after the earliest valuation date (" + lib.long_date(vmin)
                        + "): day offsets must be below MAX_KD (" + str(MAX_KD) + ")")
    keys = data.bond_keys()
    lo = cols["cf_lo"]
    for bo in range(N):
        nf = int(lo[bo + 1]) - int(lo[bo])
        if nf > MAX_SCHED:
            errs.append("bond '" + keys[bo] + "': " + str(nf) + " flows exceed MAX_SCHED (" + str(MAX_SCHED) + ")")
        nsd = int(cols["bk_settle_days"][bo])
        if nsd < 0 or nsd > MAX_SETTLE_DAYS:
            errs.append("bond '" + keys[bo] + "': settlement days " + str(nsd)
                        + " outside 0..MAX_SETTLE_DAYS (" + str(MAX_SETTLE_DAYS) + ")")
        cal = int(cols["bk_cal"][bo])
        if cal < 0 or cal >= CAL_MAX:
            errs.append("bond '" + keys[bo] + "': calendar code " + str(cal)
                        + " outside 0..CAL_MAX-1 (" + str(CAL_MAX - 1) + ")")
    if errs:
        more = "" if len(errs) <= 50 else "\n  ... and " + str(len(errs) - 50) + " more"
        raise ValueError("the inputs exceed the model limits (" + str(len(errs)) + " problem(s)):\n  "
                         + "\n  ".join(errs[:50]) + more)
    return True


# ---------------------------------------------------------------------------
# References

data = ("Interface", ("..", "Data"), "auto")

lib = ("Interface", ("..", "Lib"), "auto")

dates = ("Interface", ("..", "Dates"), "auto")

bond = ("Interface", ("..", "Bond"), "auto")
