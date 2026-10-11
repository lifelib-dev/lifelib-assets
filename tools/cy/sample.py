"""mx2cy sample script: exercises the exported model so that mx2cy can trace types.

Run by ``mx2cy`` (see tools/build_cy.py) against ``build/BondPortfolio_nomx``,
with ``build/`` on ``sys.path``. Rules (docs/model-contract.md; plan "modelx-cython rules"):

* call every CACHED Cells on representative arguments: mx2cy types only what it
  sees, and an untraced Cells stays ``object``;
* UNCACHED Cells are traced too (modelx-cython branch
  ``bondportfolio/mx2cy-improvements``), from every call the run makes to
  them, directly or nested in other Cells: the Lib / Dates / Valuation helpers
  of the hot Cells are reached through the calls below. Those that the hot
  Cells reach only on rare branches are called directly in
  :func:`exercise_rare_helpers`. The rest are listed, with the reason, in
  ``tools/build_cy.py`` ``UNCACHED_OBJECT_CELLS``; the pxd audit there fails
  the build if any other Cells comes out ``object``;
* pass floats as Python floats, ints as ints;
* raise nothing (a Cells that raises during the trace is typed ``object``).
  The Phase 4 analytics are traced with ``Data.solver_error_policy = ERR_NAN``
  and ``Data.output_level = 3``: a failed solve or a Macaulay duration of a
  yield that is not Compounded gives NaN instead of raising, and
  ``result_frame`` builds every analytics column. The (b, y) Cells are called
  directly only on arguments where they cannot raise
  (``macaulay_duration_y`` on Compounded yields only);
* do NOT delete Bond or Valuation items: Space-parameter types are learned
  from the items alive when the script ends.

The Cells and their parameters are read from the model source, so new Cells
are exercised without editing this script, as long as their parameter tuple
has a domain in :data:`DOMAINS`.
"""

import ast
import math
import pathlib

from BondPortfolio_nomx import BondPortfolio as m

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
MODEL_DIR = ROOT / "bond_portfolio" / "BondPortfolio"
SAMPLE_INPUTS = HERE / "sample_inputs"

m.Data.input_dir = str(SAMPLE_INPUTS)
m.Data.solver_error_policy = 1  # ERR_NAN: nothing raises during the trace
m.Data.output_level = 3  # result_frame() builds every analytics column


def cells_of(space):
    """[(name, params, cached)] of a Space, read from its serialized source."""
    tree = ast.parse((MODEL_DIR / space / "__init__.py").read_text(encoding="utf-8"))
    out, prev = [], None
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            out.append([node.name, tuple(a.arg for a in node.args.args), True])
        elif (isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)
              and node.targets[0].id == "_is_cached" and isinstance(prev, ast.FunctionDef)):
            out[-1][2] = False
        prev = node
    return [tuple(c) for c in out]


# Representative serials: every day of a few years (all weekdays, month ends,
# holidays, Feb 29) plus a sparse sweep of the whole range.
YEARS = (1901, 2004, 2015, 2016, 2024, 2100, 2199)
SERIALS = sorted(set(
    [d for y in YEARS for d in range(m.Dates.year_offset(y) + 1, m.Dates.year_offset(y + 1) + 1)
     if y < 2200 and d <= 109574]
    + list(range(367, 109575, 997))))

N_T = m.Data.n_times()


def domain(space, name, params):
    """Argument tuples for one Cells, or None to skip it."""
    if params == ():
        return [()]
    if params == ("d",):
        return [(d,) for d in SERIALS]
    if params == ("yr",):
        # 1901..2199: the Easter table starts in 1901 (1900 raises, as in pureql).
        return [(y,) for y in range(1901, 2200)]
    if params == ("m", "leap"):
        top = 13 if name == "month_offset" else 12
        return [(mm, lp) for mm in range(1, top + 1) for lp in (0, 1)]
    if params == ("w",):
        return [(w,) for w in range(1, 8)]
    if params == ("cal", "d"):
        return [(c, d) for c in range(4) for d in SERIALS]
    if params == ("per",):
        return [(p,) for p in range(N_T + 1)]
    return None


def exercise(space_obj, space, skip=()):
    for name, params, cached in cells_of(space):
        if not cached or name in skip:
            continue
        args_list = domain(space, name, params)
        if args_list is None:
            continue
        f = getattr(space_obj, name)
        for args in args_list:
            f(*args)


N_BONDS = m.Data.n_bonds()
ZS = (-0.0125, 0.0, 0.004, 0.03)  # z-spreads, Python floats
YS = (-0.01, 0.0, 0.03, 0.1)  # yields, Python floats
#: Per-bond analytics called first, so that the (b, y), (b, kind) and p Cells
#: are traced through the calls the model itself makes.
ANALYTICS = ("ytm", "zspread", "risk_yield", "duration_simple", "duration_modified", "duration_macaulay",
             "convexity", "bpv", "yvbp", "dirty_at_yield_in", "clean_at_yield_in")


def val_domain(v, name, params):
    """Argument tuples for one Valuation Cells of item ``v``, or None to skip it.

    The kd / p / x Cells are not called directly: the per-bond outputs reach
    them (and the nd and (cal, nsd) Cells) on the offsets the portfolio
    actually uses, so the tracer sees them without arbitrary arguments.
    """
    if params == ():
        return [()]
    if params == ("b",):
        return [(b,) for b in range(N_BONDS)]
    if params == ("b", "role"):
        roles = (0, 1, 2) if name in ("first_live", "ref_date") else (0, 1)
        return [(b, r) for b in range(N_BONDS) for r in roles]
    if params == ("b", "z"):
        return [(b, z) for b in range(N_BONDS) for z in ZS]
    if params == ("b", "y"):
        bonds = range(N_BONDS)
        if name == "macaulay_duration_y":  # raises "compounded rate required" otherwise
            bonds = [b for b in bonds if v.ycomp(b) == 1]  # COMP_COMPOUNDED
        return [(b, y) for b in bonds for y in YS]
    if params == ("b", "kind"):
        return [(b, k) for b in range(N_BONDS) for k in (0, 1)]  # SOLVE_YIELD, SOLVE_ZSPREAD
    if params == ("cal", "nsd"):
        return [(c, n) for c in range(4) for n in range(4)]
    if params == ("nd",):
        if v.curve_type() != 0:  # CURVE_ZERO
            return None
        top = v.n_nodes() - 1 if name == "node_slope" else v.n_nodes()
        return [(nd,) for nd in range(top)]
    return None


def exercise_valuation(v):
    # the per-bond outputs first: they trace the curve Cells through nested calls
    for b in range(N_BONDS):
        for name in ("npv", "settlement_value", "accrued_amount", "dirty_price", "clean_price",
                     "market_value"):
            getattr(v, name)(b)
        for z in ZS:
            v.clean_from_z(b, z)
        for name in ANALYTICS:
            getattr(v, name)(b)
    for name, params, cached in cells_of("Valuation"):
        if not cached:
            continue
        args_list = val_domain(v, name, params)
        if args_list is None:
            continue
        f = getattr(v, name)
        for args in args_list:
            f(*args)


def exercise_rare_helpers(lib):
    """Call the uncached Lib helpers that the hot Cells reach only on rare branches.

    The nested calls of the run below do not reach them, so mx2cy would leave
    them ``object``; each is called here on Python floats, the types the
    model passes:

    * ``cxx_pow`` calls ``is_odd_integer`` only where ``math.pow`` raises
      (overflow, a zero base with a negative exponent): ``cxx_pow`` is called
      on those arguments (and on a negative base with a fractional exponent),
      and ``is_odd_integer`` directly, including on ``inf`` and ``nan``;
    * ``range_ok`` calls ``close_enough`` only for a time past the curve's last
      node; it is called directly, on equal, close and distant pairs.

    Neither raises on these arguments.
    """
    for x, y in ((1e300, 3.0), (-1e300, 3.0), (1e300, 2.0), (-0.0, -3.0), (0.0, -2.0), (-2.0, 0.5)):
        lib.cxx_pow(x, y)
    for y in (-3.0, 0.5, 2.0, math.inf, math.nan):
        lib.is_odd_integer(y)
    for x, y in ((30.0, 30.0), (30.0, 30.0 + 1e-14), (0.0, 1e-300), (12.5, 30.0), (-1.0, 1.0)):
        lib.close_enough(x, y)


exercise(m.Lib, "Lib")
exercise_rare_helpers(m.Lib)
exercise(m.Dates, "Dates")
exercise(m.Data, "Data")
for b in range(m.Data.n_bonds()):
    exercise(m.Bond[b], "Bond")
exercise(m.Legs, "Legs")
exercise(m.Proj, "Proj")
for s in range(1, m.Data.n_scen() + 1):
    for t in range(N_T):
        exercise_valuation(m.Valuation[s, t])

# Items stay alive (see the module docstring).
assert len(m.Bond._mx_itemspaces) == m.Data.n_bonds()
assert len(m.Valuation._mx_itemspaces) == m.Data.n_scen() * N_T
