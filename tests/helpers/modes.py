"""The three execution modes of BondPortfolio, and bitwise comparison.

* **modelx**: ``mx.read_model`` of ``bond_portfolio/BondPortfolio``.
* **export**: the pure-Python package from ``mx.export_model``. Tests export
  into ``tmp_path`` under a unique package name, so several exports can live
  in one process.
* **compiled**: ``build/BondPortfolio_nomx_cy`` from ``tools/build_cy.py``.

Exported and compiled models never invalidate caches: set ``Data.input_dir``
on a FRESH instance before the first calculation.
"""

import importlib
import itertools
import math
import pathlib
import struct
import sys

import numpy as np

from helpers.model import MODEL_DIR

ROOT = MODEL_DIR.parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from buildpaths import build_dir  # noqa: E402

BUILD = build_dir()
_counter = itertools.count()


def export_package(tmp_dir):
    """Export the model into ``tmp_dir`` under a unique name; return the package module."""
    import modelx as mx
    name = f"BondPortfolio_nomx_t{next(_counter)}"
    m = mx.read_model(MODEL_DIR, name="BondPortfolio")
    try:
        mx.export_model(m, pathlib.Path(tmp_dir) / name)
    finally:
        m.close()
    if str(tmp_dir) not in sys.path:
        sys.path.insert(0, str(tmp_dir))
    return importlib.import_module(name)


def compiled_package():
    """The compiled package from build/, or None if it has not been built."""
    if not (BUILD / "BondPortfolio_nomx_cy").exists():
        return None
    if str(BUILD) not in sys.path:
        sys.path.insert(0, str(BUILD))
    return importlib.import_module("BondPortfolio_nomx_cy")


def new_instance(package, input_dir):
    """A fresh model instance of an exported or compiled package, pointed at ``input_dir``."""
    m = package._mx_model._c_BondPortfolio()
    m.Data.input_dir = str(input_dir)
    return m


def bits(x):
    """A hashable bit pattern of a scalar; every NaN maps to one pattern."""
    if isinstance(x, (bool, np.bool_)):
        return ("b", bool(x))
    if isinstance(x, (int, np.integer)):
        return ("i", int(x))
    if isinstance(x, (float, np.floating)):
        x = float(x)
        return ("f", "nan") if math.isnan(x) else ("f", struct.pack("<d", x))
    if isinstance(x, str):
        return ("s", x)
    if isinstance(x, (tuple, list)):
        return ("t", tuple(bits(v) for v in x))
    if isinstance(x, np.ndarray) or hasattr(x, "__array__") and not hasattr(x, "columns"):
        a = np.asarray(x)
        return ("a", a.dtype.kind, a.shape, tuple(bits(v) for v in a.ravel().tolist()))
    if isinstance(x, dict):
        return ("d", tuple((k, bits(v)) for k, v in sorted(x.items())))
    if hasattr(x, "columns") and hasattr(x, "to_dict"):  # a DataFrame
        return ("df", tuple(x.columns), tuple((c, bits(x[c].tolist())) for c in x.columns))
    try:  # a Cython typed memoryview (buffer protocol)
        memoryview(x)
    except TypeError:
        raise TypeError(f"no bit pattern for {type(x)}") from None
    return bits(np.asarray(x))


def same_bits(a, b):
    return bits(a) == bits(b)
