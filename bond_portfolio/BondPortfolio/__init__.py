# modelx: pseudo-python
# This file is part of a modelx model.
# It can be imported as a Python module, but functions defined herein
# are model formulas and may not be executable as standard Python.

"""Bond portfolio model transcribed from quantlib-migration's ``pureql``.

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

from modelx.serialize.jsonvalues import *

_name = "BondPortfolio"

_allow_none = False

_spaces = [
    "Data",
    "Lib",
    "Dates",
    "Bond",
    "Legs",
    "Proj",
    "Valuation"
]

# ---------------------------------------------------------------------------
# References

math = ("Module", "math")

np = ("Module", "numpy")

pd = ("Module", "pandas")

datetime = ("Module", "datetime")

BDC_FOLLOWING = 0

BDC_MODIFIED_FOLLOWING = 1

BDC_PRECEDING = 2

BDC_MODIFIED_PRECEDING = 3

BDC_UNADJUSTED = 4

BDC_HALF_MONTH_MODIFIED_FOLLOWING = 5

BDC_NEAREST = 6

TU_DAYS = 0

TU_WEEKS = 1

TU_MONTHS = 2

TU_YEARS = 3

FREQ_NO_FREQUENCY = -1

FREQ_ONCE = 0

FREQ_ANNUAL = 1

FREQ_SEMIANNUAL = 2

FREQ_EVERY_FOURTH_MONTH = 3

FREQ_QUARTERLY = 4

FREQ_BIMONTHLY = 6

FREQ_MONTHLY = 12

FREQ_EVERY_FOURTH_WEEK = 13

FREQ_BIWEEKLY = 26

FREQ_WEEKLY = 52

FREQ_DAILY = 365

FREQ_OTHER_FREQUENCY = 999

COMP_SIMPLE = 0

COMP_COMPOUNDED = 1

COMP_CONTINUOUS = 2

COMP_SIMPLE_THEN_COMPOUNDED = 3

COMP_COMPOUNDED_THEN_SIMPLE = 4

RULE_BACKWARD = 0

RULE_FORWARD = 1

RULE_ZERO = 2

DUR_SIMPLE = 0

DUR_MACAULAY = 1

DUR_MODIFIED = 2

PRICE_DIRTY = 0

PRICE_CLEAN = 1

SUNDAY = 1

MONDAY = 2

TUESDAY = 3

WEDNESDAY = 4

THURSDAY = 5

FRIDAY = 6

SATURDAY = 7

JANUARY = 1

FEBRUARY = 2

MARCH = 3

APRIL = 4

MAY = 5

JUNE = 6

JULY = 7

AUGUST = 8

SEPTEMBER = 9

OCTOBER = 10

NOVEMBER = 11

DECEMBER = 12

CAL_NULL = 0

CAL_TARGET = 1

CAL_US_SETTLEMENT = 2

CAL_US_GOVBOND = 3

DC_ACT360 = 1

DC_ACT365F = 2

DC_30360_USA = 10

DC_30360_BB = 11

DC_30360_EU = 12

BOND_FIXED = 0

BOND_ZERO = 1

CURVE_ZERO = 0

CURVE_FLAT = 1

CF_COUPON = 0

CF_AMORTIZING = 1

CF_REDEMPTION = 2

ROLE_ENGINE = 0

ROLE_SETTLE = 1

ROLE_EXPIRY = 2

SOLVE_YIELD = 0

SOLVE_ZSPREAD = 1

NT_ENGINE = 0

NT_RAISE = 1

ERR_RAISE = 0

ERR_NAN = 1

NULL_DATE = 0

MIN_SERIAL = 367

MAX_SERIAL = 109574

QL_EPSILON = 2.220446049250313e-16

CLOSE_N = 42

ZERO_RATE_DT = 0.0001

ZSPREAD_STEP = 0.01

BASIS_POINT = 0.0001

MAX_BONDS = 12000

MAX_FLOWS = 480000

MAX_KD = 40000

MAX_NODES = 64

MAX_T = 1201

CAL_MAX = 4

MAX_SETTLE_DAYS = 7

MAX_SCHED = 1200

MAX_SCEN = 1000