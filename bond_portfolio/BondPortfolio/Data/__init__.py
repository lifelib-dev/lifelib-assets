# modelx: pseudo-python
# This file is part of a modelx model.
# It can be imported as a Python module, but functions defined herein
# are model formulas and may not be executable as standard Python.

"""Inputs read from CSV files, and run settings.

All readers live here, so each file is read once per model.
Set :attr:`input_dir` before calculating; when it is empty the
directory containing the model is used.

The CSV columns, their defaults and the codes the names map to are
documented in ``bond_portfolio/inputs.md``. Readers return DataFrames of
strings; the parsers turn names into the integer codes of the model-level
References; the ``*_arr`` Cells hold the parsed inputs as numpy arrays that
other Spaces read element-wise only (``data.b_type_arr()[b]``).
:func:`check_inputs` validates the inputs against the v1 scope."""

from modelx.serialize.jsonvalues import *

_formula = None

_bases = []

_allow_none = None

_spaces = []

# ---------------------------------------------------------------------------
# Cells

def input_path():
    """Directory holding the input CSV files.

    :attr:`input_dir` if it is set, else the directory containing the model.
    """
    if input_dir:
        return str(input_dir)
    return str(_model.path.parent)


def read_table(fname, required, optional, must_exist):
    """The CSV file ``fname`` in :func:`input_path`, read as strings.

    The file is read with ``pd.read_csv(path, dtype=str, keep_default_na=False)``,
    so a blank cell is ``''``; surrounding whitespace is removed from names and
    values. ``required`` and ``optional`` are tuples of column names. A missing
    required column raises ``ValueError``; a missing optional column is added,
    blank. A missing file raises ``ValueError`` if ``must_exist`` is 1, else
    gives an empty frame with the columns ``required + optional``.
    """
    path = input_path() + "/" + fname
    try:
        df = pd.read_csv(path, dtype=str, keep_default_na=False)
    except FileNotFoundError:
        if must_exist:
            raise ValueError(fname + ": input file not found: " + path)
        empty = {}
        for c in required + optional:
            empty[c] = pd.Series([], dtype=str)
        return pd.DataFrame(empty)
    names = [str(c).replace("﻿", "").strip() for c in df.columns]
    missing = [c for c in required if c not in names]
    if missing:
        raise ValueError(fname + ": missing required column(s): " + ", ".join(missing))
    # A new frame rather than column assignment into df: pandas detects chained
    # assignment by reference counts, which differ in the compiled model.
    cols = {}
    for name, c in zip(names, df.columns):
        cols[name] = df[c].astype(str).str.strip().tolist()
    nrows = len(df)
    for c in optional:
        if c not in cols:
            cols[c] = [""] * nrows
    return pd.DataFrame(cols, dtype=str)

_is_cached = False


def bond_table():
    """``bonds.csv``: one row per bond; the row order defines the bond index ``b``."""
    return read_table(
        bond_file,
        ("bond_key", "bond_type", "face_amount", "settlement_days", "calendar"),
        ("issue_date", "redemption", "spread_id",
         "effective_date", "termination_date", "tenor", "convention",
         "termination_convention", "rule", "end_of_month", "first_date",
         "next_to_last_date", "coupon_rate", "accrual_day_counter",
         "first_period_day_counter", "payment_convention", "payment_calendar",
         "maturity_date", "yield_day_counter", "yield_compounding",
         "yield_frequency"),
        1)


def coupon_rate_table():
    """``coupon_rates.csv`` (optional): step-up coupon vectors, one row per (bond_key, k)."""
    return read_table(coupon_rate_file, ("bond_key", "k", "rate"), (), 0)


def val_date_table():
    """``valuation_dates.csv``: the valuation date of each time index ``t`` (shared by all scenarios)."""
    return read_table(val_date_file, ("t", "val_date"), (), 1)


def curve_param_table():
    """``curve_params.csv``: the curve conventions of each (scen_id, t)."""
    return read_table(
        curve_param_file,
        ("scen_id", "t", "curve_type", "day_counter"),
        ("compounding", "frequency", "extrapolate", "flat_rate",
         "spread_compounding", "spread_frequency"),
        1)


def curve_node_table():
    """``curve_nodes.csv`` (optional): ZeroCurve nodes of each (scen_id, t), by date or by tenor."""
    return read_table(
        curve_node_file, ("scen_id", "t", "node", "rate"), ("date", "tenor"), 0)


def spread_table():
    """``spreads.csv`` (optional): the zero spread of each spread_id at each (scen_id, t)."""
    return read_table(spread_file, ("scen_id", "t", "spread_id", "spread"), (), 0)


def price_table():
    """``prices.csv`` (optional, sparse): quoted bond prices at (scen_id, t)."""
    return read_table(
        price_file, ("scen_id", "t", "bond_key", "price"), ("price_type",), 0)


def yield_table():
    """``yields.csv`` (optional, sparse): quoted bond yields at (scen_id, t)."""
    return read_table(yield_file, ("scen_id", "t", "bond_key", "yield"), (), 0)


def iso_serial(s):
    """Serial number of the ISO date ``s`` (``YYYY-MM-DD``); ``''`` gives 0, the null date.

    The serial is ``(date - 1899-12-30).days``, which equals the QuantLib
    serial number over the whole valid range (1901-01-01 is 367).
    """
    if s == "":
        return 0
    ok = len(s) == 10 and s[4] == "-" and s[7] == "-" and s.isascii() \
        and s[0:4].isdigit() and s[5:7].isdigit() and s[8:10].isdigit()
    if not ok:
        raise ValueError("invalid date '" + s + "' (expected ISO YYYY-MM-DD)")
    try:
        dt = datetime.date(int(s[0:4]), int(s[5:7]), int(s[8:10]))
    except ValueError:
        raise ValueError("invalid date '" + s + "' (expected ISO YYYY-MM-DD)")
    return int((dt - datetime.date(1899, 12, 30)).days)

_is_cached = False


def int_text(s):
    """The int of a decimal integer text such as ``'3'`` or ``'-1'``; raises ``ValueError`` otherwise."""
    digits = s[1:] if s[:1] in ("-", "+") else s
    if not (len(digits) > 0 and digits.isascii() and digits.isdigit()):
        raise ValueError("invalid integer '" + s + "'")
    return int(s)

_is_cached = False


def float_text(s):
    """The float of a finite number text such as ``'0.04'``; raises ``ValueError`` otherwise."""
    try:
        x = float(s)
    except ValueError:
        raise ValueError("invalid number '" + s + "'")
    if not math.isfinite(x):
        raise ValueError("invalid number '" + s + "' (not finite)")
    return x

_is_cached = False


def calendar_code(s):
    """Calendar code (``CAL_*``) of a calendar name.

    ``NullCalendar``, ``TARGET``, ``UnitedStates.Settlement`` and
    ``UnitedStates.GovernmentBond``; any other name raises ``ValueError``.
    """
    if s == "NullCalendar":
        return CAL_NULL
    elif s == "TARGET":
        return CAL_TARGET
    elif s == "UnitedStates.Settlement":
        return CAL_US_SETTLEMENT
    elif s == "UnitedStates.GovernmentBond":
        return CAL_US_GOVBOND
    raise ValueError(
        "unknown or unsupported calendar '" + s + "' (supported: NullCalendar, "
        "TARGET, UnitedStates.Settlement, UnitedStates.GovernmentBond)")

_is_cached = False


def daycounter_code(s):
    """Day-counter code (``DC_*``) of a day-counter name.

    ``Actual360``, ``Actual365Fixed``, ``Thirty360.USA``,
    ``Thirty360.BondBasis`` and ``Thirty360.ISMA`` (both ``DC_30360_BB``),
    ``Thirty360.European`` and ``Thirty360.EurobondBasis`` (both
    ``DC_30360_EU``), as pureql's ``thirty360._implementation`` pairs them.
    Any other name raises ``ValueError``.
    """
    if s == "Actual360":
        return DC_ACT360
    elif s == "Actual365Fixed":
        return DC_ACT365F
    elif s == "Thirty360.USA":
        return DC_30360_USA
    elif s == "Thirty360.BondBasis" or s == "Thirty360.ISMA":
        return DC_30360_BB
    elif s == "Thirty360.European" or s == "Thirty360.EurobondBasis":
        return DC_30360_EU
    raise ValueError(
        "unknown or unsupported day counter '" + s + "' (supported: Actual360, "
        "Actual365Fixed, Thirty360.USA, Thirty360.BondBasis, Thirty360.ISMA, "
        "Thirty360.European, Thirty360.EurobondBasis)")

_is_cached = False


def bdc_code(s):
    """``BusinessDayConvention`` value (``BDC_*``) of a pureql member name such as ``Following``."""
    if s == "Following":
        return BDC_FOLLOWING
    elif s == "ModifiedFollowing":
        return BDC_MODIFIED_FOLLOWING
    elif s == "Preceding":
        return BDC_PRECEDING
    elif s == "ModifiedPreceding":
        return BDC_MODIFIED_PRECEDING
    elif s == "Unadjusted":
        return BDC_UNADJUSTED
    elif s == "HalfMonthModifiedFollowing":
        return BDC_HALF_MONTH_MODIFIED_FOLLOWING
    elif s == "Nearest":
        return BDC_NEAREST
    raise ValueError(
        "unknown business day convention '" + s + "' (expected one of: Following, "
        "ModifiedFollowing, Preceding, ModifiedPreceding, Unadjusted, "
        "HalfMonthModifiedFollowing, Nearest)")

_is_cached = False


def comp_code(s):
    """``Compounding`` value (``COMP_*``) of a pureql member name such as ``Compounded``."""
    if s == "Simple":
        return COMP_SIMPLE
    elif s == "Compounded":
        return COMP_COMPOUNDED
    elif s == "Continuous":
        return COMP_CONTINUOUS
    elif s == "SimpleThenCompounded":
        return COMP_SIMPLE_THEN_COMPOUNDED
    elif s == "CompoundedThenSimple":
        return COMP_COMPOUNDED_THEN_SIMPLE
    raise ValueError(
        "unknown compounding '" + s + "' (expected one of: Simple, Compounded, "
        "Continuous, SimpleThenCompounded, CompoundedThenSimple)")

_is_cached = False


def freq_code(s):
    """``Frequency`` value (``FREQ_*``) of a pureql member name such as ``Semiannual``."""
    if s == "NoFrequency":
        return FREQ_NO_FREQUENCY
    elif s == "Once":
        return FREQ_ONCE
    elif s == "Annual":
        return FREQ_ANNUAL
    elif s == "Semiannual":
        return FREQ_SEMIANNUAL
    elif s == "EveryFourthMonth":
        return FREQ_EVERY_FOURTH_MONTH
    elif s == "Quarterly":
        return FREQ_QUARTERLY
    elif s == "Bimonthly":
        return FREQ_BIMONTHLY
    elif s == "Monthly":
        return FREQ_MONTHLY
    elif s == "EveryFourthWeek":
        return FREQ_EVERY_FOURTH_WEEK
    elif s == "Biweekly":
        return FREQ_BIWEEKLY
    elif s == "Weekly":
        return FREQ_WEEKLY
    elif s == "Daily":
        return FREQ_DAILY
    elif s == "OtherFrequency":
        return FREQ_OTHER_FREQUENCY
    raise ValueError(
        "unknown frequency '" + s + "' (expected one of: NoFrequency, Once, Annual, "
        "Semiannual, EveryFourthMonth, Quarterly, Bimonthly, Monthly, "
        "EveryFourthWeek, Biweekly, Weekly, Daily, OtherFrequency)")

_is_cached = False


def rule_code(s):
    """``DateGeneration.Rule`` value of a pureql member name such as ``Backward``.

    Every pureql member is recognised (``RULE_*`` names the first three);
    :func:`check_inputs` admits only ``Backward`` in v1.
    """
    if s == "Backward":
        return RULE_BACKWARD
    elif s == "Forward":
        return RULE_FORWARD
    elif s == "Zero":
        return RULE_ZERO
    elif s == "ThirdWednesday":
        return 3
    elif s == "ThirdWednesdayInclusive":
        return 4
    elif s == "Twentieth":
        return 5
    elif s == "TwentiethIMM":
        return 6
    elif s == "OldCDS":
        return 7
    elif s == "CDS":
        return 8
    elif s == "CDS2015":
        return 9
    raise ValueError(
        "unknown date generation rule '" + s + "' (expected one of: Backward, Forward, "
        "Zero, ThirdWednesday, ThirdWednesdayInclusive, Twentieth, TwentiethIMM, "
        "OldCDS, CDS, CDS2015)")

_is_cached = False


def bond_type_code(s):
    """Bond type code: ``FixedRate`` gives ``BOND_FIXED``, ``ZeroCoupon`` gives ``BOND_ZERO``."""
    if s == "FixedRate":
        return BOND_FIXED
    elif s == "ZeroCoupon":
        return BOND_ZERO
    raise ValueError(
        "unknown or unsupported bond type '" + s + "' (supported: FixedRate, ZeroCoupon)")

_is_cached = False


def curve_type_code(s):
    """Curve type code: ``ZeroCurve`` gives ``CURVE_ZERO``, ``FlatForward`` gives ``CURVE_FLAT``."""
    if s == "ZeroCurve":
        return CURVE_ZERO
    elif s == "FlatForward":
        return CURVE_FLAT
    raise ValueError(
        "unknown or unsupported curve type '" + s + "' (supported: ZeroCurve, FlatForward)")

_is_cached = False


def price_type_code(s):
    """``Bond.Price.Type`` value: ``Dirty`` gives ``PRICE_DIRTY``, ``Clean`` gives ``PRICE_CLEAN``."""
    if s == "Dirty":
        return PRICE_DIRTY
    elif s == "Clean":
        return PRICE_CLEAN
    raise ValueError("unknown price type '" + s + "' (expected Clean or Dirty)")

_is_cached = False


def tenor_n(s):
    """Length ``n`` of a tenor ``<n><D|W|M|Y>`` such as ``6M``, ``1Y`` or ``0D``."""
    digits = s[:-1]
    ok = len(s) >= 2 and digits.isascii() and digits.isdigit() and s[-1] in "DWMYdwmy"
    if not ok:
        raise ValueError("invalid tenor '" + s + "' (expected <n><D|W|M|Y>, e.g. 6M, 1Y, 0D)")
    return int(digits)

_is_cached = False


def tenor_unit(s):
    """``TimeUnit`` value (``TU_*``) of a tenor ``<n><D|W|M|Y>`` such as ``6M``."""
    n = tenor_n(s)
    u = s[-1].upper()
    if u == "D":
        return TU_DAYS
    elif u == "W":
        return TU_WEEKS
    elif u == "M":
        return TU_MONTHS
    return TU_YEARS

_is_cached = False


def flag(s):
    """0/1 of a flag text: ``1``/``true`` give 1; ``0``/``false`` and blank (the default) give 0."""
    if s == "" or s == "0" or s.lower() == "false":
        return 0
    elif s == "1" or s.lower() == "true":
        return 1
    raise ValueError("invalid flag '" + s + "' (expected 0, 1, true, false or blank)")

_is_cached = False


def code_of(kind, s):
    """The text ``s`` parsed as ``kind``, cached per distinct (kind, text).

    ``kind`` is one of ``date``, ``int``, ``calendar``,
    ``daycounter``, ``bdc``, ``comp``, ``freq``, ``rule``, ``bond_type``,
    ``curve_type``, ``price_type``, ``tenor_n``, ``tenor_unit``, ``flag``.
    Used by the array builders so that each distinct text is parsed once.
    """
    if kind == "date":
        return iso_serial(s)
    elif kind == "int":
        return int_text(s)
    elif kind == "calendar":
        return calendar_code(s)
    elif kind == "daycounter":
        return daycounter_code(s)
    elif kind == "bdc":
        return bdc_code(s)
    elif kind == "comp":
        return comp_code(s)
    elif kind == "freq":
        return freq_code(s)
    elif kind == "rule":
        return rule_code(s)
    elif kind == "bond_type":
        return bond_type_code(s)
    elif kind == "curve_type":
        return curve_type_code(s)
    elif kind == "price_type":
        return price_type_code(s)
    elif kind == "tenor_n":
        return tenor_n(s)
    elif kind == "tenor_unit":
        return tenor_unit(s)
    elif kind == "flag":
        return flag(s)
    raise ValueError("code_of: unknown kind '" + kind + "'")


def float_of(s):
    """The text ``s`` parsed as a float (:func:`float_text`), cached per distinct text.

    Kept apart from :func:`code_of`, whose values are all integers, so that
    each has one return type (modelx-cython types a Cells by what it returns).
    """
    return float_text(s)


def parse_error(kind, s):
    """``''`` if the text ``s`` parses as ``kind`` (see :func:`code_of`; ``float`` is :func:`float_of`), else the error message."""
    try:
        if kind == "float":
            float_of(s)
        else:
            code_of(kind, s)
    except ValueError as e:
        return str(e)
    return ""


def n_bonds():
    """N: the number of bonds (rows of bonds.csv)."""
    return len(bond_table())


def n_times():
    """T: the number of valuation dates (rows of valuation_dates.csv); t runs 0..T-1."""
    return len(val_date_table())


def n_scen():
    """S: the largest scen_id in curve_params.csv (scen_id runs 1..S); 0 if there is none."""
    s = 0
    for x in curve_param_table()["scen_id"].tolist():
        v = code_of("int", x)
        if v > s:
            s = v
    return s


def n_spread_ids():
    """The number of spread ids, ``len(spread_ids())``: the last dimension of :func:`sp_arr`."""
    return len(spread_ids())


def n_nodes_total():
    """The total number of curve nodes held in :func:`n_date_arr` and :func:`n_rate_arr`."""
    return len(node_columns()["n_date"])


def bond_keys():
    """The bond_key of every bond, in row order (``b``)."""
    return tuple(bond_table()["bond_key"].tolist())


def spread_ids():
    """The distinct spread ids: first those of spreads.csv, then any only in bonds.csv, in order of appearance.

    The position of an id in this tuple is its spread index, the value of
    :func:`b_spread_idx_arr` and the last index of :func:`sp_arr`.
    """
    ids = []
    seen = set()
    for k in spread_table()["spread_id"].tolist() + bond_table()["spread_id"].tolist():
        if k != "" and k not in seen:
            seen.add(k)
            ids.append(k)
    return tuple(ids)


def bond_columns():
    """Per-bond inputs parsed into numpy arrays, keyed by array name without ``_arr``.

    Built in one pass over :func:`bond_table`. Blank cells take the defaults
    of inputs.md: redemption 100, spread index -1 (no spread), tenor 0D,
    convention Following, termination convention = convention, rule Backward,
    end_of_month 0, first/next-to-last dates null, first-period day counter 0
    (none), payment convention Following, payment calendar -1 (the schedule
    calendar), yield day counter = the accrual day counter (FixedRate) or
    Actual365Fixed (ZeroCoupon), yield compounding Compounded. The coupon
    rates are in CSR form: ``cr_lo``/``cr_cnt`` per bond into ``cr_rate``,
    from coupon_rates.csv if it lists the bond, else from ``coupon_rate``.
    The yield frequency is in :func:`b_yfreq_arr`.
    """
    df = bond_table()
    sid = {}
    for i, k in enumerate(spread_ids()):
        sid[k] = i
    crt = coupon_rate_table()
    vec = {}
    for key, k, rate in zip(crt["bond_key"].tolist(), crt["k"].tolist(), crt["rate"].tolist()):
        if key not in vec:
            vec[key] = []
        vec[key].append((code_of("int", k), float_of(rate)))
    names = ("b_type", "b_face", "b_settle_days", "b_calendar", "b_issue",
             "b_redemption", "b_spread_idx", "b_eff", "b_term", "b_tenor_n",
             "b_tenor_unit", "b_conv", "b_term_conv", "b_rule", "b_eom",
             "b_first", "b_ntl", "b_accrual_dc", "b_first_dc", "b_pay_conv",
             "b_pay_cal", "cr_lo", "cr_cnt", "b_maturity", "b_ydc", "b_ycomp")
    cols = {}
    for name in names:
        cols[name] = []
    rates = []
    for i, r in enumerate(df.to_dict("records")):
        try:
            btype = code_of("bond_type", r["bond_type"])
            cols["b_type"].append(btype)
            cols["b_face"].append(float_of(r["face_amount"]))
            cols["b_settle_days"].append(code_of("int", r["settlement_days"]))
            cols["b_calendar"].append(code_of("calendar", r["calendar"]))
            cols["b_issue"].append(code_of("date", r["issue_date"]))
            cols["b_redemption"].append(
                float_of(r["redemption"]) if r["redemption"] != "" else 100.0)
            cols["b_spread_idx"].append(sid[r["spread_id"]] if r["spread_id"] != "" else -1)
            cols["b_eff"].append(code_of("date", r["effective_date"]))
            cols["b_term"].append(code_of("date", r["termination_date"]))
            tenor = r["tenor"] if r["tenor"] != "" else "0D"
            cols["b_tenor_n"].append(code_of("tenor_n", tenor))
            cols["b_tenor_unit"].append(code_of("tenor_unit", tenor))
            conv = code_of("bdc", r["convention"]) if r["convention"] != "" else BDC_FOLLOWING
            cols["b_conv"].append(conv)
            cols["b_term_conv"].append(
                code_of("bdc", r["termination_convention"])
                if r["termination_convention"] != "" else conv)
            cols["b_rule"].append(code_of("rule", r["rule"]) if r["rule"] != "" else RULE_BACKWARD)
            cols["b_eom"].append(code_of("flag", r["end_of_month"]))
            cols["b_first"].append(code_of("date", r["first_date"]))
            cols["b_ntl"].append(code_of("date", r["next_to_last_date"]))
            adc = code_of("daycounter", r["accrual_day_counter"]) \
                if r["accrual_day_counter"] != "" else 0
            cols["b_accrual_dc"].append(adc)
            cols["b_first_dc"].append(
                code_of("daycounter", r["first_period_day_counter"])
                if r["first_period_day_counter"] != "" else 0)
            cols["b_pay_conv"].append(
                code_of("bdc", r["payment_convention"])
                if r["payment_convention"] != "" else BDC_FOLLOWING)
            cols["b_pay_cal"].append(
                code_of("calendar", r["payment_calendar"])
                if r["payment_calendar"] != "" else -1)
            cols["b_maturity"].append(code_of("date", r["maturity_date"]))
            if r["yield_day_counter"] != "":
                ydc = code_of("daycounter", r["yield_day_counter"])
            elif btype == BOND_FIXED:
                ydc = adc
            else:
                ydc = DC_ACT365F
            cols["b_ydc"].append(ydc)
            cols["b_ycomp"].append(
                code_of("comp", r["yield_compounding"])
                if r["yield_compounding"] != "" else COMP_COMPOUNDED)
            cols["cr_lo"].append(len(rates))
            if btype == BOND_FIXED:
                if r["bond_key"] in vec:
                    for k, rate in sorted(vec[r["bond_key"]]):
                        rates.append(rate)
                elif r["coupon_rate"] != "":
                    rates.append(float_of(r["coupon_rate"]))
            cols["cr_cnt"].append(len(rates) - cols["cr_lo"][-1])
        except (ValueError, KeyError) as e:
            raise ValueError(
                "bonds.csv line " + str(i + 2) + " (bond_key '" + r["bond_key"] + "'): "
                + str(e) + " (run check_inputs() for a full report)")
    out = {}
    for name in names:
        if name == "b_face" or name == "b_redemption":
            out[name] = np.array(cols[name], dtype=np.float64)
        else:
            out[name] = np.array(cols[name], dtype=np.int64)
    out["cr_rate"] = np.array(rates, dtype=np.float64)
    return out


def b_type_arr():
    """Bond type code per bond (``BOND_FIXED`` / ``BOND_ZERO``), int64 [N]."""
    return bond_columns()["b_type"]


def b_face_arr():
    """Face amount per bond, float64 [N]."""
    return bond_columns()["b_face"]


def b_settle_days_arr():
    """Settlement days per bond, int64 [N]."""
    return bond_columns()["b_settle_days"]


def b_calendar_arr():
    """Calendar code per bond (the schedule calendar of a FixedRate bond), int64 [N]."""
    return bond_columns()["b_calendar"]


def b_issue_arr():
    """Issue date serial per bond (0 = none), int64 [N]."""
    return bond_columns()["b_issue"]


def b_redemption_arr():
    """Redemption per bond in percent of face (blank gives 100.0), float64 [N]."""
    return bond_columns()["b_redemption"]


def b_spread_idx_arr():
    """Spread index per bond into :func:`spread_ids` (-1 = no spread: the plain curve), int64 [N]."""
    return bond_columns()["b_spread_idx"]


def b_eff_arr():
    """Schedule effective date serial per bond (0 for ZeroCoupon), int64 [N]."""
    return bond_columns()["b_eff"]


def b_term_arr():
    """Schedule termination date serial per bond (0 for ZeroCoupon), int64 [N]."""
    return bond_columns()["b_term"]


def b_tenor_n_arr():
    """Schedule tenor length per bond (blank tenor gives 0D), int64 [N]."""
    return bond_columns()["b_tenor_n"]


def b_tenor_unit_arr():
    """Schedule tenor unit per bond (``TU_*``), int64 [N]."""
    return bond_columns()["b_tenor_unit"]


def b_conv_arr():
    """Schedule business-day convention per bond (blank gives Following), int64 [N]."""
    return bond_columns()["b_conv"]


def b_term_conv_arr():
    """Schedule termination-date convention per bond (blank gives the convention), int64 [N]."""
    return bond_columns()["b_term_conv"]


def b_rule_arr():
    """Date-generation rule per bond (blank gives Backward), int64 [N]."""
    return bond_columns()["b_rule"]


def b_eom_arr():
    """Schedule end-of-month flag per bond (0/1, blank gives 0), int64 [N]."""
    return bond_columns()["b_eom"]


def b_first_arr():
    """Schedule first date serial per bond (0 = none), int64 [N]."""
    return bond_columns()["b_first"]


def b_ntl_arr():
    """Schedule next-to-last date serial per bond (0 = none), int64 [N]."""
    return bond_columns()["b_ntl"]


def b_accrual_dc_arr():
    """Accrual day-counter code per bond (0 for ZeroCoupon), int64 [N]."""
    return bond_columns()["b_accrual_dc"]


def b_first_dc_arr():
    """First-period day-counter code per bond (0 = none), int64 [N]."""
    return bond_columns()["b_first_dc"]


def b_pay_conv_arr():
    """Payment business-day convention per bond (blank gives Following), int64 [N]."""
    return bond_columns()["b_pay_conv"]


def b_pay_cal_arr():
    """Payment calendar code per bond (-1 = the schedule calendar), int64 [N]."""
    return bond_columns()["b_pay_cal"]


def cr_lo_arr():
    """Index of each bond's first coupon rate in :func:`cr_rate_arr`, int64 [N]."""
    return bond_columns()["cr_lo"]


def cr_cnt_arr():
    """Number of coupon rates of each bond (0 for ZeroCoupon), int64 [N]."""
    return bond_columns()["cr_cnt"]


def cr_rate_arr():
    """Coupon rates of all bonds, concatenated in bond order (CSR values), float64."""
    return bond_columns()["cr_rate"]


def b_maturity_arr():
    """Maturity date serial per bond (the input of a ZeroCoupon bond; 0 if blank), int64 [N]."""
    return bond_columns()["b_maturity"]


def b_ydc_arr():
    """Yield-quote day-counter code per bond, int64 [N].

    Blank gives the accrual day counter (FixedRate) or Actual365Fixed (ZeroCoupon).
    """
    return bond_columns()["b_ydc"]


def b_ycomp_arr():
    """Yield-quote compounding per bond (blank gives Compounded), int64 [N]."""
    return bond_columns()["b_ycomp"]


def b_yfreq_arr():
    """Yield-quote frequency per bond, int64 [N].

    Blank gives, for a FixedRate bond, the frequency of its tenor
    (``dates.period_frequency``) when that is a regular frequency (Annual to
    Daily), else Annual; for a ZeroCoupon bond, Annual.
    """
    cols = bond_columns()
    df = bond_table()
    out = []
    for i, s in enumerate(df["yield_frequency"].tolist()):
        if s != "":
            out.append(code_of("freq", s))
        elif cols["b_type"][i] == BOND_FIXED:
            f = dates.period_frequency(int(cols["b_tenor_n"][i]), int(cols["b_tenor_unit"][i]))
            if f == FREQ_NO_FREQUENCY or f == FREQ_ONCE or f == FREQ_OTHER_FREQUENCY:
                f = FREQ_ANNUAL
            out.append(int(f))
        else:
            out.append(FREQ_ANNUAL)
    return np.array(out, dtype=np.int64)


def val_date_arr():
    """Valuation date serial of each t, int64 [T]."""
    T = n_times()
    out = np.zeros(T, dtype=np.int64)
    df = val_date_table()
    for ts, ds in zip(df["t"].tolist(), df["val_date"].tolist()):
        t = code_of("int", ts)
        if 0 <= t and t < T:
            out[t] = code_of("date", ds)
    return out


def curve_columns():
    """Curve conventions per (scen_id, t) as [S, T] numpy arrays, keyed by array name without ``_arr``.

    Row ``scen_id - 1``, column ``t``. Blank cells take the pureql
    constructor defaults: compounding Continuous, frequency Annual,
    extrapolate 0, spread compounding Continuous, spread frequency
    NoFrequency; a blank flat_rate is NaN. A (scen_id, t) missing from
    curve_params.csv holds -1 (NaN for ``c_flat``).
    """
    S = n_scen()
    T = n_times()
    names = ("c_type", "c_dc", "c_comp", "c_freq", "c_extrap", "c_sp_comp", "c_sp_freq")
    out = {}
    for name in names:
        out[name] = np.full((S, T), -1, dtype=np.int64)
    out["c_flat"] = np.full((S, T), np.nan, dtype=np.float64)
    for i, r in enumerate(curve_param_table().to_dict("records")):
        try:
            s = code_of("int", r["scen_id"]) - 1
            t = code_of("int", r["t"])
            if not (0 <= s and s < S and 0 <= t and t < T):
                continue
            out["c_type"][s, t] = code_of("curve_type", r["curve_type"])
            out["c_dc"][s, t] = code_of("daycounter", r["day_counter"])
            out["c_comp"][s, t] = code_of("comp", r["compounding"]) \
                if r["compounding"] != "" else COMP_CONTINUOUS
            out["c_freq"][s, t] = code_of("freq", r["frequency"]) \
                if r["frequency"] != "" else FREQ_ANNUAL
            out["c_extrap"][s, t] = code_of("flag", r["extrapolate"])
            if r["flat_rate"] != "":
                out["c_flat"][s, t] = float_of(r["flat_rate"])
            out["c_sp_comp"][s, t] = code_of("comp", r["spread_compounding"]) \
                if r["spread_compounding"] != "" else COMP_CONTINUOUS
            out["c_sp_freq"][s, t] = code_of("freq", r["spread_frequency"]) \
                if r["spread_frequency"] != "" else FREQ_NO_FREQUENCY
        except ValueError as e:
            raise ValueError(
                "curve_params.csv line " + str(i + 2) + ": " + str(e)
                + " (run check_inputs() for a full report)")
    return out


def c_type_arr():
    """Curve type per (scen, t) (``CURVE_ZERO`` / ``CURVE_FLAT``; -1 if absent), int64 [S, T]."""
    return curve_columns()["c_type"]


def c_dc_arr():
    """Curve day-counter code per (scen, t), int64 [S, T]."""
    return curve_columns()["c_dc"]


def c_comp_arr():
    """Curve compounding per (scen, t) (blank gives Continuous), int64 [S, T]."""
    return curve_columns()["c_comp"]


def c_freq_arr():
    """Curve frequency per (scen, t) (blank gives Annual), int64 [S, T]."""
    return curve_columns()["c_freq"]


def c_extrap_arr():
    """Curve extrapolation flag per (scen, t) (0/1, blank gives 0), int64 [S, T]."""
    return curve_columns()["c_extrap"]


def c_flat_arr():
    """FlatForward rate per (scen, t) (NaN if blank), float64 [S, T]."""
    return curve_columns()["c_flat"]


def c_sp_comp_arr():
    """Zero-spread compounding per (scen, t) (blank gives Continuous), int64 [S, T]."""
    return curve_columns()["c_sp_comp"]


def c_sp_freq_arr():
    """Zero-spread frequency per (scen, t) (blank gives NoFrequency), int64 [S, T]."""
    return curve_columns()["c_sp_freq"]


def node_columns():
    """Curve nodes in CSR form, keyed by array name without ``_arr``.

    ``n_lo``/``n_cnt`` [S, T] index ``n_date``/``n_rate``; within a
    (scen_id, t) the nodes are in ``node`` order. A node given by tenor is
    resolved to ``dates.advance_date(val_date(t), n, unit)``. Rows whose
    (scen_id, t) lies outside the curve_params grid are left out.
    """
    S = n_scen()
    T = n_times()
    lo = np.zeros((S, T), dtype=np.int64)
    cnt = np.zeros((S, T), dtype=np.int64)
    rows = []
    for i, r in enumerate(curve_node_table().to_dict("records")):
        s = code_of("int", r["scen_id"]) - 1
        t = code_of("int", r["t"])
        if 0 <= s and s < S and 0 <= t and t < T:
            rows.append((s, t, code_of("int", r["node"]), i, r["date"], r["tenor"], r["rate"]))
    rows.sort()
    node_dates = []
    node_rates = []
    for s, t, nd, i, ds, ts, rs in rows:
        try:
            if cnt[s, t] == 0:
                lo[s, t] = len(node_dates)
            cnt[s, t] += 1
            if ds != "":
                d = code_of("date", ds)
            elif ts != "":
                d = dates.advance_date(
                    int(val_date_arr()[t]), code_of("tenor_n", ts), code_of("tenor_unit", ts))
            else:
                d = 0
            node_dates.append(int(d))
            node_rates.append(float_of(rs))
        except ValueError as e:
            raise ValueError(
                "curve_nodes.csv line " + str(i + 2) + ": " + str(e)
                + " (run check_inputs() for a full report)")
    return {"n_lo": lo, "n_cnt": cnt,
            "n_date": np.array(node_dates, dtype=np.int64),
            "n_rate": np.array(node_rates, dtype=np.float64)}


def n_lo_arr():
    """Index of the first node of each (scen, t) in :func:`n_date_arr`, int64 [S, T]."""
    return node_columns()["n_lo"]


def n_cnt_arr():
    """Number of nodes of each (scen, t), int64 [S, T]."""
    return node_columns()["n_cnt"]


def n_date_arr():
    """Node date serials, concatenated per (scen, t) (CSR values), int64."""
    return node_columns()["n_date"]


def n_rate_arr():
    """Node zero rates, concatenated per (scen, t) (CSR values), float64."""
    return node_columns()["n_rate"]


def sp_arr():
    """Zero spread per (scen, t, spread index), float64 [S, T, len(spread_ids())]; NaN where absent."""
    S = n_scen()
    T = n_times()
    sid = {}
    for i, k in enumerate(spread_ids()):
        sid[k] = i
    out = np.full((S, T, len(sid)), np.nan, dtype=np.float64)
    for i, r in enumerate(spread_table().to_dict("records")):
        s = code_of("int", r["scen_id"]) - 1
        t = code_of("int", r["t"])
        if 0 <= s and s < S and 0 <= t and t < T and r["spread_id"] in sid:
            out[s, t, sid[r["spread_id"]]] = float_of(r["spread"])
    return out


def quote_columns():
    """The sparse price and yield quotes as numpy arrays, keyed by array name without ``_arr``.

    Quotes usually exist at a few (scen_id, t) only, so they are held per
    *slot* rather than in a dense [S, T, N] array: every (scen_id, t) with at
    least one price gets a price slot, numbered in (scen_id, t) order, and
    likewise for yields.

    * ``px_slot`` int64 [S, T]: the price slot of (scen_id, t), -1 if none;
    * ``px_val`` float64 [NPS, N]: the price of bond ``b`` in a slot, NaN if none;
    * ``px_type`` int64 [NPS, N]: ``PRICE_CLEAN`` (also for a blank
      price_type) or ``PRICE_DIRTY``, -1 if no price;
    * ``yl_slot`` int64 [S, T] and ``yl_val`` float64 [NYS, N]: the same for yields.

    From ``prices.csv`` (scen_id, t, bond_key, price, price_type) and
    ``yields.csv`` (scen_id, t, bond_key, yield). Rows outside the
    curve_params grid or naming an unknown bond_key are left out
    (:func:`quote_errors` reports them).
    """
    S = n_scen()
    T = n_times()
    N = n_bonds()
    bidx = {}
    for i, k in enumerate(bond_keys()):
        if k not in bidx:
            bidx[k] = i
    out = {}
    for prefix, fname, df, col in (("px", price_file, price_table(), "price"),
                                   ("yl", yield_file, yield_table(), "yield")):
        rows = []
        for i, r in enumerate(df.to_dict("records")):
            try:
                s = code_of("int", r["scen_id"]) - 1
                t = code_of("int", r["t"])
                if 0 <= s and s < S and 0 <= t and t < T and r["bond_key"] in bidx:
                    ptype = PRICE_CLEAN
                    if col == "price" and r["price_type"] != "":
                        ptype = code_of("price_type", r["price_type"])
                    rows.append((s, t, bidx[r["bond_key"]], float_of(r[col]), ptype))
            except ValueError as e:
                raise ValueError(fname + " line " + str(i + 2) + ": " + str(e)
                                 + " (run check_inputs() for a full report)")
        slot = np.full((S, T), -1, dtype=np.int64)
        used = set()
        for rw in rows:
            used.add((rw[0], rw[1]))
        cells = sorted(used)
        for k, st in enumerate(cells):
            slot[st[0], st[1]] = k
        val = np.full((len(cells), N), np.nan, dtype=np.float64)
        typ = np.full((len(cells), N), -1, dtype=np.int64)
        for s, t, bo, x, ptype in rows:
            val[slot[s, t], bo] = x
            typ[slot[s, t], bo] = ptype
        out[prefix + "_slot"] = slot
        out[prefix + "_val"] = val
        if prefix == "px":
            out["px_type"] = typ
    return out


def px_slot_arr():
    """The price slot of each (scen, t) (-1 = no prices there), int64 [S, T]."""
    return quote_columns()["px_slot"]


def px_val_arr():
    """The quoted price of each bond per price slot (NaN = none), float64 [NPS, N]."""
    return quote_columns()["px_val"]


def px_type_arr():
    """The price type of each quoted price (``PRICE_CLEAN`` / ``PRICE_DIRTY``; -1 = none), int64 [NPS, N]."""
    return quote_columns()["px_type"]


def yl_slot_arr():
    """The yield slot of each (scen, t) (-1 = no yields there), int64 [S, T]."""
    return quote_columns()["yl_slot"]


def yl_val_arr():
    """The quoted yield of each bond per yield slot (NaN = none), float64 [NYS, N]."""
    return quote_columns()["yl_val"]


def table_errors():
    """Problems reading the input files (missing files or required columns), as a tuple of messages."""
    errs = []
    for reader in ("bond_table", "coupon_rate_table", "val_date_table",
                   "curve_param_table", "curve_node_table", "spread_table",
                   "price_table", "yield_table"):
        try:
            if reader == "bond_table":
                bond_table()
            elif reader == "coupon_rate_table":
                coupon_rate_table()
            elif reader == "val_date_table":
                val_date_table()
            elif reader == "curve_param_table":
                curve_param_table()
            elif reader == "curve_node_table":
                curve_node_table()
            elif reader == "spread_table":
                spread_table()
            elif reader == "price_table":
                price_table()
            else:
                yield_table()
        except ValueError as e:
            errs.append(str(e))
    return tuple(errs)


def bond_errors():
    """Problems in bonds.csv and coupon_rates.csv (v1 scope and consistency), as a tuple of messages."""
    errs = []
    df = bond_table()
    if len(df) > MAX_BONDS:
        errs.append("bonds.csv: " + str(len(df)) + " bonds exceed MAX_BONDS (" + str(MAX_BONDS) + ")")
    vec_keys = set(coupon_rate_table()["bond_key"].tolist())
    first_line = {}
    btypes = {}
    for i, r in enumerate(df.to_dict("records")):
        key = r["bond_key"]
        where = "bonds.csv line " + str(i + 2) + " (bond_key '" + key + "')"
        if key == "":
            errs.append(where + ": bond_key is blank")
        elif key in first_line:
            errs.append(where + ": duplicate bond_key (first on line " + str(first_line[key]) + ")")
        else:
            first_line[key] = i + 2
        msgs = []
        for col, kind in (("bond_type", "bond_type"), ("face_amount", "float"),
                          ("settlement_days", "int"), ("calendar", "calendar")):
            e = parse_error(kind, r[col])
            if e:
                msgs.append(col + ": " + e)
        for col, kind in (("issue_date", "date"), ("redemption", "float"),
                          ("payment_convention", "bdc"), ("yield_day_counter", "daycounter"),
                          ("yield_compounding", "comp"), ("yield_frequency", "freq"),
                          ("effective_date", "date"), ("termination_date", "date"),
                          ("tenor", "tenor_n"), ("convention", "bdc"),
                          ("termination_convention", "bdc"), ("rule", "rule"),
                          ("end_of_month", "flag"), ("first_date", "date"),
                          ("next_to_last_date", "date"), ("coupon_rate", "float"),
                          ("accrual_day_counter", "daycounter"),
                          ("first_period_day_counter", "daycounter"),
                          ("payment_calendar", "calendar"), ("maturity_date", "date")):
            if r[col] != "":
                e = parse_error(kind, r[col])
                if e:
                    msgs.append(col + ": " + e)
                elif kind == "date":
                    d = code_of("date", r[col])
                    if d < MIN_SERIAL or d > MAX_SERIAL:
                        msgs.append(col + ": date " + r[col] + " outside 1901-01-01..2199-12-31")
        if not parse_error("int", r["settlement_days"]):
            nsd = code_of("int", r["settlement_days"])
            if nsd < 0 or nsd > MAX_SETTLE_DAYS:
                msgs.append("settlement_days " + str(nsd) + " outside 0..MAX_SETTLE_DAYS ("
                            + str(MAX_SETTLE_DAYS) + ")")
        btype = -1
        if not parse_error("bond_type", r["bond_type"]):
            btype = code_of("bond_type", r["bond_type"])
            btypes[key] = btype
        if btype == BOND_FIXED:
            for col in ("effective_date", "termination_date", "tenor", "accrual_day_counter"):
                if r[col] == "":
                    msgs.append(col + " is required for a FixedRate bond")
            if r["effective_date"] != "" and r["termination_date"] != "" \
                    and not parse_error("date", r["effective_date"]) \
                    and not parse_error("date", r["termination_date"]):
                if not (code_of("date", r["effective_date"]) < code_of("date", r["termination_date"])):
                    msgs.append("effective_date " + r["effective_date"]
                                + " is not earlier than termination_date " + r["termination_date"])
            if r["rule"] != "" and not parse_error("rule", r["rule"]):
                if code_of("rule", r["rule"]) != RULE_BACKWARD:
                    msgs.append("rule " + r["rule"] + " is not supported in this model version "
                                "(only Backward; a 0D tenor gives the Zero rule)")
            if r["coupon_rate"] != "" and key in vec_keys:
                msgs.append("coupon rates given both in coupon_rate and in coupon_rates.csv")
            elif r["coupon_rate"] == "" and key not in vec_keys:
                msgs.append("no coupon rate (give coupon_rate or rows in coupon_rates.csv)")
        elif btype == BOND_ZERO:
            if r["maturity_date"] == "":
                msgs.append("maturity_date is required for a ZeroCoupon bond")
        if r["yield_frequency"] != "" and not parse_error("freq", r["yield_frequency"]):
            comp = COMP_COMPOUNDED
            if r["yield_compounding"] != "" and not parse_error("comp", r["yield_compounding"]):
                comp = code_of("comp", r["yield_compounding"])
            freq = code_of("freq", r["yield_frequency"])
            if (comp == COMP_COMPOUNDED or comp == COMP_SIMPLE_THEN_COMPOUNDED
                    or comp == COMP_COMPOUNDED_THEN_SIMPLE) \
                    and (freq == FREQ_ONCE or freq == FREQ_NO_FREQUENCY):
                msgs.append("yield_frequency " + r["yield_frequency"] + " is not allowed with "
                            "yield_compounding " + (r["yield_compounding"] or "Compounded")
                            + " (needs a frequency other than NoFrequency or Once)")
        for m in msgs:
            errs.append(where + ": " + m)
    crt = coupon_rate_table()
    ks = {}
    for i, r in enumerate(crt.to_dict("records")):
        where = "coupon_rates.csv line " + str(i + 2) + " (bond_key '" + r["bond_key"] + "')"
        if r["bond_key"] not in first_line:
            errs.append(where + ": bond_key not in bonds.csv")
        elif btypes.get(r["bond_key"], BOND_FIXED) != BOND_FIXED:
            errs.append(where + ": coupon rates given for a bond that is not FixedRate")
        e = parse_error("int", r["k"])
        if e:
            errs.append(where + ": k: " + e)
        else:
            if r["bond_key"] not in ks:
                ks[r["bond_key"]] = []
            ks[r["bond_key"]].append(code_of("int", r["k"]))
        e = parse_error("float", r["rate"])
        if e:
            errs.append(where + ": rate: " + e)
    for key, kk in ks.items():
        if sorted(kk) != list(range(len(kk))):
            errs.append("coupon_rates.csv (bond_key '" + key + "'): k must run 0, 1, ..., "
                        + str(len(kk) - 1) + " without gaps or duplicates (got "
                        + str(sorted(kk)) + ")")
    return tuple(errs)


def val_date_errors():
    """Problems in valuation_dates.csv, as a tuple of messages.

    t must run 0..T-1 once each, the dates must be valid, within range and
    strictly increasing in t.
    """
    errs = []
    df = val_date_table()
    T = len(df)
    if T == 0:
        errs.append("valuation_dates.csv: no valuation dates")
    if T > MAX_T:
        errs.append("valuation_dates.csv: " + str(T) + " dates exceed MAX_T (" + str(MAX_T) + ")")
    by_t = {}
    for i, r in enumerate(df.to_dict("records")):
        where = "valuation_dates.csv line " + str(i + 2)
        e = parse_error("int", r["t"])
        if e:
            errs.append(where + ": t: " + e)
            continue
        t = code_of("int", r["t"])
        if t < 0 or t >= T:
            errs.append(where + ": t " + str(t) + " outside 0.." + str(T - 1))
            continue
        if t in by_t:
            errs.append(where + ": duplicate t " + str(t))
            continue
        e = parse_error("date", r["val_date"])
        if e or r["val_date"] == "":
            errs.append(where + ": val_date: " + (e or "blank"))
            continue
        d = code_of("date", r["val_date"])
        if d < MIN_SERIAL or d > MAX_SERIAL:
            errs.append(where + ": val_date " + r["val_date"] + " outside 1901-01-01..2199-12-31")
            continue
        by_t[t] = d
    for t in range(1, T):
        if t in by_t and (t - 1) in by_t and not (by_t[t - 1] < by_t[t]):
            errs.append("valuation_dates.csv: val_date of t=" + str(t)
                        + " is not later than that of t=" + str(t - 1)
                        + " (valuation dates must be strictly increasing)")
    return tuple(errs)


def curve_errors():
    """Problems in curve_params.csv, as a tuple of messages.

    (scen_id, t) must form the dense grid 1..S x 0..T-1, each once; names
    must be v1 codes; a FlatForward needs flat_rate; Compounded,
    SimpleThenCompounded and CompoundedThenSimple need a frequency other than
    NoFrequency or Once (the InterestRate guard), for the curve and for the spread.
    """
    errs = []
    T = len(val_date_table())
    df = curve_param_table()
    seen = {}
    S = 0
    for i, r in enumerate(df.to_dict("records")):
        where = "curve_params.csv line " + str(i + 2)
        msgs = []
        e1 = parse_error("int", r["scen_id"])
        e2 = parse_error("int", r["t"])
        if e1:
            msgs.append("scen_id: " + e1)
        if e2:
            msgs.append("t: " + e2)
        if not e1 and not e2:
            s = code_of("int", r["scen_id"])
            t = code_of("int", r["t"])
            where = where + " (scen_id " + str(s) + ", t " + str(t) + ")"
            if s < 1 or s > MAX_SCEN:
                msgs.append("scen_id outside 1..MAX_SCEN (" + str(MAX_SCEN) + ")")
            elif t < 0 or t >= T:
                msgs.append("t outside 0.." + str(T - 1) + " (the rows of valuation_dates.csv)")
            elif (s, t) in seen:
                msgs.append("duplicate (scen_id, t) (first on line " + str(seen[(s, t)]) + ")")
            else:
                seen[(s, t)] = i + 2
                if s > S:
                    S = s
        e = parse_error("curve_type", r["curve_type"])
        if e:
            msgs.append("curve_type: " + e)
        e = parse_error("daycounter", r["day_counter"])
        if e:
            msgs.append("day_counter: " + e)
        for col, kind in (("compounding", "comp"), ("frequency", "freq"),
                          ("extrapolate", "flag"), ("flat_rate", "float"),
                          ("spread_compounding", "comp"), ("spread_frequency", "freq")):
            if r[col] != "":
                e = parse_error(kind, r[col])
                if e:
                    msgs.append(col + ": " + e)
        if not parse_error("curve_type", r["curve_type"]):
            if code_of("curve_type", r["curve_type"]) == CURVE_FLAT and r["flat_rate"] == "":
                msgs.append("flat_rate is required for a FlatForward curve")
        for ccol, fcol, fdefault in (("compounding", "frequency", FREQ_ANNUAL),
                                     ("spread_compounding", "spread_frequency", FREQ_NO_FREQUENCY)):
            if parse_error("comp", r[ccol] or "Continuous") or parse_error("freq", r[fcol] or "Annual"):
                continue
            comp = code_of("comp", r[ccol]) if r[ccol] != "" else COMP_CONTINUOUS
            freq = code_of("freq", r[fcol]) if r[fcol] != "" else fdefault
            if (comp == COMP_COMPOUNDED or comp == COMP_SIMPLE_THEN_COMPOUNDED
                    or comp == COMP_COMPOUNDED_THEN_SIMPLE) \
                    and (freq == FREQ_ONCE or freq == FREQ_NO_FREQUENCY):
                msgs.append(fcol + " " + (r[fcol] or "(blank: NoFrequency)") + " is not allowed with "
                            + ccol + " " + r[ccol]
                            + " (needs a frequency other than NoFrequency or Once)")
        for m in msgs:
            errs.append(where + ": " + m)
    if len(df) == 0:
        errs.append("curve_params.csv: no rows")
    missing = []
    for s in range(1, S + 1):
        for t in range(T):
            if (s, t) not in seen:
                missing.append("(" + str(s) + ", " + str(t) + ")")
    if missing:
        errs.append("curve_params.csv: the (scen_id, t) grid 1.." + str(S) + " x 0.." + str(T - 1)
                    + " is not dense; missing: " + ", ".join(missing[:20])
                    + (" ..." if len(missing) > 20 else ""))
    return tuple(errs)


def node_errors():
    """Problems in curve_nodes.csv, as a tuple of messages.

    Each node gives exactly one of date and tenor, and a rate; node numbers
    run 0..k-1 within a (scen_id, t). A ZeroCurve needs 2..MAX_NODES nodes
    whose dates (tenors resolved against val_date(t)) are strictly increasing
    and start at val_date(t). Their times under the curve's day counter
    (``dayCounter.yearFraction(val_date(t), date)``) must not be ``close``
    and must be strictly increasing: pureql's ``InterpolatedCurve.setupTimes``
    refuses two dates that map to the same time (as 30/360 maps the 30th and
    the 31st of a month), with the message given here. So every ZeroCurve
    pureql cannot build is rejected before any valuation, rather than when
    ``Valuation.curve_ok()`` first runs. Nodes of a FlatForward (scen_id, t)
    are ignored. Expects :func:`curve_errors` and :func:`val_date_errors` to
    be clean.

    Derived from QuantLib (BSD-3-Clause); see NOTICE.md.
    """
    # ported from pureql/termstructures/interpolatedcurve.py (ql/interpolatedcurve.hpp:100-115), QuantLib v1.43, BSD-3-Clause
    errs = []
    S = n_scen()
    T = n_times()
    groups = {}
    for i, r in enumerate(curve_node_table().to_dict("records")):
        where = "curve_nodes.csv line " + str(i + 2)
        msgs = []
        ok = True
        for col in ("scen_id", "t", "node"):
            e = parse_error("int", r[col])
            if e:
                msgs.append(col + ": " + e)
                ok = False
        if ok:
            s = code_of("int", r["scen_id"])
            t = code_of("int", r["t"])
            nd = code_of("int", r["node"])
            where = where + " (scen_id " + str(s) + ", t " + str(t) + ", node " + str(nd) + ")"
            if s < 1 or s > S or t < 0 or t >= T:
                msgs.append("(scen_id, t) is not in the curve_params.csv grid")
                ok = False
        if (r["date"] == "") == (r["tenor"] == ""):
            msgs.append("give exactly one of date and tenor")
            ok = False
        elif r["date"] != "":
            e = parse_error("date", r["date"])
            if e:
                msgs.append("date: " + e)
                ok = False
        else:
            e = parse_error("tenor_n", r["tenor"])
            if e:
                msgs.append("tenor: " + e)
                ok = False
        e = parse_error("float", r["rate"])
        if e:
            msgs.append("rate: " + e)
            ok = False
        if ok:
            if r["date"] != "":
                d = code_of("date", r["date"])
            else:
                try:
                    d = dates.advance_date(
                        int(val_date_arr()[t]), code_of("tenor_n", r["tenor"]),
                        code_of("tenor_unit", r["tenor"]))
                except ValueError as e:
                    msgs.append("tenor " + r["tenor"] + " from val_date: " + str(e))
                    d = 0
                    ok = False
            if ok and (d < MIN_SERIAL or d > MAX_SERIAL):
                msgs.append("node date outside 1901-01-01..2199-12-31")
                ok = False
            if ok:
                if (s, t) not in groups:
                    groups[(s, t)] = []
                groups[(s, t)].append((nd, int(d), i + 2))
        for m in msgs:
            errs.append(where + ": " + m)
    for s in range(1, S + 1):
        for t in range(T):
            if int(c_type_arr()[s - 1, t]) != CURVE_ZERO:
                continue
            where = "curve_nodes.csv (scen_id " + str(s) + ", t " + str(t) + ", ZeroCurve)"
            g = sorted(groups.get((s, t), []))
            nds = [x[0] for x in g]
            if nds != list(range(len(g))):
                errs.append(where + ": node numbers must run 0, 1, ..., k-1 without gaps or "
                            "duplicates (got " + str(nds) + ")")
                continue
            if len(g) < 2:
                errs.append(where + ": a ZeroCurve needs at least 2 nodes (got " + str(len(g)) + ")")
                continue
            if len(g) > MAX_NODES:
                errs.append(where + ": " + str(len(g)) + " nodes exceed MAX_NODES (" + str(MAX_NODES) + ")")
            v = int(val_date_arr()[t])
            if g[0][1] != v:
                errs.append(where + ": node 0 must be the valuation date (line " + str(g[0][2]) + ")")
            dc = int(c_dc_arr()[s - 1, t])
            tp = float(dates.year_fraction(dc, v, g[0][1], 0, 0))
            for k in range(1, len(g)):
                if not (g[k - 1][1] < g[k][1]):
                    errs.append(where + ": node dates must be strictly increasing (node "
                                + str(k) + ", line " + str(g[k][2]) + ")")
                    break
                tn = float(dates.year_fraction(dc, v, g[k][1], 0, 0))
                if lib.close(float(tn), float(tp)):
                    errs.append(where + ": two passed dates (" + lib.long_date(g[k - 1][1]) + " and "
                                + lib.long_date(g[k][1]) + ") correspond to the same time under this "
                                "curve's day count convention (" + dates.daycounter_name(dc) + ") (node "
                                + str(k) + ", line " + str(g[k][2]) + ")")
                    break
                if not (tn > tp):
                    errs.append(where + ": node times must be strictly increasing (node "
                                + str(k) + ", line " + str(g[k][2]) + ")")
                    break
                tp = tn
    return tuple(errs)


def spread_errors():
    """Problems in spreads.csv, as a tuple of messages.

    Each (scen_id, t, spread_id) at most once within the curve_params grid,
    and every spread_id a bond uses has a spread at every (scen_id, t).
    Expects :func:`curve_errors` and :func:`val_date_errors` to be clean.
    """
    errs = []
    S = n_scen()
    T = n_times()
    seen = {}
    for i, r in enumerate(spread_table().to_dict("records")):
        where = "spreads.csv line " + str(i + 2)
        msgs = []
        ok = True
        for col in ("scen_id", "t"):
            e = parse_error("int", r[col])
            if e:
                msgs.append(col + ": " + e)
                ok = False
        if r["spread_id"] == "":
            msgs.append("spread_id is blank")
            ok = False
        e = parse_error("float", r["spread"])
        if e:
            msgs.append("spread: " + e)
        if ok:
            s = code_of("int", r["scen_id"])
            t = code_of("int", r["t"])
            if s < 1 or s > S or t < 0 or t >= T:
                msgs.append("(scen_id " + str(s) + ", t " + str(t) + ") is not in the curve_params.csv grid")
            elif (s, t, r["spread_id"]) in seen:
                msgs.append("duplicate (scen_id, t, spread_id) (first on line "
                            + str(seen[(s, t, r["spread_id"])]) + ")")
            else:
                seen[(s, t, r["spread_id"])] = i + 2
        for m in msgs:
            errs.append(where + ": " + m)
    used = {}
    for key, k in zip(bond_table()["bond_key"].tolist(), bond_table()["spread_id"].tolist()):
        if k != "" and k not in used:
            used[k] = key
    for k, key in used.items():
        missing = []
        for s in range(1, S + 1):
            for t in range(T):
                if (s, t, k) not in seen:
                    missing.append("(" + str(s) + ", " + str(t) + ")")
        if missing:
            errs.append("spreads.csv: spread_id '" + k + "' (used by bond '" + key
                        + "') has no spread at (scen_id, t) " + ", ".join(missing[:20])
                        + (" ..." if len(missing) > 20 else ""))
    return tuple(errs)


def quote_errors():
    """Problems in the optional prices.csv and yields.csv, as a tuple of messages.

    Each row names a known bond_key at a (scen_id, t) of the grid, at most
    once, with a number; price_type is blank (Clean), Clean or Dirty.
    """
    errs = []
    S = n_scen()
    T = n_times()
    keys = set(bond_table()["bond_key"].tolist())
    for fname, df, col in ((price_file, price_table(), "price"),
                           (yield_file, yield_table(), "yield")):
        seen = {}
        for i, r in enumerate(df.to_dict("records")):
            where = fname + " line " + str(i + 2)
            msgs = []
            ok = True
            for c in ("scen_id", "t"):
                e = parse_error("int", r[c])
                if e:
                    msgs.append(c + ": " + e)
                    ok = False
            if r["bond_key"] not in keys:
                msgs.append("bond_key '" + r["bond_key"] + "' not in bonds.csv")
            e = parse_error("float", r[col])
            if e:
                msgs.append(col + ": " + e)
            if col == "price" and r["price_type"] != "":
                e = parse_error("price_type", r["price_type"])
                if e:
                    msgs.append("price_type: " + e)
            if ok:
                s = code_of("int", r["scen_id"])
                t = code_of("int", r["t"])
                if s < 1 or s > S or t < 0 or t >= T:
                    msgs.append("(scen_id " + str(s) + ", t " + str(t) + ") is not in the curve_params.csv grid")
                elif (s, t, r["bond_key"]) in seen:
                    msgs.append("duplicate (scen_id, t, bond_key) (first on line "
                                + str(seen[(s, t, r["bond_key"])]) + ")")
                else:
                    seen[(s, t, r["bond_key"])] = i + 2
            for m in msgs:
                errs.append(where + ": " + m)
    return tuple(errs)


def check_inputs():
    """Validate the inputs against the v1 scope and for consistency; return True.

    Runs in stages, each only if the previous ones found nothing: the files
    and their required columns (:func:`table_errors`); bonds, coupon rates and
    valuation dates (:func:`bond_errors`, :func:`val_date_errors`); curve
    parameters (:func:`curve_errors`); curve nodes, spreads and quotes
    (:func:`node_errors`, :func:`spread_errors`, :func:`quote_errors`).
    Raises ``ValueError`` listing every problem of the failing stage.
    """
    errs = list(table_errors())
    if not errs:
        errs = list(bond_errors()) + list(val_date_errors())
    if not errs:
        errs = list(curve_errors())
    if not errs:
        errs = list(node_errors()) + list(spread_errors()) + list(quote_errors())
    if errs:
        shown = errs[:50]
        more = "" if len(errs) <= 50 else "\n  ... and " + str(len(errs) - 50) + " more"
        raise ValueError("invalid inputs in " + input_path() + " (" + str(len(errs))
                         + " problem(s)):\n  " + "\n  ".join(shown) + more)
    return True


# ---------------------------------------------------------------------------
# References

input_dir = ""

bond_file = "bonds.csv"

coupon_rate_file = "coupon_rates.csv"

val_date_file = "valuation_dates.csv"

curve_param_file = "curve_params.csv"

curve_node_file = "curve_nodes.csv"

spread_file = "spreads.csv"

price_file = "prices.csv"

yield_file = "yields.csv"

include_reference_date_events = 0

include_todays_cashflows = -1

engine_include_settlement_flows = -1

nontradable_policy = 0

solver_error_policy = 0

output_level = 1

yield_solver = 0

yield_accuracy = 1e-10

yield_max_evaluations = 100

yield_guess = 0.05

zspread_accuracy = 1e-10

zspread_max_evaluations = 100

zspread_guess = 0.0

zspread_price_source = 0

dates = ("Interface", ("..", "Dates"), "auto")

lib = ("Interface", ("..", "Lib"), "auto")
