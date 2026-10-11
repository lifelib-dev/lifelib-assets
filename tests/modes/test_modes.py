"""L7: the three execution modes give bit-identical results.

* ``export == modelx`` runs by default: the model is exported into ``tmp_path``.
* ``compiled == export`` needs the build of ``tools/build_cy.py`` and is marked
  ``compiled`` (run with ``pytest -m compiled``).

The probes call every Cells of the model (read from its source) over
representative arguments, on each input set, and compare the bit patterns of
the results (NaN-aware; arrays and DataFrames element by element). An exception
is a result too: both modes must raise, with the same message.

Each input set is probed under the default Data settings; ``coverage_analytics``
probes the coverage inputs again with the Phase 4 alternatives set
(``output_level`` 3, ``ERR_NAN``, the Brent yield solver, the z-spread from
the engine price), so that ``result_frame`` and both solver paths are compared
across modes too.
"""

import ast
import math

import modelx as mx
import pytest

from helpers import modes
from helpers.model import MODEL_DIR, ROOT

INPUT_SETS = {
    "demo": ROOT / "bond_portfolio",
    "coverage": ROOT / "tools" / "cy" / "sample_inputs",
    "coverage_analytics": ROOT / "tools" / "cy" / "sample_inputs",
}
#: Data References set (on a fresh instance) before probing an input set.
INPUT_REFS = {
    "coverage_analytics": {"output_level": 3, "solver_error_policy": 1, "yield_solver": 1,
                           "zspread_price_source": 1},
}
SPACES = ["Lib", "Dates", "Data", "Bond", "Legs", "Proj", "Valuation"]

SERIALS = sorted(set(list(range(367, 109575, 1543)) + list(range(42000, 42400)) + [109574]))
CALS = range(4)
CONVS = range(7)
DCS = (1, 2, 10, 11, 12)
RATES = (-0.5, -0.01, 0.0, 0.03, 0.25)
TIMES = (0.0, 0.25, 1.0, 7.5, 30.0)
COMPS = range(5)
FREQS = (-1, 0, 1, 2, 4, 12, 365)


def cells_of(space):
    """[(name, params, cached)] of a Space, from its serialized source."""
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


def domain(space, name, params, m):
    """Argument tuples for a Cells; None means 'not probed here'."""
    if params == ():
        return [()]
    if params == ("d",):
        return [(d,) for d in SERIALS]
    if params == ("yr",):
        return [(y,) for y in range(1901, 2200, 7)]
    if params == ("m", "leap"):
        top = 13 if name == "month_offset" else 12
        return [(mm, lp) for mm in range(1, top + 1) for lp in (0, 1)]
    if params == ("w",):
        return [(w,) for w in range(1, 8)]
    if params == ("cal", "d"):
        return [(c, d) for c in CALS for d in SERIALS[::3]]
    if params == ("cal", "d", "conv"):
        return [(c, d, v) for c in CALS for d in SERIALS[::9] for v in CONVS]
    if params == ("cal", "d", "n", "unit", "conv", "eom"):
        return [(c, d, n, u, 0, e) for c in CALS for d in SERIALS[::23]
                for n, u in ((0, 0), (3, 0), (-2, 0), (1, 1), (6, 2), (-1, 3)) for e in (0, 1)]
    if params == ("d", "n", "unit"):
        return [(d, n, u) for d in SERIALS[::11] for n, u in ((5, 0), (-2, 1), (1, 2), (-13, 2), (2, 3))]
    if params == ("dc", "d1", "d2") or params == ("dc", "d1", "d2", "r1", "r2"):
        pairs = [(SERIALS[i], SERIALS[i + 5]) for i in range(0, len(SERIALS) - 5, 13)]
        extra = (0, 0) if len(params) == 5 else ()
        return [(dc, a, b) + extra for dc in DCS for a, b in pairs]
    if params == ("n", "unit"):
        return [(n, u) for n in (0, 1, 2, 3, 6, 12, 24) for u in range(4)]
    if params == ("x",):
        return [(x,) for x in (-800.0, -1.0, 0.0, 0.5, 1.5, 2.5, 800.0, math.inf)]
    if params == ("x", "y"):
        return [(x, y) for x in (-2.0, -0.0, 0.0, 1.5, 1e300) for y in (-3.0, -0.5, 0.0, 2.0, 3.0)]
    if params == ("y",):
        return [(y,) for y in (-3.0, -2.0, 0.5, 3.0)]
    if params == ("a", "c"):
        return [(a, c) for a in (-7, -1, 0, 5, 9) for c in (-2, 3)]
    if params == ("comp", "freq"):
        return [(c, f) for c in COMPS for f in FREQS]
    if params == ("r", "comp", "freq", "tt"):
        return [(r, c, f, t) for r in RATES for c in COMPS for f in (1, 2, 12) for t in TIMES]
    if params == ("compound", "comp", "freq", "tt"):
        return [(k, c, f, t) for k in (0.5, 1.0, 1.04) for c in COMPS for f in (1, 2, 12) for t in TIMES[1:]]
    if params == ("r", "comp", "freq", "tt", "comp2", "freq2"):
        return [(r, c, f, t, c2, 2) for r in RATES[2:] for c in COMPS for f in (1, 12)
                for t in TIMES[1:] for c2 in COMPS]
    if params == ("r", "comp", "freq", "dc", "d1", "d2", "r1", "r2"):
        return [(0.03, c, 2, dc, 42000, 42000 + k, 0, 0) for c in COMPS for dc in DCS for k in (0, 31, 400)]
    if params == ("d", "ref", "include_flag", "eval_date", "todays", "ref_events"):
        e = 42000
        return [(d, ref, i, e, t, r) for d in (e - 1, e, e + 1) for ref in (0, e)
                for i in (-1, 0, 1) for t in (-1, 0, 1) for r in (0, 1)]
    if params == ("ex_date", "ref"):
        return [(x, r) for x in (0, 42000) for r in (41999, 42000, 42001)]
    if params == ("per",):
        return [(p,) for p in range(m.Data.n_times() + 1)]
    return None


VAL_ZS = (-0.0125, 0.0, 0.004, 0.03)
VAL_YS = (-0.01, 0.0, 0.03, 0.1)
#: The Phase 4 Cells that solve (directly or through ``risk_yield``): probed on
#: the first ``ANALYTICS_BONDS`` bonds of an item only, so that the large
#: portfolios of test_modes_future.py stay affordable in modelx mode.
SOLVING_CELLS = {"ytm", "risk_yield", "duration_simple", "duration_modified", "duration_macaulay",
                 "convexity", "bpv", "yvbp", "zspread"}
ANALYTICS_BONDS = 24


def val_domain(name, params, v, m):
    """Argument tuples for a Cells of the Valuation item ``v``; None means 'not probed here'.

    The kd, p and x Cells are not called with arbitrary arguments (a C array
    index outside the build sizes is not a comparable outcome); the per-bond
    Cells reach them on the offsets the portfolio uses. The nd Cells are
    probed on ZeroCurve items only, over the curve's own nodes.
    """
    nb = m.Data.n_bonds()
    na = min(nb, ANALYTICS_BONDS)
    if params == ():
        return [()]
    if params == ("b",):
        return [(b,) for b in range(na if name in SOLVING_CELLS else nb)]
    if params == ("b", "role"):
        return [(b, r) for b in range(nb) for r in (0, 1, 2)]
    if params == ("b", "z"):
        return [(b, z) for b in range(nb) for z in VAL_ZS]
    if params == ("b", "y"):
        return [(b, y) for b in range(na) for y in VAL_YS]
    if params == ("b", "kind"):
        return [(b, k) for b in range(na) for k in (0, 1)]
    if params == ("cal", "nsd"):
        return [(c, n) for c in CALS for n in range(4)]
    if params == ("nd",):
        if v.curve_type() != 0:  # CURVE_ZERO
            return None
        top = v.n_nodes() - 1 if name == "node_slope" else v.n_nodes()
        return [(nd,) for nd in range(top)]
    return None


def call(f, args):
    try:
        return ("ok", modes.bits(f(*args)))
    except Exception as e:  # an exception is a result too
        err = mx.get_error() if type(e).__name__ == "FormulaError" else e
        err = err or e
        return ("raise", type(err).__name__, str(err).splitlines()[0][:200])


def probe(m, space_names=SPACES):
    """{(space, cells, args): result} over the model ``m`` (any mode)."""
    out = {}
    for space in space_names:
        cells = cells_of(space)
        if space == "Bond":
            items = [(b, m.Bond[b]) for b in range(m.Data.n_bonds())]
        elif space == "Valuation":
            items = [((s, t), m.Valuation[s, t])
                     for s in range(1, m.Data.n_scen() + 1) for t in range(m.Data.n_times())]
        else:
            items = [(None, getattr(m, space))]
        for key, obj in items:
            for name, params, _cached in cells:
                if space == "Valuation":
                    args_list = val_domain(name, params, obj, m)
                else:
                    args_list = domain(space, name, params, m)
                if args_list is None:
                    continue
                f = getattr(obj, name)
                for args in args_list:
                    out[(space, key, name, args)] = call(f, args)
    return out


def compare(a, b):
    assert a.keys() == b.keys()
    bad = [k for k in a if a[k] != b[k]]
    assert not bad, f"{len(bad)} mismatches, e.g. {bad[:5]}: {a[bad[0]]!s:.300} vs {b[bad[0]]!s:.300}"


def instance(pkg, label):
    """A fresh exported or compiled instance on the input set ``label``, with its Data References set."""
    m = modes.new_instance(pkg, INPUT_SETS[label])
    for k, v in INPUT_REFS.get(label, {}).items():
        setattr(m.Data, k, v)
    return m


@pytest.fixture(scope="module")
def modelx_results():
    out = {}
    for label, inputs in INPUT_SETS.items():
        m = mx.read_model(MODEL_DIR, name=f"BondPortfolio_modes_{label}")
        try:
            m.Data.input_dir = str(inputs)
            for k, v in INPUT_REFS.get(label, {}).items():
                setattr(m.Data, k, v)
            mx.use_formula_error(True)
            out[label] = probe(m)
        finally:
            m.close()
    return out


@pytest.fixture(scope="module")
def export_results(tmp_path_factory):
    pkg = modes.export_package(tmp_path_factory.mktemp("export"))
    return {label: probe(instance(pkg, label)) for label in INPUT_SETS}


@pytest.mark.parametrize("label", list(INPUT_SETS))
def test_export_equals_modelx(label, modelx_results, export_results):
    compare(modelx_results[label], export_results[label])


@pytest.mark.compiled
@pytest.mark.parametrize("label", list(INPUT_SETS))
def test_compiled_equals_export(label, export_results):
    pkg = modes.compiled_package()
    if pkg is None:
        pytest.skip("no compiled build; run tools/build_cy.py")
    compare(export_results[label], probe(instance(pkg, label)))
