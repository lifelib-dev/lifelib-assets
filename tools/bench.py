"""Benchmark ``bond_portfolio/run.py`` on a generated portfolio, and record the results.

    python tools/bench.py [--n-bonds 10000] [--n-scen 2] [--n-times 121] [--step 1M] [--seed 1]
                          [--modes export,compiled] [--scen LIST] [--times LIST]
                          [--output-level 1|2|3] [--solver-errors raise|nan]
                          [--work DIR] [--keep] [--doc docs/performance.md]

1. Generate the inputs with ``bond_portfolio/generate_inputs.py`` into
   ``<work>/inputs`` (``--work`` defaults to a new temporary directory).
2. Run ``run.py --mode <mode>`` for each mode, each in a fresh process, into
   ``<work>/out_<mode>``; ``--scen`` / ``--times`` are passed through, to time
   a representative subset of a run too long to do in full, and so are
   ``--output-level`` / ``--solver-errors`` (the analytics columns; a
   generated portfolio has yields that are not Compounded, so level 2 or 3
   needs ``--solver-errors nan``, or its Macaulay durations raise). The export and
   compiled packages come from the build directory (``tools/buildpaths.py``);
   build them first with ``tools/build_cy.py`` (from PowerShell on Windows),
   whose ``sizes.json`` must cover the portfolio (run.py refuses otherwise).
3. Check that the modes wrote byte-identical CSV files (SHA-256).
4. Print a table of wall time per stage, microseconds per bond-point
   (one bond valued at one (scen_id, t)) and peak RSS, headed by the
   portfolio, the machine and the compiled build (its modelx-cython source and
   options, from ``<build>/build_info.json``, which ``tools/build_cy.py``
   writes); write
   ``<work>/bench.json``; with ``--doc``, replace the block between
   ``<!-- bench:begin -->`` and ``<!-- bench:end -->`` of that Markdown file
   with the table. When only a subset of the (scen_id, t) grid was valued,
   the table also gives the valuation time of the full grid extrapolated at
   the measured seconds per item.

The work directory is deleted at the end unless ``--keep`` (or ``--work``) is given.
"""

import argparse
import datetime
import hashlib
import importlib.util
import json
import os
import pathlib
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
RUN = ROOT / "bond_portfolio" / "run.py"
GENERATE = ROOT / "bond_portfolio" / "generate_inputs.py"
sys.path.insert(0, str(ROOT / "tools"))
from buildpaths import build_dir  # noqa: E402

STAGES = ["load", "inputs, Legs, limits", "free Bond items", "cash-flow outputs", "curve pre-flight",
          "valuation", "valuation output writing"]
BEGIN, END = "<!-- bench:begin -->", "<!-- bench:end -->"


def load_generator():
    spec = importlib.util.spec_from_file_location("generate_inputs", GENERATE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def total_ram():
    """Physical memory in bytes (Windows ``GlobalMemoryStatusEx`` or POSIX ``sysconf``), or None."""
    try:
        if sys.platform == "win32":
            import ctypes

            class MemoryStatus(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

            st = MemoryStatus()
            st.dwLength = ctypes.sizeof(st)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st)):
                return int(st.ullTotalPhys)
            return None
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    except (OSError, ValueError, AttributeError):
        return None


def cpu_name():
    if sys.platform == "win32":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as k:
                return winreg.QueryValueEx(k, "ProcessorNameString")[0].strip()
        except OSError:
            pass
    return platform.processor() or platform.machine()


def versions():
    out = {"python": sys.version.split()[0]}
    for name in ("numpy", "pandas", "modelx", "modelx_cython", "Cython"):
        try:
            mod = __import__(name)
            out[name] = getattr(mod, "__version__", "?")
        except ImportError:
            out[name] = None
    return out


def machine():
    ram = total_ram()
    return {"cpu": cpu_name(), "logical_cpus": os.cpu_count(), "ram_gb": round(ram / 2**30, 1) if ram else None,
            "platform": platform.platform()}


def run_mode(mode, inputs, out, scen=None, times=None, output_level=1, solver_errors=None):
    cmd = [sys.executable, "-B", str(RUN), "--inputs", str(inputs), "--out", str(out), "--mode", mode]
    if scen:
        cmd += ["--scen", scen]
    if times:
        cmd += ["--times", times]
    cmd += ["--output-level", str(output_level)]
    if solver_errors:
        cmd += ["--solver-errors", solver_errors]
    print(" ".join(cmd), flush=True)
    t0 = time.perf_counter()
    proc = subprocess.run(cmd, capture_output=True, text=True)
    wall = time.perf_counter() - t0
    if proc.returncode != 0:
        raise SystemExit(f"bench.py: run.py --mode {mode} failed:\n{proc.stderr}")
    tail = [line for line in proc.stdout.splitlines() if not line.startswith("wrote ")]
    print("\n".join(tail), flush=True)
    summary = json.loads((pathlib.Path(out) / "run_summary.json").read_text(encoding="utf-8"))
    summary["process_wall_seconds"] = wall
    return summary


def fmt_s(x):
    return "" if x is None else f"{x:,.2f}"


def read_build_info():
    """``<build>/build_info.json`` (written by tools/build_cy.py), or None."""
    path = build_dir() / "build_info.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def build_line(info):
    """One line on the compiled build: the modelx-cython source and the build options."""
    src = info.get("modelx_cython_src", "?")
    branch = info.get("modelx_cython_branch")
    where = f"{src}" + (f" (branch {branch}" + (", modified" if info.get("modelx_cython_modified") else "")
                        + ")" if branch else "")
    opts = []
    if info.get("compiler_directives"):
        opts.append("compiler_directives " + ", ".join(f"{k}={v!r}" for k, v in info["compiler_directives"].items()))
    if info.get("use_libm"):
        opts.append("use_libm")
    return (f"Build ({build_dir()}): modelx-cython from {where}; "
            + ("; ".join(opts) if opts else "default spec options") + ".")


def table(config, results):
    """Markdown: the configuration and one column per mode."""
    modes = list(results)
    lines = [f"Generated portfolio: {config['n_bonds']:,} bonds, {config['n_scen']} scenario(s) x "
             f"{config['n_times']} valuation dates (step {config['step']}, seed {config['seed']}); "
             f"{config['flows']:,} flows. Valued: {config['items']} (scen_id, t) item(s)"
             + (f" of {config['grid_items']} (subset; full grid extrapolated below)"
                if config["items"] < config["grid_items"] else "") + "."
             + f" Output level {config['output_level']}"
             + (f", solver errors {config['solver_errors']}" if config["solver_errors"] else "") + ".",
             "",
             f"Machine: {config['machine']['cpu']}, {config['machine']['logical_cpus']} logical CPUs, "
             f"{config['machine']['ram_gb']} GB RAM; {config['machine']['platform']}. "
             + ", ".join(f"{k} {v}" for k, v in config["versions"].items() if v) + ". "
             f"Run on {config['date']}; input generation took {config['generate_seconds']:.1f} s.",
             ""]
    if config.get("build"):
        lines += [build_line(config["build"]), ""]
    lines += ["| | " + " | ".join(modes) + " |", "|---|" + "---:|" * len(modes)]

    def row(label, values):
        lines.append(f"| {label} | " + " | ".join(values) + " |")

    for stage in STAGES:
        row(f"{stage} (s)", [fmt_s(results[m]["stages"].get(stage)) for m in modes])
    row("**total, in run.py** (s)", [f"**{fmt_s(results[m]['total_seconds'])}**" for m in modes])
    row("process wall time (s)", [fmt_s(results[m]["process_wall_seconds"]) for m in modes])
    row("seconds per (scen_id, t) item", [f"{results[m]['valuation']['seconds_per_item']:.3f}" for m in modes])
    row("**us per bond-point** (valuation)",
        [f"**{results[m]['valuation']['us_per_bond_point']:.1f}**" for m in modes])
    row("us per bond-point incl. output writing",
        [f"{results[m]['valuation']['us_per_bond_point_incl_writing']:.1f}" for m in modes])
    if config["items"] < config["grid_items"]:
        row(f"full grid ({config['grid_items']} items), valuation extrapolated (min)",
            [f"{results[m]['valuation']['seconds_per_item'] * config['grid_items'] / 60:.1f}" for m in modes])
    row("RSS after Legs (MB)", [f"{results[m]['rss_after_stage']['inputs, Legs, limits'] / 2**20:,.0f}"
                                for m in modes])
    row("**peak RSS** (MB)", [f"**{results[m]['memory']['peak'] / 2**20:,.0f}**" for m in modes])
    return "\n".join(lines)


def update_doc(path, text):
    path = pathlib.Path(path)
    doc = path.read_text(encoding="utf-8")
    pattern = re.compile(re.escape(BEGIN) + ".*?" + re.escape(END), re.S)
    if not pattern.search(doc):
        raise SystemExit(f"bench.py: {path} has no {BEGIN} ... {END} block")
    path.write_text(pattern.sub(lambda _: BEGIN + "\n" + text + "\n" + END, doc), encoding="utf-8")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--n-bonds", type=int, default=10000)
    ap.add_argument("--n-scen", type=int, default=2)
    ap.add_argument("--n-times", type=int, default=121)
    ap.add_argument("--step", default="1M")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--modes", default="export,compiled")
    ap.add_argument("--scen", help="scenario ids to value (run.py --scen)")
    ap.add_argument("--times", help="valuation-date indices to value (run.py --times)")
    ap.add_argument("--output-level", type=int, choices=(1, 2, 3), default=1, help="run.py --output-level")
    ap.add_argument("--solver-errors", choices=("raise", "nan"), help="run.py --solver-errors")
    ap.add_argument("--work", help="work directory (kept); default: a temporary directory, deleted")
    ap.add_argument("--keep", action="store_true", help="keep the temporary work directory")
    ap.add_argument("--doc", help="Markdown file whose bench block is replaced with the results")
    args = ap.parse_args(argv)
    modes = [m.strip() for m in args.modes.split(",") if m.strip()]

    sizes_path = build_dir() / "sizes.json"
    if any(m != "modelx" for m in modes) and not sizes_path.exists():
        raise SystemExit(f"bench.py: {sizes_path} not found; build with tools/build_cy.py first")

    work = pathlib.Path(args.work) if args.work else pathlib.Path(tempfile.mkdtemp(prefix="bp_bench_"))
    work.mkdir(parents=True, exist_ok=True)
    try:
        gen = load_generator()
        t0 = time.perf_counter()
        tables = gen.generate(args.n_bonds, args.n_scen, args.n_times, args.seed, step=args.step)
        gen.write_tables(work / "inputs", tables)
        gen_s = time.perf_counter() - t0
        print(f"generated {args.n_bonds} bonds x {args.n_scen} scenario(s) x {args.n_times} dates "
              f"into {work / 'inputs'} in {gen_s:.1f}s", flush=True)

        results = {}
        for mode in modes:
            results[mode] = run_mode(mode, work / "inputs", work / f"out_{mode}", args.scen, args.times,
                                     args.output_level, args.solver_errors)

        files = sorted(p.name for p in (work / f"out_{modes[0]}").glob("*.csv"))
        hashes = {mode: {f: sha256(work / f"out_{mode}" / f) for f in files} for mode in modes}
        identical = all(hashes[m] == hashes[modes[0]] for m in modes)
        print(f"CSV outputs byte-identical across {', '.join(modes)}: {identical}", flush=True)

        first = results[modes[0]]
        config = {"n_bonds": args.n_bonds, "n_scen": args.n_scen, "n_times": args.n_times, "step": args.step,
                  "seed": args.seed, "flows": first["counts"]["flows"], "items": first["counts"]["items"],
                  "grid_items": args.n_scen * args.n_times, "generate_seconds": gen_s,
                  "output_level": args.output_level, "solver_errors": args.solver_errors,
                  "date": datetime.date.today().isoformat(), "machine": machine(), "versions": versions(),
                  "build": read_build_info() if any(m != "modelx" for m in modes) else None,
                  "outputs_identical": identical, "output_bytes": {
                      mode: sum((work / f"out_{mode}" / f).stat().st_size for f in files) for mode in modes}}
        text = table(config, results)
        text += f"\n\nCSV outputs byte-identical across the modes: {'yes' if identical else 'NO'} " \
                f"({len(files)} files, {config['output_bytes'][modes[0]] / 2**20:,.0f} MB per mode)."
        print()
        print(text)
        (work / "bench.json").write_text(json.dumps({"config": config, "results": results, "hashes": hashes},
                                                    indent=1), encoding="utf-8")
        if args.doc:
            update_doc(args.doc, text)
            print(f"updated {args.doc}")
        if not identical:
            return 1
    finally:
        if not (args.work or args.keep):
            shutil.rmtree(work, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
