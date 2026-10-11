"""L8 memory: streaming ``Valuation[scen_id, t]`` items keeps one item alive at a time.

Exported and compiled Spaces are self-cyclic (``_space``, ``_mx_roots``;
docs/mx2cy-issues.md #4), so ``del model.Valuation[scen_id, t]`` alone frees
nothing: the item waits for the cyclic collector. ``bond_portfolio/run.py``
therefore calls ``gc.collect()`` after each ``del``. These tests stream at
least 50 items the way the driver does (Legs built, Bond items deleted, one
item created, harvested and deleted at a time) and count the live instances
of the package's ``_c_Valuation`` class with a ``gc.get_objects()`` scan:

* with ``gc.collect()`` after each ``del``, the count is base + 1 while an
  item is alive and back to base after it (base: the ``Valuation`` parents of
  the model instances that exist anyway); no ``Bond`` item is re-created;
* **negative control**: with the collector disabled, the deleted items pile
  up one per item. That outcome is deterministic (only the cyclic collector
  can free a self-cyclic object) and is asserted; if it ever stops happening
  the test skips with a note that issue #4 looks fixed. With the collector
  enabled but no explicit ``gc.collect()``, how many items pile up depends on
  the generation-0 threshold, so it is only recorded (``record_property``).

Variants: the demo inputs in export mode by default (56 items: the 8 demo
items cycled 7 times) and in compiled mode (marker ``compiled``); a generated
portfolio of 1,000 bonds x 2 scenarios x 30 dates (60 items, every one
harvested with ``result_frame()``), with the RSS recorded along the stream,
under marker ``perf``.
"""

import gc
import importlib.util

import pytest

from helpers import modes
from helpers.model import MODEL_DIR

ROOT = MODEL_DIR.parents[1]
DEMO = ROOT / "bond_portfolio"
N_STREAM = 56

_spec = importlib.util.spec_from_file_location("bp_run_mem", ROOT / "bond_portfolio" / "run.py")
runmod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(runmod)

_gspec = importlib.util.spec_from_file_location("generate_inputs_mem", DEMO / "generate_inputs.py")
gen = importlib.util.module_from_spec(_gspec)
_gspec.loader.exec_module(gen)


def live(cls):
    """The number of live (GC-tracked) instances of exactly ``cls``."""
    return sum(1 for o in gc.get_objects() if type(o) is cls)


def prepared(package, input_dir):
    """A fresh instance with Legs built and the Bond items deleted, as run.py leaves it before valuing."""
    m = modes.new_instance(package, input_dir)
    m.Data.check_inputs()
    m.Legs.check_limits()
    runmod.free_bond_items(m)
    return m


def stream(m, n, collect=True, harvest="totals", rss=None):
    """Create, harvest and delete ``n`` Valuation items, cycling over the (scen_id, t) grid.

    Returns ``(alive, after)``: the live ``_c_Valuation`` count while each
    item exists and after its ``del`` (and ``gc.collect()`` if ``collect``).
    """
    cls = type(m.Valuation)
    pairs = [(s, t) for s in range(1, m.Data.n_scen() + 1) for t in range(m.Data.n_times())]
    alive, after = [], []
    for i in range(n):
        s, t = pairs[i % len(pairs)]
        v = m.Valuation[s, t]
        if harvest == "frame":
            v.result_frame()
        v.npv_total()
        alive.append(live(cls))
        v = None
        del m.Valuation[s, t]
        if collect:
            gc.collect()
        after.append(live(cls))
        if rss is not None:
            rss.append(runmod.memory_info()["current"])
    return alive, after


def check_streaming(m, n, harvest="totals", record=None):
    gc.collect()
    cls_v, cls_b = type(m.Valuation), type(m.Bond)
    base, base_bond = live(cls_v), live(cls_b)
    rss = []
    alive, after = stream(m, n, harvest=harvest, rss=rss)
    assert len(alive) == n >= 50
    assert max(alive) <= base + 1, (base, alive)
    assert alive == [base + 1] * n
    assert after == [base] * n
    assert live(cls_b) == base_bond, "a Valuation item re-created Bond items"
    if record is not None:
        record("live_valuation_base", base)
        record("rss_mb_first_last", [round(rss[0] / 2**20, 1), round(rss[-1] / 2**20, 1)] if rss[0] else None)
    return rss


def negative_control(m, record):
    """Without gc.collect(): deterministic pile-up with the collector disabled; recorded otherwise."""
    gc.collect()
    cls = type(m.Valuation)
    base = live(cls)
    gc.disable()
    try:
        _, after = stream(m, 10, collect=False)
    finally:
        gc.enable()
        gc.collect()
    record("live_after_del_gc_disabled", after)
    assert live(cls) == base
    if after[-1] == base:
        pytest.skip("deleted Valuation items were freed without the cyclic collector: "
                    "mx2cy issue #4 looks fixed, and run.py's gc.collect() may no longer be needed")
    assert after == [base + k + 1 for k in range(10)]
    # collector enabled, no explicit collect: depends on the gen-0 threshold, so recorded only
    _, after_auto = stream(m, 20, collect=False)
    gc.collect()
    record("live_after_del_gc_enabled_no_collect", after_auto)
    assert live(cls) == base


@pytest.fixture(scope="module")
def export_pkg(tmp_path_factory):
    return modes.export_package(tmp_path_factory.mktemp("mem_export"))


def compiled_pkg():
    pkg = modes.compiled_package()
    if pkg is None:
        pytest.skip("no compiled build; run tools/build_cy.py")
    return pkg


# --------------------------------------------------------------------------- quick (demo inputs)
@pytest.mark.perf
def test_streaming_frees_each_item_export(export_pkg, record_property):
    check_streaming(prepared(export_pkg, DEMO), N_STREAM, record=record_property)


@pytest.mark.perf
def test_without_gc_collect_items_pile_up_export(export_pkg, record_property):
    negative_control(prepared(export_pkg, DEMO), record_property)


@pytest.mark.compiled
def test_streaming_frees_each_item_compiled(record_property):
    check_streaming(prepared(compiled_pkg(), DEMO), N_STREAM, record=record_property)


@pytest.mark.compiled
def test_without_gc_collect_items_pile_up_compiled(record_property):
    negative_control(prepared(compiled_pkg(), DEMO), record_property)


# --------------------------------------------------------------------------- perf (generated portfolio)
@pytest.fixture(scope="module")
def generated(tmp_path_factory):
    d = tmp_path_factory.mktemp("mem_gen")
    gen.write_tables(d, gen.generate(1000, 2, 30, 20261011))
    return d


@pytest.mark.perf
def test_streaming_a_generated_portfolio_export(export_pkg, generated, record_property):
    rss = check_streaming(prepared(export_pkg, generated), 60, harvest="frame", record=record_property)
    print(f"export: RSS over 60 items {rss[0] / 2**20:.1f} -> {rss[-1] / 2**20:.1f} MB")


@pytest.mark.perf
@pytest.mark.compiled
def test_streaming_a_generated_portfolio_compiled(generated, record_property):
    rss = check_streaming(prepared(compiled_pkg(), generated), 60, harvest="frame", record=record_property)
    print(f"compiled: RSS over 60 items {rss[0] / 2**20:.1f} -> {rss[-1] / 2**20:.1f} MB")
