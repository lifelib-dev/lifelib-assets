"""Phase 3 driver (``bond_portfolio/run.py``) and the checks it runs before valuing anything.

* **Input checks.** ``Data.check_inputs()`` rejects every ZeroCurve that
  pureql cannot build, including two node dates that map to the same time
  under the curve's day counter (``InterpolatedCurve.setupTimes``), with
  pureql's message; ``Valuation.curve_ok()`` gives the same message.
* **Limits.** ``Legs.check_limits()`` lists every input beyond a compile-time
  size, the day offset ``kd`` against ``MAX_KD`` included; the bound it uses
  covers every day offset the Valuation items actually discount at.
* **The driver end to end** on the demo inputs: modelx, export (a fresh export
  of the current model, in a build directory of the test's own) and compiled
  (``tools/build_cy.py``'s build, marker ``compiled``) write byte-identical
  CSV files, whose values are the model's own ``result_frame()`` and
  aggregates bit for bit; ``--scen`` / ``--times`` subsets; and the refusals
  (invalid inputs, inputs beyond ``sizes.json``, the curve pre-flight, bad
  arguments), each before any valuation output is written.
"""

import csv
import datetime
import importlib.util
import json
import os
import shutil
import struct
import subprocess
import sys

import modelx as mx
import pandas as pd
import pytest

from helpers import modes
from helpers.model import MODEL_DIR

ROOT = MODEL_DIR.parents[1]
DEMO = ROOT / "bond_portfolio"
COVERAGE = ROOT / "tools" / "cy" / "sample_inputs"
RUN = ROOT / "bond_portfolio" / "run.py"
CSV_FILES = ("cashflows.csv", "period_cashflows.csv", "valuation_scen1.csv", "valuation_scen2.csv",
             "valuation_totals.csv")
RESULT_COLUMNS = ["bond_key", "settlement_date", "notional", "npv", "settlement_value", "dirty_price",
                  "clean_price", "accrued_amount", "market_value", "tradable", "expired"]
TOTALS = ["npv_total", "mv_total", "sv_total", "accrued_total", "n_tradable", "n_expired"]

_spec = importlib.util.spec_from_file_location("bp_run", RUN)
runpy_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(runpy_mod)

_COUNT = iter(range(10**6))


def private_model(prefix, input_dir=None):
    m = mx.read_model(MODEL_DIR, name=f"{prefix}{next(_COUNT)}")
    if input_dir is not None:
        m.Data.input_dir = str(input_dir)
    return m


def formula_error(fn, *args):
    """The ORIGINAL exception a formula raises (unwrapping modelx's FormulaError), or None."""
    try:
        fn(*args)
    except mx.core.errors.FormulaError:
        return mx.get_error()
    except Exception as e:  # noqa: BLE001 - exported/compiled models raise directly
        return e
    return None


def run_py(inputs, out, *args, build=None):
    env = dict(os.environ)
    if build is not None:
        env["BONDPORTFOLIO_BUILD"] = str(build)
    return subprocess.run([sys.executable, "-B", str(RUN), "--inputs", str(inputs), "--out", str(out), *args],
                          capture_output=True, text=True, timeout=900, env=env)


def copy_inputs(src, dst):
    dst.mkdir(parents=True, exist_ok=True)
    for p in src.glob("*.csv"):
        shutil.copy(p, dst)
    return dst


def edit_csv(path, fn):
    """Rewrite the CSV file ``path`` as ``fn(rows)`` (rows are dicts of strings)."""
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    columns = list(rows[0].keys())
    rows = fn(rows)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=columns, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def set_where(pred, **values):
    def fn(rows):
        for r in rows:
            if pred(r):
                r.update(values)
        return rows
    return fn


def at(s, t, node=None):
    return lambda r: r["scen_id"] == str(s) and r["t"] == str(t) and (node is None or r["node"] == str(node))


def model_sizes(m):
    """The model-level sizes, as ``tools/build_cy.py`` writes them into ``sizes.json``."""
    return {k: v for k, v in m.refs.items()
            if isinstance(v, int) and not isinstance(v, bool) and (k.startswith("MAX_") or k == "CAL_MAX")}


def bits(x):
    return struct.pack("<d", float(x))


# --------------------------------------------------------------------------- fixtures
@pytest.fixture(scope="module")
def demo_model():
    m = private_model("DriverDemo", DEMO)
    yield m
    m.close()


@pytest.fixture(scope="module")
def export_build(tmp_path_factory):
    """A build directory holding a fresh export of the CURRENT model and a ``sizes.json`` from its References."""
    build = tmp_path_factory.mktemp("build")
    m = mx.read_model(MODEL_DIR, name="BondPortfolio")
    try:
        mx.export_model(m, build / "BondPortfolio_nomx")
        sizes = model_sizes(m)
    finally:
        m.close()
    (build / "sizes.json").write_text(json.dumps(sizes, indent=1), encoding="utf-8")
    return build


@pytest.fixture(scope="module")
def runs(tmp_path_factory, export_build):
    """``{mode: output directory}`` of run.py on the demo inputs, in modelx and export mode."""
    out = {}
    for mode in ("modelx", "export"):
        d = tmp_path_factory.mktemp(f"run_{mode}")
        proc = run_py(DEMO, d, "--mode", mode, build=export_build)
        assert proc.returncode == 0, proc.stderr
        out[mode] = d
    return out


def read_valuation(path):
    return pd.read_csv(path, dtype={"bond_key": str, "settlement_date": str, "val_date": str},
                       keep_default_na=False, float_precision="round_trip")


# --------------------------------------------------------------------------- input checks
SAME_TIME = "two passed dates (March 30th, 2017 and March 31st, 2017) correspond to the same time " \
            "under this curve's day count convention (30E/360 (Eurobond Basis))"


def same_time_inputs(dst, day_counter="Thirty360.European"):
    """The demo inputs with the (2, 2) ZeroCurve on ``day_counter`` and nodes 1, 2 on 2017-03-30 and -31."""
    copy_inputs(DEMO, dst)
    edit_csv(dst / "curve_params.csv", set_where(at(2, 2), day_counter=day_counter))
    edit_csv(dst / "curve_nodes.csv", set_where(at(2, 2, 1), date="2017-03-30"))
    edit_csv(dst / "curve_nodes.csv", set_where(at(2, 2, 2), date="2017-03-31"))
    return dst


def test_daycounter_names_are_pureqls(demo_model):
    from helpers.pureql_ref import pq_daycounter
    for code in (1, 2, 10, 11, 12):
        assert demo_model.Dates.daycounter_name(code) == str(pq_daycounter(code)), code
    assert demo_model.Dates.daycounter_name(13) == "day counter 13"


@pytest.mark.parametrize("dc", ["Thirty360.European", "Thirty360.EurobondBasis"])
def test_check_inputs_rejects_nodes_at_the_same_time(tmp_path, dc):
    """30E/360 maps the 30th and the 31st to the same time: check_inputs refuses the curve up front."""
    same_time_inputs(tmp_path, dc)
    m = private_model("DriverSameTime", tmp_path)
    try:
        err = formula_error(m.Data.check_inputs)
        assert isinstance(err, ValueError)
        assert "curve_nodes.csv (scen_id 2, t 2, ZeroCurve): " + SAME_TIME + " (node 2, line 37)" in str(err)
        assert "(1 problem(s))" in str(err)
        # the lazy check of the Valuation item gives the same pureql message
        err2 = formula_error(m.Valuation[2, 2].curve_ok)
        assert isinstance(err2, ValueError) and str(err2) == SAME_TIME
    finally:
        m.close()


def test_same_time_message_is_pureqls():
    """pureql's ZeroCurve (``InterpolatedCurve.setupTimes``) refuses the same nodes with the same message."""
    from pureql import _state
    from pureql.errors import Error
    from pureql.math.interpolations.linearinterpolation import Linear
    from pureql.termstructures.yield_.zerocurve import ZeroCurve

    from helpers.pureql_ref import pq_comp, pq_date, pq_daycounter, pq_freq, ql

    dates = [pq_date(x) for x in (42629, 42824, 42825, 43724, 44455)]  # 2016-09-16, 2017-03-30/31, ...
    before = _state.snapshot_all()
    try:
        with pytest.raises(Error) as ei:
            ZeroCurve(dates, [0.002, 0.004, 0.008, 0.012, 0.016], pq_daycounter(12), ql.NullCalendar(), Linear(),
                      pq_comp(2), pq_freq(1))
    finally:
        _state.restore_all(before)
    assert str(ei.value) == SAME_TIME


@pytest.mark.oracle
def test_same_time_message_is_quantlibs():
    QL = pytest.importorskip("QuantLib")
    dates = [QL.Date(16, 9, 2016), QL.Date(30, 3, 2017), QL.Date(31, 3, 2017), QL.Date(16, 9, 2019)]
    with pytest.raises(RuntimeError) as ei:
        QL.ZeroCurve(dates, [0.002, 0.004, 0.008, 0.012], QL.Thirty360(QL.Thirty360.European))
    assert SAME_TIME in str(ei.value)


def test_check_inputs_still_passes_on_the_shipped_inputs():
    for d in (DEMO, COVERAGE):
        m = private_model("DriverInputs", d)
        try:
            assert m.Data.check_inputs() is True
        finally:
            m.close()


# --------------------------------------------------------------------------- limits
def kd_bound(m):
    """The latest flow or issue date minus the earliest valuation date."""
    cols = m.Legs.leg_columns()
    vd = m.Data.val_date_arr()
    return max(int(cols["cf_date"].max()), int(cols["bk_issue"].max())) - int(vd.min())


def test_check_limits_lists_every_excess():
    m = private_model("DriverLimits", DEMO)
    try:
        assert m.Legs.check_limits() is True
        kd = kd_bound(m)
        m.MAX_BONDS = 12
        m.MAX_FLOWS = 100
        m.MAX_SETTLE_DAYS = 2
        m.MAX_T = 3
        m.MAX_SCEN = 1
        m.MAX_NODES = 8
        m.MAX_KD = kd
        err = formula_error(m.Legs.check_limits)
        assert isinstance(err, ValueError)
        text = str(err)
        for part in ("13 bonds exceed MAX_BONDS (12)", "153 flows exceed MAX_FLOWS (100)",
                     "4 valuation dates exceed MAX_T (3)", "2 scenarios exceed MAX_SCEN (1)",
                     "the ZeroCurve of (scen_id 1, t 1) has 9 nodes, more than MAX_NODES (8)",
                     "the ZeroCurve of (scen_id 2, t 3) has 9 nodes, more than MAX_NODES (8)",
                     "bond 'HEADLINE_10Y': settlement days 3 outside 0..MAX_SETTLE_DAYS (2)",
                     f"the latest flow or issue date (June 15th, 2026) is {kd} days after the earliest "
                     f"valuation date (September 16th, 2015): day offsets must be below MAX_KD ({kd})"):
            assert part in text, part
        assert text.startswith("the inputs exceed the model limits (")
        assert "(scen_id 2, t 2)" not in text  # 5 nodes
    finally:
        m.close()


def test_max_kd_boundary():
    m = private_model("DriverKd", DEMO)
    try:
        kd = kd_bound(m)
        assert kd == (datetime.date(2026, 6, 15) - datetime.date(2015, 9, 16)).days == 3925
        m.MAX_KD = kd + 1
        assert m.Legs.check_limits() is True
        m.MAX_KD = kd
        assert "day offsets must be below MAX_KD" in str(formula_error(m.Legs.check_limits))
    finally:
        m.close()


@pytest.mark.parametrize("input_dir", [DEMO, COVERAGE], ids=["demo", "coverage"])
def test_kd_bound_covers_every_offset_the_valuation_uses(input_dir):
    """Every ``kd`` a Valuation item discounts at (all of them, after result_frame) is within the bound."""
    m = private_model("DriverKdUse", input_dir)
    try:
        bound = kd_bound(m)
        seen = []
        for s in range(1, m.Data.n_scen() + 1):
            for t in range(m.Data.n_times()):
                v = m.Valuation[s, t]
                v.result_frame()
                for name in ("curve_time", "range_ok", "discount"):
                    seen += [k[0] if isinstance(k, tuple) else k for k in getattr(v, name).keys()]
        assert seen and min(seen) >= 0
        assert max(seen) <= bound
    finally:
        m.close()


def test_driver_sizes_agree_with_check_limits():
    """run.py's measurement of the inputs and Legs.check_limits() refuse the same limits."""
    m = private_model("DriverSizes", DEMO)
    try:
        needed = runpy_mod.needed_sizes(m)
        sizes = model_sizes(m)
        assert runpy_mod.size_problems(needed, sizes) == []
        assert needed["MAX_KD"][0] == kd_bound(m) + 1
        assert needed["MAX_BONDS"][0] == 13 and needed["MAX_FLOWS"][0] == 153
        assert needed["MAX_T"][0] == 4 and needed["MAX_SCEN"][0] == 2 and needed["MAX_NODES"][0] == 9
        for key in ("MAX_BONDS", "MAX_FLOWS", "MAX_T", "MAX_SCEN", "MAX_NODES", "MAX_KD", "MAX_SETTLE_DAYS"):
            small = dict(sizes, **{key: needed[key][0] - 1})
            problems = runpy_mod.size_problems(needed, small)
            assert len(problems) == 1 and key in problems[0], key
            setattr(m, key, small[key])
            assert isinstance(formula_error(m.Legs.check_limits), ValueError), key
            setattr(m, key, sizes[key])
        assert m.Legs.check_limits() is True
    finally:
        m.close()


# --------------------------------------------------------------------------- the driver end to end
def test_modelx_and_export_runs_write_identical_files(runs):
    for f in CSV_FILES:
        a = (runs["modelx"] / f).read_bytes()
        assert a == (runs["export"] / f).read_bytes(), f
    assert not (runs["modelx"] / "valuation_scen3.csv").exists()


@pytest.mark.compiled
def test_compiled_run_writes_identical_files(runs, tmp_path):
    if modes.compiled_package() is None:
        pytest.skip("no compiled build; run tools/build_cy.py")
    proc = run_py(DEMO, tmp_path, "--mode", "compiled")
    assert proc.returncode == 0, proc.stderr
    for f in CSV_FILES:
        assert (tmp_path / f).read_bytes() == (runs["modelx"] / f).read_bytes(), f
    summary = json.loads((tmp_path / "run_summary.json").read_text(encoding="utf-8"))
    assert summary["bond_items_freed"] == 13


def test_outputs_are_the_models_own_values(runs, demo_model):
    """valuation_scen<k>.csv and valuation_totals.csv hold result_frame() and the aggregates, bit for bit."""
    m = demo_model
    S, T = m.Data.n_scen(), m.Data.n_times()
    totals = read_valuation(runs["modelx"] / "valuation_totals.csv")
    assert list(totals.columns) == ["scen_id", "t", "val_date"] + TOTALS
    assert list(zip(totals["scen_id"], totals["t"])) == [(s, t) for s in range(1, S + 1) for t in range(T)]
    vdates = m.Data.val_date_table()["val_date"].tolist()
    for s in range(1, S + 1):
        df = read_valuation(runs["modelx"] / f"valuation_scen{s}.csv")
        assert list(df.columns) == ["scen_id", "t", "val_date"] + RESULT_COLUMNS
        assert (df["scen_id"] == s).all()
        for t in range(T):
            v = m.Valuation[s, t]
            exp = v.result_frame()
            got = df[df["t"] == t].reset_index(drop=True)
            assert len(got) == len(exp) == m.Data.n_bonds()
            assert (got["val_date"] == vdates[t]).all()
            for c in RESULT_COLUMNS:
                if exp[c].dtype.kind == "f":
                    assert [bits(x) for x in got[c]] == [bits(x) for x in exp[c]], (s, t, c)
                else:
                    assert got[c].tolist() == exp[c].tolist(), (s, t, c)
            row = totals[(totals["scen_id"] == s) & (totals["t"] == t)].iloc[0]
            assert row["val_date"] == vdates[t]
            for c in TOTALS:
                x = getattr(v, c)()
                if isinstance(x, float):
                    assert bits(row[c]) == bits(x), (s, t, c)
                else:
                    assert int(row[c]) == x, (s, t, c)
    # the goldens of the headline bond at t = 0 (plan Phase 2)
    df = read_valuation(runs["modelx"] / "valuation_scen1.csv")
    head = df[(df["t"] == 0) & (df["bond_key"] == "HEADLINE_10Y")].iloc[0]
    assert head["npv"] == 108.36776235612268 and head["clean_price"] == 108.34563953853349


def test_cash_flow_outputs_are_unchanged(runs, demo_model):
    cf = pd.read_csv(runs["modelx"] / "cashflows.csv", keep_default_na=False, dtype=str)
    assert len(cf) == demo_model.Legs.n_flows()
    pf = pd.read_csv(runs["modelx"] / "period_cashflows.csv", keep_default_na=False, dtype=str)
    assert (pf["level"] == "portfolio").sum() == demo_model.Data.n_times() + 1


def test_run_summary(runs):
    for mode, d in runs.items():
        s = json.loads((d / "run_summary.json").read_text(encoding="utf-8"))
        assert s["mode"] == mode
        assert s["counts"] == {"bonds": 13, "flows": 153, "scenarios": 2, "times": 4, "items": 8,
                               "bond_points": 104}
        assert s["valuation"]["items"] == 8 and s["valuation"]["us_per_bond_point"] > 0
        assert {"load", "inputs, Legs, limits", "cash-flow outputs", "curve pre-flight", "valuation",
                "valuation output writing"} <= set(s["stages"])
        if sys.platform == "win32":
            assert s["memory"]["source"] == "GetProcessMemoryInfo" and s["memory"]["peak"] > 0
        if mode == "export":
            assert s["bond_items_freed"] == 13
            assert s["build_sizes"]["MAX_KD"] == 40000
        else:
            assert "bond_items_freed" not in s


def test_subset_run_writes_the_same_rows(runs, tmp_path):
    proc = run_py(DEMO, tmp_path, "--scen", "2", "--times", "1,3")
    assert proc.returncode == 0, proc.stderr
    assert not (tmp_path / "valuation_scen1.csv").exists()
    full = (runs["modelx"] / "valuation_scen2.csv").read_text(encoding="utf-8").splitlines()
    sub = (tmp_path / "valuation_scen2.csv").read_text(encoding="utf-8").splitlines()
    assert sub[0] == full[0]
    assert sub[1:] == [r for r in full[1:] if r.split(",")[1] in ("1", "3")]
    assert len(sub) == 1 + 2 * 13
    tot = (tmp_path / "valuation_totals.csv").read_text(encoding="utf-8").splitlines()
    full_tot = (runs["modelx"] / "valuation_totals.csv").read_text(encoding="utf-8").splitlines()
    assert tot == [full_tot[0]] + [r for r in full_tot[1:] if r.startswith(("2,1,", "2,3,"))]
    s = json.loads((tmp_path / "run_summary.json").read_text(encoding="utf-8"))
    assert s["counts"]["items"] == 2


@pytest.mark.parametrize("args,message", [
    (("--scen", "3"), "scenario 3 outside 1..2"),
    (("--times", "2-5"), "t 4 outside 0..3"),
    (("--times", "1,x"), "--times: invalid item 'x'"),
    (("--scen", "2-1"), "--scen: empty range '2-1'"),
])
def test_run_py_rejects_bad_selections(tmp_path, args, message):
    proc = run_py(DEMO, tmp_path, *args)
    assert proc.returncode == 1
    assert message in proc.stderr


def test_run_py_refuses_a_curve_pureql_cannot_build(tmp_path):
    same_time_inputs(tmp_path / "in")
    proc = run_py(tmp_path / "in", tmp_path / "out")
    assert proc.returncode == 1
    assert SAME_TIME in proc.stderr
    assert not (tmp_path / "out" / "valuation_totals.csv").exists()


def test_run_py_refuses_inputs_beyond_the_build_sizes(tmp_path, export_build):
    build = tmp_path / "build"
    shutil.copytree(export_build / "BondPortfolio_nomx", build / "BondPortfolio_nomx")
    sizes = json.loads((export_build / "sizes.json").read_text(encoding="utf-8"))
    sizes.update(MAX_BONDS=12, MAX_KD=3000)
    (build / "sizes.json").write_text(json.dumps(sizes), encoding="utf-8")
    proc = run_py(DEMO, tmp_path / "out", "--mode", "export", build=build)
    assert proc.returncode == 1, proc.stdout
    assert "the inputs exceed the sizes the build" in proc.stderr
    assert "13 bonds: needs MAX_BONDS >= 13, the build has MAX_BONDS = 12" in proc.stderr
    assert ("day offset 3925 (latest flow or issue date 2026-06-15 - earliest valuation date 2015-09-16): "
            "needs MAX_KD >= 3926, the build has MAX_KD = 3000") in proc.stderr
    assert not (tmp_path / "out" / "cashflows.csv").exists()


def test_run_py_compiled_needs_sizes_json(tmp_path):
    build = tmp_path / "build"
    (build / "BondPortfolio_nomx_cy").mkdir(parents=True)
    proc = run_py(DEMO, tmp_path / "out", "--mode", "compiled", build=build)
    assert proc.returncode != 0
    assert "sizes.json not found" in proc.stderr


def test_curve_pre_flight_lists_the_items_the_valuation_would_fail(tmp_path, demo_model):
    """(2, 2) without extrapolation stops at 2023-09-18 before the last flow: refused before any valuation."""
    inputs = copy_inputs(DEMO, tmp_path / "in")
    edit_csv(inputs / "curve_params.csv", set_where(at(2, 2), extrapolate="0"))
    proc = run_py(inputs, tmp_path / "out")
    assert proc.returncode == 1
    assert "curve pre-flight failed at 1 (scen_id, t) item(s)" in proc.stderr
    assert not (tmp_path / "out" / "valuation_totals.csv").exists()
    # the pre-flight reports checkRange at the latest flow date; the valuation of the bond paying
    # it raises the same range error (at its first flow past the curve's max time)
    m = private_model("DriverPreflight", inputs)
    try:
        cols = m.Legs.leg_columns()
        v = m.Valuation[2, 2]
        kd = int(cols["cf_date"].max()) - v.vdate()
        err = formula_error(v.range_ok, kd)
        assert isinstance(err, ValueError)
        assert f"(scen_id 2, t 2): {err}" in proc.stderr
        assert str(err) == f"time ({v.curve_time(kd):g}) is past max curve time ({v.max_time():g})"
        b = int(cols["cf_owner"][int(cols["cf_date"].argmax())])
        err2 = formula_error(v.npv, b)
        assert isinstance(err2, ValueError) and str(err2).endswith(f"is past max curve time ({v.max_time():g})")
    finally:
        m.close()
