"""Export the model and compile it with modelx-cython.

    python tools/build_cy.py [--translate-only] [--skip-export]
                             [--directive NAME=VALUE ...] [--use-libm]

Steps:

1. ``mx.export_model`` → ``build/BondPortfolio_nomx`` (pure Python, no modelx).
2. ``build/spec.py`` from the model-level ``MAX_*`` References through the
   static map :data:`SPEC_MAP` (one entry per integer-parameter tuple per Space),
   plus the optional model-wide keys below.
3. ``mx2cy build/BondPortfolio_nomx --sample tools/cy/sample.py --spec build/spec.py``
   → ``build/BondPortfolio_nomx_cy`` (compiled in place).
4. :func:`audit_pxd` checks that every Cells, cached or uncached, came out
   with C types for its return and parameters, except those listed in
   :data:`OBJECT_CELLS` and :data:`UNCACHED_OBJECT_CELLS` (an ``object`` type
   elsewhere is a silent demotion, e.g. from a float/np.float64 mix in the
   sample, or a Cells the sample does not reach), and writes
   ``build/sizes.json`` for the drivers and ``build/build_info.json`` (the
   modelx-cython source and the options below) for ``tools/bench.py``.

Options (all off by default; the default build is the one the tests and the
drivers use). They need a modelx-cython that knows the spec keys
``compiler_directives`` and ``use_libm`` (branch
``bondportfolio/mx2cy-improvements``; select it with ``MODELX_CYTHON_SRC``):

``--directive NAME=VALUE`` (repeatable)
    A Cython compiler directive for the generated ``setup.py`` (spec key
    ``compiler_directives``), e.g. ``--directive infer_types=True``. VALUE is a
    Python literal (``True``, ``False``, ``None``, a number) or else a string.
    Also from the environment: ``BONDPORTFOLIO_CY_DIRECTIVES="infer_types=True,..."``.
``--use-libm``
    Compile ``math.exp/log/pow`` on C doubles to the C library calls (spec key
    ``use_libm``). Also from the environment: ``BONDPORTFOLIO_CY_LIBM=1``.

Either option changes the compiled code: gate the build with
``pytest -m compiled`` (``compiled == export``, bitwise) before using it.
``BONDPORTFOLIO_BUILD`` (tools/buildpaths.py) builds into another directory.
"""

import ast
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / "bond_portfolio" / "BondPortfolio"
sys.path.insert(0, str(ROOT / "tools"))
from buildpaths import build_dir, EXPORT_NAME  # noqa: E402

BUILD = build_dir()
SAMPLE = ROOT / "tools" / "cy" / "sample.py"

# Space -> {integer-parameter tuple: model Reference names giving the sizes}.
# A size of n admits arguments in range(n). tests/lint checks completeness
# against the generated .pxd files.
SPEC_MAP = {
    "Dates": {
        ("d",): ("MAX_SERIAL+1",),
        ("yr",): ("2201",),
        ("m", "leap"): ("14", "2"),
        ("w",): ("8",),
        ("cal", "d"): ("CAL_MAX", "MAX_SERIAL+1"),
    },
    "Proj": {
        ("per",): ("MAX_T+1",),
    },
    "Valuation": {
        ("b",): ("MAX_BONDS",),
        ("b", "role"): ("MAX_BONDS", "3"),
        ("b", "kind"): ("MAX_BONDS", "2"),
        ("kd",): ("MAX_KD",),
        ("nd",): ("MAX_NODES",),
        ("p",): ("MAX_FLOWS",),
        ("cal", "nsd"): ("CAL_MAX", "MAX_SETTLE_DAYS+1"),
    },
}

# Cached Cells that legitimately return Python objects (DataFrames, tuples,
# dicts, lists). Every OTHER cached Cells must come out of mx2cy with C types
# for its return and its parameters; audit_pxd() fails the build otherwise (a
# silent demotion, e.g. from a float/np.float64 mix in the sample trace).
OBJECT_CELLS = {
    "Data": {
        "bond_table", "coupon_rate_table", "val_date_table", "curve_param_table",
        "curve_node_table", "spread_table", "price_table", "yield_table", "bond_keys",
        "spread_ids", "bond_columns", "curve_columns", "node_columns", "quote_columns", "table_errors",
        "bond_errors", "val_date_errors", "curve_errors", "node_errors", "spread_errors",
        "quote_errors",
    },
    "Bond": {
        "coupon_rates", "schedule", "coupons", "coupon_amounts", "accrual_periods",
        "notional_schedule", "redemption_flows", "leg", "cashflow_table",
    },
    "Legs": {"leg_columns", "cashflow_frame", "iso_column"},
    "Proj": {"bond_cf_table", "period_table"},
    "Valuation": {"result_frame"},
}

# Uncached Cells that may stay ``object`` in the generated .pxd, with the
# reason. mx2cy types an uncached Cells from the calls the sample run makes to
# it, directly or nested in other Cells (tools/cy/sample.py); one it never sees
# keeps ``object`` parameters and return. Every OTHER uncached Cells must come
# out with C types (or ``str``), like the cached ones.
UNCACHED_OBJECT_CELLS = {
    "Data": {
        "read_table": "returns a DataFrame (reads one input CSV file)",
    },
    "Lib": {
        "long_date": "returns str; formats dates in error messages only",
        "cxx_lround": "not called by the model",
        "cxx_idiv": "not called by the model",
        "cxx_irem": "not called by the model",
        "implied_rate_dates": "not called by the model",
        "equivalent_rate_dates": "not called by the model",
    },
    "Dates": {
        "daycounter_name": "returns str; names a day counter in error messages only",
    },
}

SPACES = ["Data", "Lib", "Dates", "Bond", "Legs", "Proj", "Valuation"]


def cells_of(space):
    """[(name, cached)] of the Cells of a Space, read from the model source."""
    tree = ast.parse((MODEL_DIR / space / "__init__.py").read_text(encoding="utf-8"))
    names, prev = [], None
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            names.append([node.name, True])
        elif (isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)
              and node.targets[0].id == "_is_cached" and isinstance(prev, ast.FunctionDef)):
            names[-1][1] = False
        prev = node
    return [tuple(n) for n in names]


def cached_cells(space):
    """Names of the cached Cells of a Space, read from the model source."""
    return [n for n, cached in cells_of(space) if cached]


def uncached_cells(space):
    """Names of the uncached Cells of a Space, read from the model source."""
    return [n for n, cached in cells_of(space) if not cached]


def model_refs():
    import modelx as mx
    m = mx.read_model(MODEL_DIR, name="BondPortfolio_build")
    try:
        refs = {k: v for k, v in m.refs.items() if isinstance(v, int) and not isinstance(v, bool)}
    finally:
        m.close()
    return refs


def size_of(expr, refs):
    total = 0
    for term in expr.split("+"):
        term = term.strip()
        total += int(term) if term.isdigit() else refs[term]
    return total


def make_spec(refs, directives=None, use_libm=False):
    """The mx2cy spec: the array sizes from :data:`SPEC_MAP`, plus the model-wide options if set."""
    spaces = {}
    for space, tuples in SPEC_MAP.items():
        sizes = {}
        for params, exprs in tuples.items():
            vals = tuple(size_of(e, refs) for e in exprs)
            if len(params) == 1:
                sizes[params[0]] = vals[0]
            else:
                sizes[params] = vals
        spaces[space] = {"cells_param_size": sizes}
    spec = {"spaces": spaces}
    if directives:
        spec["compiler_directives"] = dict(directives)
    if use_libm:
        spec["use_libm"] = True
    return spec


def parse_directive(text):
    """``"NAME=VALUE"`` -> (NAME, value); VALUE is a Python literal, or else the string itself."""
    name, sep, value = text.partition("=")
    name = name.strip()
    if not sep or not name.isidentifier():
        raise SystemExit(f"build_cy.py: a directive is NAME=VALUE, got {text!r}")
    value = value.strip()
    try:
        return name, ast.literal_eval(value)
    except (ValueError, SyntaxError):
        return name, value


def parse_args(argv):
    """The command-line options, with the environment defaults (see the module docstring)."""
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--translate-only", action="store_true", help="mx2cy --translate-only (no C compile)")
    ap.add_argument("--skip-export", action="store_true", help="reuse the existing export")
    ap.add_argument("--directive", action="append", default=[], metavar="NAME=VALUE",
                    help="Cython compiler directive (spec key compiler_directives); repeatable")
    ap.add_argument("--use-libm", action="store_true", help="spec key use_libm")
    args = ap.parse_args(argv)
    env_dirs = os.environ.get("BONDPORTFOLIO_CY_DIRECTIVES", "")
    texts = [t for t in env_dirs.split(",") if t.strip()] + args.directive
    args.directives = dict(parse_directive(t) for t in texts)
    args.use_libm = args.use_libm or os.environ.get("BONDPORTFOLIO_CY_LIBM", "") not in ("", "0")
    return args


def remove_tree(path, attempts=10):
    """``shutil.rmtree`` that tolerates Windows/OneDrive holding a directory handle.

    Files are removed; if the (now empty) directory itself cannot be removed
    after a few attempts it is left in place, and the export writes into it.
    """
    import time
    for i in range(attempts):
        try:
            shutil.rmtree(path)
            return
        except FileNotFoundError:
            return
        except PermissionError:
            if not any(p.is_file() for p in path.rglob("*")):
                if i == attempts - 1:
                    print(f"note: could not remove empty directory {path}; exporting into it")
                    return
            time.sleep(0.5)
    raise PermissionError(f"could not remove {path}")


def export():
    import modelx as mx
    target = BUILD / EXPORT_NAME
    if target.exists():
        remove_tree(target)
    BUILD.mkdir(exist_ok=True)
    m = mx.read_model(MODEL_DIR, name="BondPortfolio")
    try:
        mx.export_model(m, target)
    finally:
        m.close()
    return target


def run_mx2cy(translate_only=False):
    cmd = [sys.executable, "-m", "modelx_cython", EXPORT_NAME,
           "--sample", str(SAMPLE), "--spec", "spec.py", "--setup", "setup.py",
           "--log-level", "INFO"]
    if translate_only:
        cmd.append("--translate-only")
    env = dict(os.environ)
    src = os.environ.get("MODELX_CYTHON_SRC")
    if src:
        # Use a modelx-cython checkout other than the installed one (e.g. a
        # development worktree): it goes first on the subprocess's sys.path.
        env["PYTHONPATH"] = src + os.pathsep + env.get("PYTHONPATH", "")
        print("modelx-cython from", src)
    print(" ".join(cmd))
    return subprocess.run(cmd, cwd=BUILD, env=env).returncode


def pxd_class_blocks():
    """{Space name: text of its ``cdef class _c_<Space>`` block} over all generated .pxd files."""
    cy = BUILD / (EXPORT_NAME + "_cy")
    blocks = {}
    for pxd in cy.rglob("*.pxd"):
        text = pxd.read_text(encoding="utf-8")
        parts = re.split(r"^cdef class _c_(\w+)\(", text, flags=re.M)
        for name, body in zip(parts[1::2], parts[2::2]):
            blocks[name] = body
    return blocks


def cpdef_signature(block, name):
    """(return type, parameter text) of ``cpdef <ret> <name>(...)`` in a class block, or None."""
    m = re.search(rf"^\s*cpdef\s+(.+?)\s+{name}\s*\(([^)]*)\)", block, flags=re.M)
    return (m.group(1).strip(), m.group(2)) if m else None


def has_object(sig):
    """Whether a ``(return type, parameter text)`` signature has an ``object`` return or parameter."""
    ret, params = sig
    return ret == "object" or re.search(r"\bobject\s+\w", params) is not None


def audit_pxd():
    """(problems, notes) about the C types of the Cells in the generated .pxd.

    Every Cells, cached or uncached, must come out without an ``object``
    return or parameter, unless :data:`OBJECT_CELLS` (cached) or
    :data:`UNCACHED_OBJECT_CELLS` (uncached) lists it. A listed Cells that
    does not exist, or that is listed for the other kind, is a problem too (a
    stale list); a listed uncached Cells that came out with C types after all
    is reported as a note, so that the list can be shortened.
    """
    problems, notes = [], []
    uncached_problems, uncached_typed = [], 0
    blocks = pxd_class_blocks()
    for space in SPACES:
        block = blocks.get(space, "")
        cells = dict(cells_of(space))
        for kind, table in (("cached", OBJECT_CELLS), ("uncached", UNCACHED_OBJECT_CELLS)):
            for name in table.get(space, ()):
                if name not in cells:
                    problems.append(f"{space}.{name}: listed in the {kind} exceptions but not a Cells")
                elif cells[name] != (kind == "cached"):
                    problems.append(f"{space}.{name}: listed in the {kind} exceptions but is not {kind}")
        for name, cached in cells.items():
            allowed = OBJECT_CELLS if cached else UNCACHED_OBJECT_CELLS
            listed = name in allowed.get(space, ())
            sig = cpdef_signature(block, name)
            if sig is None:
                problems.append(f"{space}.{name}: no cpdef in the generated .pxd")
                continue
            ret, params = sig
            if has_object(sig):
                if not listed:
                    if cached:
                        problems.append(f"{space}.{name}: Cells typed '{ret} {name}({params})'")
                    else:
                        uncached_problems.append(
                            f"{space}.{name}: uncached Cells typed '{ret} {name}({params})'")
            elif not cached:
                uncached_typed += 1
                if listed:
                    notes.append(f"{space}.{name}: listed in UNCACHED_OBJECT_CELLS but typed "
                                 f"'{ret} {name}({params})'")
    if uncached_problems and uncached_typed == 0:
        # A modelx-cython that does not type uncached Cells at all (released
        # versions up to 0.1.0; mx2cy-issues.md #1): the build is correct, only
        # slower, so this is a note rather than a failure.
        notes.append(f"the modelx-cython in use leaves all {len(uncached_problems)} uncached Cells "
                     "untyped (docs/mx2cy-issues.md #1); the uncached-Cells audit is skipped")
    else:
        problems.extend(uncached_problems)
    return problems, notes


def build_info(args):
    """What ``tools/bench.py`` reports about the build: the modelx-cython source and the options."""
    import modelx_cython  # the installed one; MODELX_CYTHON_SRC, if set, replaces it in the mx2cy run
    src = os.environ.get("MODELX_CYTHON_SRC")
    info = {"modelx_cython_src": src or str(pathlib.Path(modelx_cython.__file__).resolve().parents[1]),
            "compiler_directives": args.directives, "use_libm": args.use_libm}
    try:
        repo = src or info["modelx_cython_src"]
        head = subprocess.run(["git", "-C", repo, "rev-parse", "--abbrev-ref", "HEAD"],
                              capture_output=True, text=True, timeout=30)
        if head.returncode == 0:
            info["modelx_cython_branch"] = head.stdout.strip()
        dirty = subprocess.run(["git", "-C", repo, "status", "--porcelain", "--untracked-files=no"],
                               capture_output=True, text=True, timeout=30)
        if dirty.returncode == 0:
            info["modelx_cython_modified"] = bool(dirty.stdout.strip())
    except (OSError, subprocess.SubprocessError):
        pass
    return info


def main(argv):
    args = parse_args(argv[1:])
    if not args.skip_export:
        print("exported to", export())
    refs = model_refs()
    spec = make_spec(refs, args.directives, args.use_libm)
    (BUILD / "spec.py").write_text(repr(spec), encoding="utf-8")
    print("wrote", BUILD / "spec.py")
    if args.directives or args.use_libm:
        print("model-wide spec options:", {k: v for k, v in spec.items() if k != "spaces"})
    info = build_info(args)
    # Removed first: a failed build must not leave the options of an earlier one behind.
    (BUILD / "build_info.json").unlink(missing_ok=True)
    rc = run_mx2cy(args.translate_only)
    if rc != 0:
        raise SystemExit(f"mx2cy failed with exit status {rc}")
    problems, notes = audit_pxd()
    sizes = {k: refs[k] for k in refs if k.startswith("MAX_") or k == "CAL_MAX"}
    (BUILD / "sizes.json").write_text(json.dumps(sizes, indent=1), encoding="utf-8")
    (BUILD / "build_info.json").write_text(json.dumps(info, indent=1), encoding="utf-8")
    for note in notes:
        print("pxd audit note:", note)
    if problems:
        print("PXD AUDIT FAILED:\n  " + "\n  ".join(problems))
        raise SystemExit(1)
    print("pxd audit: OK")


if __name__ == "__main__":
    main(sys.argv)
