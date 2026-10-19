"""Run the BondPortfolio model on a directory of inputs and write its outputs.

Usage::

    python bond_portfolio/run.py --inputs DIR --out DIR [--mode modelx|export|compiled]
                                 [--scen LIST] [--times LIST]
                                 [--output-level 1|2|3] [--solver-errors raise|nan]

``LIST`` is a comma-separated list of integers and inclusive ranges, e.g.
``2`` or ``0-12,24``. ``--scen`` selects scenario ids (default: all, 1..S) and
``--times`` valuation-date indices (default: all, 0..T-1).

``--output-level`` sets ``Data.output_level`` (default 1): 2 adds the yield
analytics to the valuation outputs and 3 also the z-spread (docs/model-contract.md
4.8). ``--solver-errors`` sets ``Data.solver_error_policy``: ``raise`` (the
model's default, ``ERR_RAISE``) stops the run at the first failed solve with
pureql's message and the item; ``nan`` (``ERR_NAN``) writes NaN there.

Steps:

1. load the model: ``modelx`` reads ``bond_portfolio/BondPortfolio`` with
   ``mx.read_model``; ``export`` and ``compiled`` import
   ``BondPortfolio_nomx`` and ``BondPortfolio_nomx_cy`` from the build
   directory of ``tools/buildpaths.py`` (made by ``tools/build_cy.py``) and
   create a fresh instance;
2. set ``Data.input_dir`` (and the output level and solver error policy)
   on the fresh instance, and run ``Data.check_inputs()`` and
   ``Legs.check_limits()``. In export and compiled mode the inputs are also
   measured against the sizes the build was compiled with
   (``<build>/sizes.json``), and the run is refused if they exceed them;
3. export and compiled mode: delete the ``Bond`` items (``Legs`` now holds
   all that is needed) and ``gc.collect()``. In modelx mode the Bond items
   stay: deleting them would clear ``Legs``;
4. write ``cashflows.csv``, the portfolio cash flows
   (``Legs.cashflow_frame()``), and ``period_cashflows.csv``, the flows
   bucketed into the projection periods: one row per (bond, period) with
   flows (``Proj.bond_cf_table()``, ``level`` = ``bond``) followed by the
   portfolio totals of every period 0..T (``Proj.period_table()``, ``level``
   = ``portfolio``, blank ``bond_key``). Then (export and compiled)
   ``gc.collect()`` and ``gc.freeze()``;
5. pre-flight the curves of every (scen_id, t) of the run:
   ``Valuation[scen_id, t].curve_ok()`` and ``range_ok(kd)`` at the latest
   flow date. A curve that does not extrapolate and stops before that date
   would fail the valuation with pureql's range error ("time (...) is past
   max curve time (...)"); the pre-flight lists every such (scen_id, t)
   before any valuation starts;
6. value scenario-major: for each scen_id, for each t, create
   ``Valuation[scen_id, t]``, append its ``result_frame()`` to
   ``valuation_scen<scen_id>.csv`` and its aggregates to
   ``valuation_totals.csv``, then ``del model.Valuation[scen_id, t]`` and
   ``gc.collect()`` (exported and compiled Spaces are self-cyclic, so ``del``
   alone frees nothing: docs/mx2cy-issues.md #4). One item is alive at a time;
7. write ``run_summary.json`` (counts, wall time per stage, microseconds per
   bond-point, peak RSS) and print the timings.

Period ``per`` runs from ``period_start`` to ``period_end``: period 0 holds the
flows already paid at the first valuation date, period ``per`` the flows paid
after ``val_date[per-1]`` up to ``val_date[per]``, and period T the flows
after the last valuation date (blank ``period_end``).

``valuation_scen<k>.csv`` has one row per (t, bond), in t then bond order:
``scen_id``, ``t``, ``val_date`` (ISO), then the columns of
``Valuation.result_frame()``: ``bond_key``, ``settlement_date``, ``notional``,
``npv``, ``settlement_value``, ``dirty_price``, ``clean_price``,
``accrued_amount``, ``market_value``, ``tradable``, ``expired``; at output
level 2 also ``ytm``, ``risk_yield``, ``duration_simple``,
``duration_modified``, ``duration_macaulay``, ``convexity``, ``bpv``,
``yvbp``, and at level 3 ``zspread`` (NaN where there is no quoted price).
``valuation_totals.csv`` has one row per (scen_id, t), scenario-major:
``scen_id``, ``t``, ``val_date``, ``npv_total``, ``mv_total``, ``sv_total``,
``accrued_total``, ``n_tradable``, ``n_expired``.

Floats are written with Python's shortest round-trip representation, so the
files reproduce the model's values exactly, and the three modes write
byte-identical CSV files.
"""

import argparse
import datetime
import gc
import json
import os
import pathlib
import platform
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / "bond_portfolio" / "BondPortfolio"
sys.path.insert(0, str(ROOT / "tools"))
from buildpaths import build_dir  # noqa: E402

PACKAGES = {"export": "BondPortfolio_nomx", "compiled": "BondPortfolio_nomx_cy"}
PERIOD_COLUMNS = ["level", "bond_key", "per", "period_start", "period_end", "coupon", "amortization",
                  "redemption", "total"]
KEY_COLUMNS = ["scen_id", "t", "val_date"]
TOTAL_COLUMNS = ["npv_total", "mv_total", "sv_total", "accrued_total", "n_tradable", "n_expired"]
BASE_DATE = datetime.date(1899, 12, 30)


def iso(serial):
    """ISO text of a date serial ('' for the null date)."""
    return "" if serial == 0 else (BASE_DATE + datetime.timedelta(days=int(serial))).isoformat()


# ----------------------------------------------------------------------------- memory

def memory_info():
    """``{"peak": bytes, "current": bytes, "source": str}`` of this process; values None if unavailable.

    Windows: ``GetProcessMemoryInfo`` (peak and current working set). POSIX:
    ``getrusage`` (peak) and ``/proc/self/statm`` (current). Otherwise, if
    :mod:`tracemalloc` is tracing, its peak and current (Python allocations only).
    """
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes

            class Counters(ctypes.Structure):
                _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                            ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                            ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]

            c = Counters()
            c.cb = ctypes.sizeof(c)
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.GetCurrentProcess.restype = wintypes.HANDLE
            fn = kernel32.K32GetProcessMemoryInfo
            fn.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
            fn.restype = wintypes.BOOL
            if fn(kernel32.GetCurrentProcess(), ctypes.byref(c), c.cb):
                return {"peak": int(c.PeakWorkingSetSize), "current": int(c.WorkingSetSize),
                        "source": "GetProcessMemoryInfo"}
        except (OSError, AttributeError):
            pass
    else:
        try:
            import resource
            peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            peak *= 1 if sys.platform == "darwin" else 1024
            current = None
            statm = pathlib.Path("/proc/self/statm")
            if statm.exists():
                current = int(statm.read_text().split()[1]) * os.sysconf("SC_PAGE_SIZE")
            return {"peak": int(peak), "current": current, "source": "getrusage"}
        except (ImportError, OSError, ValueError):
            pass
    import tracemalloc
    if tracemalloc.is_tracing():
        current, peak = tracemalloc.get_traced_memory()
        return {"peak": peak, "current": current, "source": "tracemalloc (Python allocations only)"}
    return {"peak": None, "current": None, "source": "unavailable"}


def mb(n):
    return "n/a" if n is None else f"{n / 2**20:,.1f} MB"


# ----------------------------------------------------------------------------- loading

def load(mode):
    """A model instance in ``mode`` and a function that unwraps formula errors."""
    if mode == "modelx":
        import modelx as mx

        m = mx.read_model(MODEL_DIR, name="BondPortfolio_run")

        def unwrap(e):
            from modelx.core.errors import FormulaError
            return mx.get_error() if isinstance(e, FormulaError) and mx.get_error() is not None else e

        return m, unwrap
    build = build_dir()
    package = PACKAGES[mode]
    if not (build / package).exists():
        raise SystemExit(f"run.py: {build / package} not found; build it with tools/build_cy.py")
    if str(build) not in sys.path:
        sys.path.insert(0, str(build))
    import importlib
    pkg = importlib.import_module(package)
    return pkg._mx_model._c_BondPortfolio(), (lambda e: e)


def build_sizes(mode):
    """The compiled sizes of the build (``<build>/sizes.json``), or None in modelx mode.

    Required in compiled mode. In export mode the file is used when present
    (it describes the build the export belongs to), so that an export run is
    always one the compiled build can reproduce.
    """
    if mode == "modelx":
        return None
    path = build_dir() / "sizes.json"
    if not path.exists():
        if mode == "compiled":
            raise SystemExit(f"run.py: {path} not found; rebuild with tools/build_cy.py")
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def needed_sizes(m):
    """What the inputs need of each compiled size: ``{size name: (smallest admissible value, what)}``.

    Measured from Data and Legs. The array sizes of the compiled model
    (``tools/build_cy.py`` ``SPEC_MAP``) admit indices ``0..size-1``; the
    model limits (``MAX_BONDS`` ...) are maxima.
    """
    import numpy as np

    cols = m.Legs.leg_columns()
    N = int(m.Data.n_bonds())
    P = len(cols["cf_date"])
    T = int(m.Data.n_times())
    S = int(m.Data.n_scen())
    out = {"MAX_BONDS": (N, f"{N} bonds"), "MAX_FLOWS": (P, f"{P} flows"),
           "MAX_T": (T, f"{T} valuation dates"), "MAX_SCEN": (S, f"{S} scenarios")}
    if N:
        per_bond = int(np.diff(np.asarray(cols["cf_lo"])).max())
        out["MAX_SCHED"] = (per_bond, f"{per_bond} flows in one bond")
        nsd = int(np.asarray(cols["bk_settle_days"]).max())
        out["MAX_SETTLE_DAYS"] = (nsd, f"{nsd} settlement days")
        cal = int(np.asarray(cols["bk_cal"]).max())
        out["CAL_MAX"] = (cal + 1, f"calendar code {cal}")
    ctype = np.asarray(m.Data.curve_columns()["c_type"])
    ncnt = np.asarray(m.Data.node_columns()["n_cnt"])
    zero = ncnt[ctype == 0]
    if zero.size:
        out["MAX_NODES"] = (int(zero.max()), f"{int(zero.max())} nodes in one ZeroCurve")
    vd = np.asarray(m.Data.val_date_arr())
    if T and (N or P):
        dmax = max(int(np.asarray(cols["cf_date"]).max()) if P else 0,
                   int(np.asarray(cols["bk_issue"]).max()) if N else 0)
        kd = dmax - int(vd.min())
        out["MAX_KD"] = (kd + 1, f"day offset {kd} (latest flow or issue date {iso(dmax)} - "
                                 f"earliest valuation date {iso(int(vd.min()))})")
    dates = [int(vd.max())] if T else []
    if P:
        dates.append(int(np.asarray(cols["cf_date"]).max()))
    nd = np.asarray(m.Data.node_columns()["n_date"])
    if nd.size:
        dates.append(int(nd.max()))
    if dates:
        out["MAX_SERIAL"] = (max(dates), f"latest date {iso(max(dates))}")
    return out


def size_problems(needed, sizes):
    """Messages for each size in ``needed`` that ``sizes`` (``{name: size}``) does not admit."""
    problems = []
    for key, (value, what) in needed.items():
        if key in sizes and value > sizes[key]:
            problems.append(f"{what}: needs {key} >= {value}, the build has {key} = {sizes[key]}")
    return problems


# ----------------------------------------------------------------------------- outputs

def period_frame(m):
    """The bond rows of ``Proj.bond_cf_table()`` followed by the portfolio rows of ``Proj.period_table()``."""
    import pandas as pd

    periods = m.Proj.period_table()
    starts = dict(zip(periods["per"].tolist(), periods["period_start"].tolist()))
    ends = dict(zip(periods["per"].tolist(), periods["period_end"].tolist()))
    bonds = m.Proj.bond_cf_table()
    rows = []
    for key, per, c, a, r in zip(bonds["bond_key"].tolist(), bonds["per"].tolist(), bonds["coupon"].tolist(),
                                 bonds["amortization"].tolist(), bonds["redemption"].tolist()):
        rows.append(["bond", key, per, starts[per], ends[per], c, a, r, c + a + r])
    for per, s, e, c, a, r, tot in zip(*(periods[k].tolist() for k in
                                         ("per", "period_start", "period_end", "coupon", "amortization",
                                          "redemption", "total"))):
        rows.append(["portfolio", "", per, s, e, c, a, r, tot])
    return pd.DataFrame(rows, columns=PERIOD_COLUMNS)


def free_bond_items(m):
    """Delete every ``Bond[b]`` item of an exported or compiled model, then ``gc.collect()``; return the count.

    ``Legs.leg_columns()`` holds everything the later stages read, and an
    exported model never invalidates it.
    """
    n = 0
    for b in range(int(m.Data.n_bonds())):
        try:
            del m.Bond[b]
            n += 1
        except KeyError:
            pass
    gc.collect()
    return n


def parse_list(text, what):
    """The sorted distinct non-negative integers of ``text``: comma-separated items ``n`` or ``a-b`` (inclusive)."""
    import re

    out = set()
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        mt = re.fullmatch(r"(\d+)(?:-(\d+))?", part)
        if not mt:
            raise ValueError(f"--{what}: invalid item '{part}' (expected integers or ranges like 0-12)")
        a = int(mt.group(1))
        b = int(mt.group(2)) if mt.group(2) is not None else a
        if b < a:
            raise ValueError(f"--{what}: empty range '{part}'")
        out.update(range(a, b + 1))
    if not out:
        raise ValueError(f"--{what}: empty list")
    return sorted(out)


def preflight(m, pairs, unwrap):
    """Messages for each (scen_id, t) whose curve is unusable or does not reach the latest flow date.

    ``curve_ok()``, then ``range_ok(kd)`` for the latest flow date ``d`` of
    the portfolio when ``kd = d - vdate()`` is positive: that flow is then
    alive at t, so the valuation of its bond would call ``discount(kd)`` and
    raise the range error (at the first of its flows past the curve's max
    time). A failure here is therefore always a failure of the run; a pass
    does not exclude a later range error at a settlement date past the last
    node, which the valuation reports with its (scen_id, t). Each item is
    deleted again (and collected).
    """
    import numpy as np

    cf_date = np.asarray(m.Legs.leg_columns()["cf_date"])
    dmax = int(cf_date.max()) if cf_date.size else 0
    problems = []
    for s, t in pairs:
        item = m.Valuation[s, t]
        try:
            item.curve_ok()
            kd = dmax - int(item.vdate())
            if kd > 0:
                item.range_ok(kd)
        except Exception as e:  # noqa: BLE001 - collect the formula's own error
            err = unwrap(e)
            if not isinstance(err, ValueError):
                raise err from None
            problems.append(f"(scen_id {s}, t {t}): {str(err).splitlines()[0]}")
        finally:
            item = None
            del m.Valuation[s, t]
            gc.collect()
    return problems


class Stages:
    """Wall time per stage, and the RSS at the end of each."""

    def __init__(self):
        self.seconds = {}
        self.rss = {}

    def run(self, name, fn, *args):
        t0 = time.perf_counter()
        try:
            return fn(*args)
        finally:
            self.seconds[name] = self.seconds.get(name, 0.0) + time.perf_counter() - t0
            self.rss[name] = memory_info()["current"]


def run(inputs, out, mode="modelx", scens=None, times=None, log=print, output_level=1,
        solver_error_policy=None):
    """Run the model on ``inputs`` and write every output into ``out``; return the run summary (a dict).

    ``scens`` and ``times`` are iterables of scen_ids and t indices (None: all).
    ``output_level`` (1, 2 or 3) and ``solver_error_policy`` (``ERR_RAISE`` 0,
    ``ERR_NAN`` 1; None keeps the model's default) are set on ``Data`` first.
    Invalid inputs, or inputs beyond the model or build sizes, raise
    ``ValueError`` before any output is written.
    """
    import numpy as np
    import pandas as pd

    t_start = time.perf_counter()
    out = pathlib.Path(out)
    st = Stages()
    sizes = build_sizes(mode)
    m, unwrap = st.run("load", load, mode)
    frozen = False
    if output_level not in (1, 2, 3):
        raise ValueError(f"output level {output_level} is not 1, 2 or 3")
    if solver_error_policy not in (None, 0, 1):
        raise ValueError(f"solver error policy {solver_error_policy} is not 0 (raise) or 1 (nan)")
    summary = {"mode": mode, "inputs": str(pathlib.Path(inputs).resolve()), "out": str(out.resolve()),
               "python": sys.version.split()[0], "platform": platform.platform(), "paths": [],
               "output_level": output_level}
    try:
        def check():
            m.Data.input_dir = str(pathlib.Path(inputs).resolve())
            m.Data.output_level = output_level
            if solver_error_policy is not None:
                m.Data.solver_error_policy = solver_error_policy
            summary["solver_error_policy"] = int(m.Data.solver_error_policy)
            m.Data.check_inputs()
            m.Legs.check_limits()  # builds Legs
            needed = needed_sizes(m)
            summary["needed_sizes"] = {k: v[0] for k, v in needed.items()}
            if sizes is not None:
                summary["build_sizes"] = sizes
                problems = size_problems(needed, sizes)
                if problems:
                    raise ValueError(f"the inputs exceed the sizes the build in {build_dir()} was compiled "
                                     f"with (sizes.json; rebuild with larger MAX_* References):\n  "
                                     + "\n  ".join(problems))
            elif mode == "export":
                log(f"note: {build_dir() / 'sizes.json'} not found; only the model's own limits were checked")

        try:
            st.run("inputs, Legs, limits", check)
        except Exception as e:  # noqa: BLE001 - report the formula's own error
            raise unwrap(e) from None

        N, T, S = int(m.Data.n_bonds()), int(m.Data.n_times()), int(m.Data.n_scen())
        P = int(m.Legs.n_flows())
        scens = list(range(1, S + 1)) if scens is None else list(scens)
        times = list(range(T)) if times is None else list(times)
        for s in scens:
            if not (1 <= s <= S):
                raise ValueError(f"scenario {s} outside 1..{S}")
        for t in times:
            if not (0 <= t < T):
                raise ValueError(f"t {t} outside 0..{T - 1}")
        pairs = [(s, t) for s in scens for t in times]
        summary["counts"] = {"bonds": N, "flows": P, "scenarios": S, "times": T, "items": len(pairs),
                             "bond_points": N * len(pairs)}
        log(f"{mode}: {N} bonds, {P} flows, {S} scenario(s) x {T} date(s); valuing {len(pairs)} item(s)")

        if mode != "modelx":
            summary["bond_items_freed"] = st.run("free Bond items", free_bond_items, m)

        out.mkdir(parents=True, exist_ok=True)

        def phase1():
            try:
                cf = m.Legs.cashflow_frame()
                pf = period_frame(m)
            except Exception as e:  # noqa: BLE001
                raise unwrap(e) from None
            paths = (out / "cashflows.csv", out / "period_cashflows.csv")
            cf.to_csv(paths[0], index=False, lineterminator="\n")
            pf.to_csv(paths[1], index=False, lineterminator="\n")
            return list(paths)

        summary["paths"] += st.run("cash-flow outputs", phase1)
        if mode != "modelx":
            gc.collect()
            gc.freeze()
            frozen = True

        problems = st.run("curve pre-flight", preflight, m, pairs, unwrap)
        if problems:
            raise ValueError(f"curve pre-flight failed at {len(problems)} (scen_id, t) item(s); the "
                             "valuation would raise there:\n  " + "\n  ".join(problems[:50])
                             + ("" if len(problems) <= 50 else f"\n  ... and {len(problems) - 50} more"))

        vd = [iso(int(x)) for x in np.asarray(m.Data.val_date_arr()).tolist()]
        totals_path = out / "valuation_totals.csv"
        summary["paths"].append(totals_path)
        t_val = time.perf_counter()
        t_last = t_val
        done = 0
        harvest_s = write_s = 0.0
        with open(totals_path, "w", newline="", encoding="utf-8") as ft:
            ft.write(",".join(KEY_COLUMNS + TOTAL_COLUMNS) + "\n")
            for s in scens:
                path = out / f"valuation_scen{s}.csv"
                summary["paths"].append(path)
                with open(path, "w", newline="", encoding="utf-8") as fs:
                    first = True
                    for t in times:
                        h0 = time.perf_counter()
                        item = m.Valuation[s, t]
                        try:
                            df = item.result_frame()
                            tot = [item.npv_total(), item.mv_total(), item.sv_total(), item.accrued_total(),
                                   item.n_tradable(), item.n_expired()]
                        except Exception as e:  # noqa: BLE001 - name the item
                            err = unwrap(e)
                            if isinstance(err, ValueError):
                                raise ValueError(f"Valuation[{s}, {t}] ({vd[t]}): {err}") from None
                            err.add_note(f"in Valuation[{s}, {t}] ({vd[t]})")
                            raise err from None
                        finally:
                            item = None
                            del m.Valuation[s, t]
                            gc.collect()
                        h1 = time.perf_counter()
                        df.insert(0, "val_date", vd[t])
                        df.insert(0, "t", t)
                        df.insert(0, "scen_id", s)
                        df.to_csv(fs, header=first, index=False, lineterminator="\n")
                        first = False
                        pd.DataFrame([[s, t, vd[t]] + tot], columns=KEY_COLUMNS + TOTAL_COLUMNS).to_csv(
                            ft, header=False, index=False, lineterminator="\n")
                        del df
                        h2 = time.perf_counter()
                        harvest_s += h1 - h0
                        write_s += h2 - h1
                        done += 1
                        now = time.perf_counter()
                        if now - t_last >= 30.0:
                            t_last = now
                            log(f"  {done}/{len(pairs)} items, {now - t_val:.0f}s elapsed "
                                f"(scen_id {s}, t {t})")
        # "valuation": create the item, result_frame() and the totals, del + gc.collect()
        st.seconds["valuation"] = harvest_s
        st.seconds["valuation output writing"] = write_s
        st.rss["valuation"] = st.rss["valuation output writing"] = memory_info()["current"]
        val_s = harvest_s + write_s
        summary["valuation"] = {
            "items": done, "seconds": val_s, "seconds_per_item": val_s / done if done else None,
            "us_per_bond_point": 1e6 * harvest_s / (N * done) if N and done else None,
            "us_per_bond_point_incl_writing": 1e6 * val_s / (N * done) if N and done else None}
    finally:
        if frozen:
            gc.unfreeze()
        if mode == "modelx":
            m.close()
    summary["stages"] = st.seconds
    summary["rss_after_stage"] = st.rss
    summary["total_seconds"] = time.perf_counter() - t_start
    summary["memory"] = memory_info()
    summary["paths"] = [str(p) for p in summary["paths"]]
    summary_path = out / "run_summary.json"
    summary_path.write_text(json.dumps(summary, indent=1), encoding="utf-8")
    summary["paths"].append(str(summary_path))
    return summary


def report(summary, log=print):
    """Print the stage timings, the speed and the peak RSS of a run summary."""
    log(f"  {'stage':<32}{'seconds':>9}   RSS after")
    for name, sec in summary["stages"].items():
        log(f"  {name:<32}{sec:9.2f}   {mb(summary['rss_after_stage'].get(name))}")
    log(f"  {'total':<32}{summary['total_seconds']:9.2f}")
    v = summary.get("valuation")
    if v and v["items"]:
        c = summary["counts"]
        log(f"valuation: {v['items']} item(s) x {c['bonds']} bonds = {v['items'] * c['bonds']:,} bond-points; "
            f"{v['seconds_per_item']:.3f} s per item; {v['us_per_bond_point']:.1f} us per bond-point "
            f"({v['us_per_bond_point_incl_writing']:.1f} with output writing)")
    mem = summary["memory"]
    log(f"peak RSS: {mb(mem['peak'])} ({mem['source']})")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--inputs", required=True, help="directory of the input CSV files")
    ap.add_argument("--out", required=True, help="output directory")
    ap.add_argument("--mode", choices=("modelx", "export", "compiled"), default="modelx")
    ap.add_argument("--scen", help="scenario ids to value, e.g. 1,3-4 (default: all)")
    ap.add_argument("--times", help="valuation-date indices t to value, e.g. 0-12,24 (default: all)")
    ap.add_argument("--output-level", type=int, choices=(1, 2, 3), default=1,
                    help="1: prices; 2: + yield, durations, convexity, BPV, YVBP; 3: + z-spread (default 1)")
    ap.add_argument("--solver-errors", choices=("raise", "nan"), default=None,
                    help="a failed yield or z-spread solve: raise (the model default) or NaN")
    args = ap.parse_args(argv)
    if memory_info()["source"] == "unavailable":
        import tracemalloc
        tracemalloc.start()
    try:
        scens = parse_list(args.scen, "scen") if args.scen else None
        times = parse_list(args.times, "times") if args.times else None
        policy = None if args.solver_errors is None else {"raise": 0, "nan": 1}[args.solver_errors]
        summary = run(args.inputs, args.out, args.mode, scens, times, output_level=args.output_level,
                      solver_error_policy=policy)
    except ValueError as e:
        print(f"run.py: {e}", file=sys.stderr)
        if args.output_level >= 2 and args.solver_errors is None:
            print("run.py: hint: --solver-errors nan writes NaN for a failed solve and for the Macaulay "
                  "duration of a yield that is not Compounded", file=sys.stderr)
        return 1
    for p in summary["paths"]:
        print(f"wrote {p}")
    report(summary)
    print(f"done in {summary['total_seconds']:.1f}s ({args.mode})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
