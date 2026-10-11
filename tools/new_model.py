"""Create the BondPortfolio model skeleton (one-off).

Creates the Spaces, the Space formulas, the References and the model-level
constants of ``docs/model-contract.md`` section 2, then writes the model to
``bond_portfolio/BondPortfolio`` in modelx's serializer-8 format. Formulas are
afterwards edited in place in ``bond_portfolio/BondPortfolio/<Space>/__init__.py``.

Run once. Refuses to overwrite an existing model unless ``--force`` is given.
"""

import datetime
import math
import pathlib
import sys

import numpy
import pandas
import modelx as mx

ROOT = pathlib.Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / "bond_portfolio" / "BondPortfolio"

# docs/model-contract.md section 2. Values equal pureql's enums where pureql has one.
CONSTANTS = dict(
    # BusinessDayConvention (pureql time/businessdayconvention.py:66-73)
    BDC_FOLLOWING=0, BDC_MODIFIED_FOLLOWING=1, BDC_PRECEDING=2, BDC_MODIFIED_PRECEDING=3,
    BDC_UNADJUSTED=4, BDC_HALF_MONTH_MODIFIED_FOLLOWING=5, BDC_NEAREST=6,
    # TimeUnit (time/timeunit.py:95-98)
    TU_DAYS=0, TU_WEEKS=1, TU_MONTHS=2, TU_YEARS=3,
    # Frequency (time/frequency.py:66-78)
    FREQ_NO_FREQUENCY=-1, FREQ_ONCE=0, FREQ_ANNUAL=1, FREQ_SEMIANNUAL=2,
    FREQ_EVERY_FOURTH_MONTH=3, FREQ_QUARTERLY=4, FREQ_BIMONTHLY=6, FREQ_MONTHLY=12,
    FREQ_EVERY_FOURTH_WEEK=13, FREQ_BIWEEKLY=26, FREQ_WEEKLY=52, FREQ_DAILY=365,
    FREQ_OTHER_FREQUENCY=999,
    # Compounding (compounding.py:56-60)
    COMP_SIMPLE=0, COMP_COMPOUNDED=1, COMP_CONTINUOUS=2,
    COMP_SIMPLE_THEN_COMPOUNDED=3, COMP_COMPOUNDED_THEN_SIMPLE=4,
    # DateGeneration.Rule (time/dategenerationrule.py:62-71)
    RULE_BACKWARD=0, RULE_FORWARD=1, RULE_ZERO=2,
    # Duration.Type (cashflows/duration.py:54-56), Bond.Price.Type (instruments/bond.py:185-186)
    DUR_SIMPLE=0, DUR_MACAULAY=1, DUR_MODIFIED=2,
    PRICE_DIRTY=0, PRICE_CLEAN=1,
    # Weekday (time/weekday.py:83-89)
    SUNDAY=1, MONDAY=2, TUESDAY=3, WEDNESDAY=4, THURSDAY=5, FRIDAY=6, SATURDAY=7,
    # Month (time/date.py)
    JANUARY=1, FEBRUARY=2, MARCH=3, APRIL=4, MAY=5, JUNE=6, JULY=7, AUGUST=8,
    SEPTEMBER=9, OCTOBER=10, NOVEMBER=11, DECEMBER=12,
    # model codes
    CAL_NULL=0, CAL_TARGET=1, CAL_US_SETTLEMENT=2, CAL_US_GOVBOND=3,
    DC_ACT360=1, DC_ACT365F=2, DC_30360_USA=10, DC_30360_BB=11, DC_30360_EU=12,
    BOND_FIXED=0, BOND_ZERO=1,
    CURVE_ZERO=0, CURVE_FLAT=1,
    CF_COUPON=0, CF_AMORTIZING=1, CF_REDEMPTION=2,
    ROLE_ENGINE=0, ROLE_SETTLE=1, ROLE_EXPIRY=2,
    SOLVE_YIELD=0, SOLVE_ZSPREAD=1,
    NT_ENGINE=0, NT_RAISE=1, ERR_RAISE=0, ERR_NAN=1,
    NULL_DATE=0, MIN_SERIAL=367, MAX_SERIAL=109574,
    # numerics
    QL_EPSILON=2.220446049250313e-16, CLOSE_N=42, ZERO_RATE_DT=0.0001,
    ZSPREAD_STEP=0.01, BASIS_POINT=0.0001,
    # compile-time limits (build/spec.py sizes are generated from these)
    MAX_BONDS=12000, MAX_FLOWS=480000, MAX_KD=40000, MAX_NODES=64, MAX_T=1201,
    CAL_MAX=4, MAX_SETTLE_DAYS=7, MAX_SCHED=1200, MAX_SCEN=1000,
)

DATA_REFS = dict(
    input_dir="",
    bond_file="bonds.csv",
    coupon_rate_file="coupon_rates.csv",
    val_date_file="valuation_dates.csv",
    curve_param_file="curve_params.csv",
    curve_node_file="curve_nodes.csv",
    spread_file="spreads.csv",
    price_file="prices.csv",
    yield_file="yields.csv",
    # Settings replacements (tri-states: -1 None, 0 False, 1 True)
    include_reference_date_events=0,
    include_todays_cashflows=-1,
    engine_include_settlement_flows=-1,
    # policies
    nontradable_policy=0,
    solver_error_policy=0,
    output_level=1,
    # solvers
    yield_solver=0,
    yield_accuracy=1e-10,
    yield_max_evaluations=100,
    yield_guess=0.05,
    zspread_accuracy=1e-10,
    zspread_max_evaluations=100,
    zspread_guess=0.0,
    zspread_price_source=0,
)

MODEL_DOC = """\
Bond portfolio model transcribed from quantlib-migration's ``pureql``.

``BondPortfolio`` generates the cash flows of fixed-rate and zero-coupon bonds
and values them at t=0 and at future valuation points under scenarios, with the
logic of QuantLib v1.43 re-expressed as modelx formulas. It does not import
QuantLib or pureql: every derived formula carries a provenance comment and the
derived files are licensed BSD-3-Clause; see NOTICE.md at the project root.

**Spaces**

:mod:`~.BondPortfolio.Data`
    Reads the input CSV files and holds run settings.
:mod:`~.BondPortfolio.Lib`
    Canonical numerics: IEEE helpers, comparisons, InterestRate, cash-flow predicates.
:mod:`~.BondPortfolio.Dates`
    Date algebra on integer serial numbers, calendars, business-day
    adjustment and day counters.
:mod:`~.BondPortfolio.Bond`
    ``Bond[b]`` generates the schedule and leg of bond ``b`` (one row of bonds.csv).
:mod:`~.BondPortfolio.Legs`
    The portfolio leg as flat (CSR) arrays and the cash-flow table.
:mod:`~.BondPortfolio.Proj`
    Cash flows bucketed into the projection periods between valuation dates.
:mod:`~.BondPortfolio.Valuation`
    ``Valuation[scen_id, t]`` values every bond at valuation date ``t`` under
    scenario ``scen_id``.

Example::

    >>> import modelx as mx
    >>> m = mx.read_model("bond_portfolio/BondPortfolio")
    >>> m.Data.input_dir = "bond_portfolio"
    >>> m.Legs.cashflow_frame()
"""

SPACE_DOCS = {
    "Data": "Inputs read from CSV files, and run settings.\n\n"
            "All readers live here, so each file is read once per model.\n"
            "Set :attr:`input_dir` before calculating; when it is empty the\n"
            "directory containing the model is used.",
    "Lib": "Canonical numerics transcribed from pureql.\n\n"
           "IEEE helpers, floating-point comparison, InterestRate compounding,\n"
           "and the cash-flow occurrence predicates with QuantLib's Settings made\n"
           "explicit arguments.\n\n"
           "Derived from QuantLib (BSD-3-Clause); see NOTICE.md.",
    "Dates": "Date algebra, calendars and day counters on integer serial dates.\n\n"
             "Dates are QuantLib serial numbers (1 Jan 1901 = 367, 31 Dec 2199 =\n"
             "109574, 0 = the null date).\n\n"
             "Derived from QuantLib (BSD-3-Clause); see NOTICE.md.",
    "Bond": "Schedule and leg of one bond, ``Bond[b]`` for row ``b`` of bonds.csv.\n\n"
            "Transcribes Schedule, FixedRateLeg, FixedRateBond and ZeroCouponBond\n"
            "construction. Generated once per bond.\n\n"
            "Derived from QuantLib (BSD-3-Clause); see NOTICE.md.",
    "Legs": "The portfolio leg in flat (CSR) arrays, and the cash-flow table.\n\n"
            "Derived from QuantLib (BSD-3-Clause); see NOTICE.md.",
    "Proj": "Cash flows bucketed into projection periods.\n\n"
            "A flow falls in the period in which it leaves the NPV set, using the\n"
            "same occurrence rule as the valuation.\n\n"
            "Derived from QuantLib (BSD-3-Clause); see NOTICE.md.",
    "Valuation": "Valuation of every bond at valuation date ``t`` under scenario ``scen_id``.\n\n"
                 "Derived from QuantLib (BSD-3-Clause); see NOTICE.md.",
}


def build():
    m = mx.new_model("BondPortfolio")
    m.doc = MODEL_DOC
    m.allow_none = False
    m.math = math
    m.np = numpy
    m.pd = pandas
    m.datetime = datetime
    for name, value in CONSTANTS.items():
        setattr(m, name, value)

    data = m.new_space("Data")
    lib = m.new_space("Lib")
    dates = m.new_space("Dates")
    bond = m.new_space("Bond", formula=lambda b: None)
    legs = m.new_space("Legs")
    proj = m.new_space("Proj")
    val = m.new_space("Valuation", formula=lambda scen_id, t: None)

    for name, space in [("Data", data), ("Lib", lib), ("Dates", dates), ("Bond", bond),
                        ("Legs", legs), ("Proj", proj), ("Valuation", val)]:
        space.doc = SPACE_DOCS[name]

    for name, value in DATA_REFS.items():
        setattr(data, name, value)
    data.dates = dates

    lib.dates = dates
    dates.lib = lib

    bond.b = 0
    bond.data = data
    bond.lib = lib
    bond.dates = dates

    legs.data = data
    legs.lib = lib
    legs.dates = dates
    legs.bond = bond

    proj.data = data
    proj.lib = lib
    proj.dates = dates
    proj.legs = legs

    val.scen_id = 1
    val.t = 0
    val.data = data
    val.lib = lib
    val.dates = dates
    val.legs = legs
    val.proj = proj
    return m


def main(argv):
    if MODEL_DIR.exists() and "--force" not in argv:
        raise SystemExit(f"{MODEL_DIR} exists; pass --force to overwrite")
    m = build()
    mx.write_model(m, MODEL_DIR)
    print("wrote", MODEL_DIR)


if __name__ == "__main__":
    main(sys.argv)
