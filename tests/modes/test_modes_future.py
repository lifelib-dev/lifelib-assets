"""L7 on the Phase 3 corpus: ``compiled == export == modelx`` at future valuation dates.

``tests/future`` checks the model against pureql (bitwise) and QuantLib 1.41
(T2) in modelx mode only. This module closes plan Phase 3's compile gate on
the same inputs: it runs them through the exported and the compiled packages
and compares every probed result bit for bit, with the probes of
``test_modes.py`` (every Cells of Data, Bond, Legs, Proj and Valuation over
representative arguments; NaN-aware; an exception is a result too, compared
by type and message). Lib and Dates do not depend on the inputs and are
covered by ``test_modes.py``.

Cases (input set, Data settings, Valuation items probed):

* ``edges``: the edge grid of ``tests/future/test_future_edges.py``, 12 bonds
  x 25 dates x 5 scenarios (coupon dates and the next business day, flows in
  (v, s], forward starts, maturities in (v, s], expiries, holidays and
  weekends, a ZeroCurve without extrapolation whose range errors must be the
  same in every mode, five curve and spread conventions), every item, under
  the default flags and under variants of the R x T x F matrix
  (``include_reference_date_events``, ``include_todays_cashflows``,
  ``engine_include_settlement_flows``), one of them with ``NT_RAISE``;
* ``headline_2020``: the 2020 golden inputs of ``test_future_goldens.py``;
* ``fuzz_long`` / ``fuzz_dense``: the fuzz portfolios of
  ``helpers/pureql_val.py`` (600 bonds over 2000-2064; 400 bonds with dates
  4 days apart), every Valuation item of a sample of dates by default; under
  ``slow``, every item of both portfolios for ``compiled == export`` (modelx
  mode would take many minutes there, and ``export == modelx`` is shown on
  the samples).

Exported and compiled instances never invalidate their caches, so each case
gets a fresh instance with its settings set before the first calculation. Each
Valuation item is deleted and collected after it is probed, so one item is
alive at a time, as in ``run.py``. As there, ``gc.freeze()`` first moves the
objects that already exist out of the collector's view: in a full test session
a ``gc.collect()`` over everything earlier tests left behind takes seconds.
"""

import gc
import pathlib
import sys

import modelx as mx
import pytest

import test_modes as tm
from helpers import modes
from helpers import pureql_val as pv

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "future"))
import test_future_edges as edges  # noqa: E402
import test_future_goldens as goldens  # noqa: E402

SPACES = ["Data", "Bond", "Legs", "Proj"]


def flags(R, T, F, nt=0):
    return dict(include_reference_date_events=R, include_todays_cashflows=T, engine_include_settlement_flows=F,
                nontradable_policy=nt)


#: case: (input set, Data settings, t indices probed (None: all), slow, compared with modelx mode)
CASES = {
    "edges": ("edges", {}, None, False, True),
    "edges_R1_T1_F0_ntraise": ("edges", flags(1, 1, 0, 1), None, False, True),
    "edges_R0_T0_F1": ("edges", flags(0, 0, 1), None, True, True),
    "edges_R1_Tnone_Fnone": ("edges", flags(1, -1, -1), None, True, True),
    "edges_R0_T1_Fnone": ("edges", flags(0, 1, -1), None, True, True),
    "headline_2020": ("headline_2020", {}, None, False, True),
    "fuzz_long": ("long", {}, range(0, 60, 20), True, True),
    "fuzz_dense": ("dense", {}, range(0, 90, 30), True, True),
    "fuzz_long_all": ("long", {}, None, True, False),
    "fuzz_dense_all": ("dense", {}, None, True, False),
}


def case_params(with_modelx=False):
    return [pytest.param(k, marks=(pytest.mark.slow,) if v[3] else ()) for k, v in CASES.items()
            if v[4] or not with_modelx]


def write_set(name, out):
    if name == "edges":
        return edges.write_edge_inputs(out)
    if name == "headline_2020":
        return goldens.write_headline_inputs(out)
    return pv.write_fuzz_inputs(out, name)


def probe(m, times):
    """{(space, key, cells, args): result} of ``test_modes.probe`` plus the Valuation items, one alive at a time."""
    out = tm.probe(m, SPACES)
    cells = tm.cells_of("Valuation")
    ts = range(int(m.Data.n_times())) if times is None else times
    gc.freeze()
    try:
        for s in range(1, int(m.Data.n_scen()) + 1):
            for t in ts:
                v = m.Valuation[s, t]
                for name, params, _cached in cells:
                    args_list = tm.val_domain(name, params, v, m)
                    if args_list is None:
                        continue
                    f = getattr(v, name)
                    for args in args_list:
                        out[("Valuation", (s, t), name, args)] = tm.call(f, args)
                f = v = None
                del m.Valuation[s, t]
                gc.collect()
    finally:
        gc.unfreeze()
    return out


class Results:
    """The probes of each (case, mode), computed once per module on first use."""

    def __init__(self, tmp_path_factory):
        self.tmp = tmp_path_factory
        self.inputs = {}
        self.package = None
        self.cache = {}

    def input_dir(self, name):
        if name not in self.inputs:
            self.inputs[name] = write_set(name, self.tmp.mktemp(f"modes_future_{name}"))
        return self.inputs[name]

    def instance(self, mode, input_dir, refs):
        if mode == "modelx":
            mx.use_formula_error(True)
            return pv.private_model("ModesFuture", input_dir, **refs)
        if mode == "export":
            if self.package is None:
                self.package = modes.export_package(self.tmp.mktemp("modes_future_export"))
            pkg = self.package
        else:
            pkg = modes.compiled_package()
            if pkg is None:
                pytest.skip("no compiled build; run tools/build_cy.py")
        m = modes.new_instance(pkg, input_dir)
        for k, v in refs.items():
            setattr(m.Data, k, v)
        return m

    def get(self, case, mode):
        if (case, mode) not in self.cache:
            name, refs, times = CASES[case][:3]
            m = self.instance(mode, self.input_dir(name), refs)
            try:
                self.cache[(case, mode)] = probe(m, times)
            finally:
                if mode == "modelx":
                    m.close()
                del m
        return self.cache[(case, mode)]


@pytest.fixture(scope="module")
def results(tmp_path_factory):
    return Results(tmp_path_factory)


def test_cases_reach_the_valuation(results):
    """The probes are not vacuous: values and range errors from Valuation, in every scenario of the edge grid."""
    r = results.get("edges", "export")
    val = [(k, x) for k, x in r.items() if k[0] == "Valuation" and k[2] == "npv"]
    assert {k[1][0] for k, _ in val} == set(edges.SCENARIOS)
    assert sum(1 for _, x in val if x[0] == "ok") > 1000
    assert any(x[0] == "raise" and "is past max curve time" in x[2] for _, x in val)


@pytest.mark.parametrize("case", case_params(with_modelx=True))
def test_export_equals_modelx(case, results):
    tm.compare(results.get(case, "modelx"), results.get(case, "export"))


@pytest.mark.compiled
@pytest.mark.parametrize("case", case_params())
def test_compiled_equals_export(case, results):
    tm.compare(results.get(case, "export"), results.get(case, "compiled"))
