"""Phase 4 analytics at future t (docs/model-contract.md 4.8): the model against pureql, bit for bit.

An item at any t is pureql with the evaluation date moved to ``vdate()`` and
the settlement date ``s_t = bond.settlementDate(vdate)`` (plan, "Future-t
semantics" 5-6): yields and risk are taken from ``npvDate = s_t`` with the
bond's yield conventions, the z-spread over the (scen, t) curve where a price
exists. The oracle is ``helpers/pureql_val.py::pq_analytics`` (see
``test_analytics_t0.py``).

1. Every bond of the demo and coverage sets at t = 1, 2, 3 of both
   scenarios, under the six settings variants of the t = 0 tests.
2. ALL five yield compoundings on every coverage bond: the coverage set with
   each bond repeated once per compounding (Simple, Compounded, Continuous,
   SimpleThenCompounded, CompoundedThenSimple), at every (scen_id, t), with
   NewtonSafe and with Brent.
3. The Phase 3 edge grid (``tests/future/test_future_edges.py``): flows on v
   and in (v, s], before issue, after maturity, holidays, the T override, a
   curve too short for the bonds (its range error must reach ytm through the
   engine clean price and stay a raise under ERR_NAN), under the default
   flags at every point and under a set of (R, T, F) on the event dates
   (all 18 under ``slow``).
4. The frozen analytics goldens (``tests/data/analytics_demo.json``,
   ``analytics_coverage.json``): the model against them per settings
   variant, and live pureql against them (drift of the oracle).
5. A generated portfolio (500 bonds, 2 scenarios x 3 dates two years apart,
   fixed seed): ytm == pureql, and the risk measures == pureql AT THE MODEL'S
   OWN ytm (so that a yield mismatch, if any, does not hide the risk
   transcription); t = 0 by default, every t under ``slow``.
"""

import importlib.util
import itertools
import json

import pytest

from helpers import pureql_val as pv
from helpers.model import MODEL_DIR

ROOT = MODEL_DIR.parents[1]
DEMO = ROOT / "bond_portfolio"
COVERAGE = ROOT / "tools" / "cy" / "sample_inputs"
DATA = ROOT / "tests" / "data"
SETS = {"demo": DEMO, "coverage": COVERAGE}

Y_GRID = (-0.005, 0.0, 0.0325, 0.11)
VARIANTS = {
    "default": {},
    "brent": {"yield_solver": pv.YIELD_BRENT},
    "roundtrip": {"zspread_price_source": 1},
    "nt_raise": {"nontradable_policy": pv.NT_RAISE},
    "err_nan": {"solver_error_policy": pv.ERR_NAN},
    "raise_nan": {"nontradable_policy": pv.NT_RAISE, "solver_error_policy": pv.ERR_NAN},
}

#: The generated portfolio of item 5.
GEN_BONDS, GEN_SCEN, GEN_TIMES, GEN_SEED, GEN_BASE, GEN_STEP = 500, 2, 3, 20261014, "2015-09-16", "2Y"


def every_bond(model, scen_id, t, ys=Y_GRID, risk_at_model_ytm=False, bonds=None):
    q = pv.quote_inputs(model)
    c = pv.curve_inputs(model, scen_id, t)
    item = model.Valuation[scen_id, t]
    bad = []
    for b in range(model.Data.n_bonds()) if bonds is None else bonds:
        ry = None
        if risk_at_model_ytm:
            cell = pv.analytics_cell(item, "ytm")
            ry = None if cell is None else pv.run_model(cell, b)
        bad += pv.compare_analytics(model, scen_id, t, b, ys, None, q, c, risk_yield=ry)[0]
    return bad


# --------------------------------------------------------------------------- 1. demo and coverage at future t
@pytest.mark.parametrize("variant", list(VARIANTS))
@pytest.mark.parametrize("t", [1, 2, 3])
@pytest.mark.parametrize("scen_id", [1, 2])
@pytest.mark.parametrize("name", list(SETS))
def test_every_bond_future_t(set_model, name, scen_id, t, variant):
    m = set_model(f"{name}_{variant}", SETS[name], **VARIANTS[variant])
    pv.report_analytics(every_bond(m, scen_id, t), f"{name} ({scen_id}, {t}) {variant}")


# --------------------------------------------------------------------------- 2. every yield compounding
@pytest.fixture(scope="module")
def compounding_inputs(tmp_path_factory):
    return pv.write_compounding_variants(tmp_path_factory.mktemp("analytics_compoundings"), COVERAGE)


def test_compounding_variants_cover_every_compounding(set_model, compounding_inputs):
    m = set_model("compoundings_newton", compounding_inputs)
    assert {int(x) for x in m.Data.b_ycomp_arr().tolist()} == set(pv.COMPOUNDINGS)
    assert m.Data.n_bonds() == 5 * 17


@pytest.mark.parametrize("solver", [pv.YIELD_NEWTON, pv.YIELD_BRENT], ids=["newton", "brent"])
@pytest.mark.parametrize("scen_id,t", list(itertools.product((1, 2), range(4))))
def test_every_compounding(set_model, compounding_inputs, scen_id, t, solver):
    """Every coverage bond under each of the five yield compoundings, at every (scen_id, t)."""
    name = "compoundings_newton" if solver == pv.YIELD_NEWTON else "compoundings_brent"
    m = set_model(name, compounding_inputs, yield_solver=solver)
    pv.report_analytics(every_bond(m, scen_id, t, ys=(-0.005, 0.0325)), f"compoundings ({scen_id}, {t}) {name}")


# --------------------------------------------------------------------------- 3. the Phase 3 edge grid
def _load_edges():
    spec = importlib.util.spec_from_file_location("analytics_future_edges",
                                                  ROOT / "tests" / "future" / "test_future_edges.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


EDGES = _load_edges()
EDGE_FLAGS = [(0, -1, -1), (1, -1, -1), (0, 1, -1), (0, 0, -1), (1, 0, 1), (0, 1, 1), (1, 1, 0)]


@pytest.fixture(scope="module")
def edge_inputs(tmp_path_factory):
    return EDGES.write_edge_inputs(tmp_path_factory.mktemp("analytics_edges"))


@pytest.mark.parametrize("scen_id", sorted(EDGES.SCENARIOS))
def test_edge_grid(set_model, edge_inputs, scen_id):
    """Every bond at every edge date of one scenario, default flags (SCEN_SHORT: range errors reach ytm)."""
    m = set_model("edges", edge_inputs)
    bad = []
    for t in range(len(EDGES.VDATES)):
        bad += every_bond(m, scen_id, t, ys=(0.03,))
    pv.report_analytics(bad, f"edge grid scenario {scen_id}")


def test_edge_grid_reaches_a_curve_error_and_the_t_override(new_model, edge_inputs):
    """Precondition (pureql only): a curve range error reaches ytm, and T = 1 changes an analytics output."""
    m0 = new_model("EdgesPre0", edge_inputs, solver_error_policy=pv.ERR_NAN)
    m1 = new_model("EdgesPre1", edge_inputs, include_todays_cashflows=1)
    errors, moved = 0, 0
    for t in range(len(EDGES.VDATES)):
        for b in range(m0.Data.n_bonds()):
            e = pv.pq_analytics(m0, EDGES.SCEN_SHORT, t, b, (), None, steps=False)["bond"]["ytm"]
            errors += e[0] == "err" and "past max curve time" in e[2]
        b = list(m1.Data.bond_keys()).index("T0_CPN_ON_V")
        a = pv.pq_analytics(m0, EDGES.SCEN_FLAT, t, b, (0.03,), dict(pv.ANALYTICS_DEFAULTS), steps=True)
        x = pv.pq_analytics(m1, EDGES.SCEN_FLAT, t, b, (0.03,), dict(pv.ANALYTICS_DEFAULTS), steps=True)
        moved += any(not pv.same_outcome(a["y"][k], x["y"][k]) for k in a["y"])
    assert errors > 0, "no curve range error reaches ytm on SCEN_SHORT"
    assert moved > 0, "the T override never changes an analytics output of T0_CPN_ON_V"


@pytest.mark.parametrize("R,T,F", EDGE_FLAGS, ids=[f"R{r}-T{t}-F{f}" for r, t, f in EDGE_FLAGS])
def test_flags_on_event_dates(new_model, edge_inputs, R, T, F):
    """Analytics under (R, T, F) on the event dates (flat curve): T reaches the SETTLE role when s == v."""
    m = new_model("EdgeFlags", edge_inputs, include_reference_date_events=R, include_todays_cashflows=T,
                  engine_include_settlement_flows=F)
    bad = []
    for v in EDGES.EVENT_DATES:
        bad += every_bond(m, EDGES.SCEN_FLAT, EDGES.T_OF[v], ys=(0.03,))
    pv.report_analytics(bad, f"flags R={R} T={T} F={F}")


@pytest.mark.slow
@pytest.mark.parametrize("R,T,F", EDGES.FLAGS, ids=[f"R{r}-T{t}-F{f}" for r, t, f in EDGES.FLAGS])
def test_flags_full(new_model, edge_inputs, R, T, F):
    m = new_model("EdgeFlagsFull", edge_inputs, include_reference_date_events=R, include_todays_cashflows=T,
                  engine_include_settlement_flows=F)
    bad = []
    for s in sorted(EDGES.SCENARIOS):
        for t in range(len(EDGES.VDATES)):
            bad += every_bond(m, s, t, ys=(0.03,))
    pv.report_analytics(bad, f"flags R={R} T={T} F={F} (full)")


# --------------------------------------------------------------------------- 4. the frozen goldens
def golden(name):
    return json.loads((DATA / f"analytics_{name}.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", list(SETS))
def test_golden_inputs_unchanged(name):
    """The goldens were frozen from these exact input files (else regenerate with write_analytics_golden)."""
    assert golden(name)["provenance"]["input_sha256"] == pv.input_hashes(SETS[name])


@pytest.mark.parametrize("variant", list(pv.GOLDEN_VARIANTS))
@pytest.mark.parametrize("name", list(SETS))
def test_pureql_still_reproduces_golden(set_model, name, variant):
    """Live pureql == the frozen values (no model Cells): the oracle has not drifted."""
    m = set_model(f"{name}_default", SETS[name])
    doc = golden(name)
    st = dict(pv.ANALYTICS_DEFAULTS, **doc["provenance"]["variants"][variant])
    bad = pv.live_golden_mismatches(m, doc["values"][variant], st, tuple(doc["provenance"]["yield_grid"]),
                                    f"{name} {variant}")
    pv.report_mismatches(bad, f"live pureql vs analytics_{name}.json [{variant}]")


@pytest.mark.parametrize("variant", list(pv.GOLDEN_VARIANTS))
@pytest.mark.parametrize("name", list(SETS))
def test_model_matches_golden(set_model, name, variant):
    """The model (its Data set to the variant) == the frozen pureql values, bit for bit, at every point."""
    doc = golden(name)
    over = doc["provenance"]["variants"][variant]
    m = set_model(f"{name}_golden_{variant}", SETS[name], **over)
    pv.report_analytics(pv.analytics_golden_mismatches(m, doc["values"][variant], f"{name} {variant}"),
                        f"model vs analytics_{name}.json [{variant}]")


# --------------------------------------------------------------------------- 5. a generated portfolio
@pytest.fixture(scope="module")
def gen_inputs(tmp_path_factory):
    gen = pv.generator()
    out = tmp_path_factory.mktemp("analytics_generated")
    gen.write_tables(out, gen.generate(GEN_BONDS, GEN_SCEN, GEN_TIMES, GEN_SEED, GEN_BASE, GEN_STEP))
    return out


@pytest.mark.parametrize("scen_id", [1, pytest.param(2, marks=pytest.mark.slow)])
def test_generated_portfolio_t0(set_model, gen_inputs, scen_id):
    """500 generated bonds at t = 0: ytm == pureql; the risk measures at the model's own ytm == pureql."""
    m = set_model("generated", gen_inputs)
    pv.report_analytics(every_bond(m, scen_id, 0, ys=(0.04,), risk_at_model_ytm=True),
                        f"generated ({scen_id}, 0)")


@pytest.mark.slow
@pytest.mark.parametrize("scen_id,t", [(s, t) for s in (1, 2) for t in (1, 2)])
def test_generated_portfolio_future_t(set_model, gen_inputs, scen_id, t):
    m = set_model("generated", gen_inputs)
    pv.report_analytics(every_bond(m, scen_id, t, ys=(0.04,), risk_at_model_ytm=True),
                        f"generated ({scen_id}, {t})")


@pytest.mark.slow
@pytest.mark.parametrize("scen_id,t", [(s, t) for s in (1, 2) for t in range(GEN_TIMES)])
def test_generated_portfolio_brent(set_model, gen_inputs, scen_id, t):
    m = set_model("generated_brent", gen_inputs, yield_solver=pv.YIELD_BRENT)
    pv.report_analytics(every_bond(m, scen_id, t, ys=(), risk_at_model_ytm=True), f"generated Brent ({scen_id}, {t})")


def test_generated_portfolio_is_varied(set_model, gen_inputs):
    """Precondition (pureql only): the portfolio has every compounding, untradable bonds and solved yields."""
    m = set_model("generated", gen_inputs)
    comps = {int(x) for x in m.Data.b_ycomp_arr().tolist()}
    assert comps == set(pv.COMPOUNDINGS)
    q = pv.quote_inputs(m)
    c = pv.curve_inputs(m, 1, 0)
    kinds = set()
    for b in range(0, m.Data.n_bonds(), 5):
        e = pv.pq_analytics(m, 1, 0, b, (), None, q, c, steps=False)
        kinds.add((e["facts"]["tradable"], e["bond"]["ytm"][0]))
    assert {(True, "ok"), (False, "ok")} <= kinds, kinds
