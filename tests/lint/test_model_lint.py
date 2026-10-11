"""L0 static checks of the model source (docs/model-contract.md sections 1 and 3).

The model is read as text and parsed with ``ast``; nothing is calculated.
"""

import ast
import pathlib
import re

import pytest

from helpers.model import MODEL_DIR

ROOT = MODEL_DIR.parents[1]
PQ = ROOT.parent / "quantlib-migration" / "src" / "pureql"

SERIALIZER_NAMES = {"_formula", "_bases", "_allow_none", "_spaces", "_is_cached", "_name"}
PROVENANCE_RE = re.compile(
    # The anchor may itself contain parentheses ("date.cpp:912-924 (io::long_date ...)"),
    # so it runs greedily up to the closing "), QuantLib v1.43".
    r"#\s*ported from pureql/(?P<path>[\w/]+\.py) \((?P<anchor>port rider|ql/.+)\), "
    r"QuantLib v1\.43, BSD-3-Clause\s*$")
DERIVED_DOC_LINE = "Derived from QuantLib (BSD-3-Clause); see NOTICE.md."
FORBIDDEN_CALLS = {"sum", "round"}
FORBIDDEN_ATTR_CALLS = {"fsum", "sum"}


def space_files():
    return sorted(p for p in MODEL_DIR.glob("*/__init__.py"))


class SpaceSource:
    """Cells, References and parameters of one serialized Space file."""

    def __init__(self, path: pathlib.Path):
        self.path = path
        self.name = path.parent.name
        self.text = path.read_text(encoding="utf-8")
        self.tree = ast.parse(self.text)
        self.lines = self.text.splitlines()
        self.cells = {}
        self.refs = set()
        self.params = []
        self.uncached = set()
        prev = None
        for node in self.tree.body:
            if isinstance(node, ast.FunctionDef):
                self.cells[node.name] = node
            elif isinstance(node, ast.Assign) and len(node.targets) == 1 \
                    and isinstance(node.targets[0], ast.Name):
                target = node.targets[0].id
                if target == "_formula" and isinstance(node.value, ast.Lambda):
                    self.params = [a.arg for a in node.value.args.args]
                elif target == "_is_cached" and isinstance(prev, ast.FunctionDef):
                    self.uncached.add(prev.name)
                elif target not in SERIALIZER_NAMES:
                    self.refs.add(target)
            prev = node

    def body_comments(self, fn):
        """Comment lines inside a function's body."""
        return [line.strip() for line in self.lines[fn.lineno - 1:fn.end_lineno]
                if line.strip().startswith("#")]


SPACES = [SpaceSource(p) for p in space_files()]
ROOT_SRC = SpaceSource(MODEL_DIR / "__init__.py")
SPACE_NAMES = {s.name for s in SPACES}
ALL_CELLS = {name for s in SPACES for name in s.cells}
MODEL_REFS = ROOT_SRC.refs


def test_model_has_the_seven_spaces():
    assert SPACE_NAMES == {"Data", "Lib", "Dates", "Bond", "Legs", "Proj", "Valuation"}


@pytest.mark.parametrize("src", SPACES + [ROOT_SRC], ids=lambda s: s.name)
def test_no_pureql_or_quantlib_import(src):
    for node in ast.walk(src.tree):
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [node.module or ""]
        else:
            continue
        for n in names:
            assert not n.split(".")[0].lower() in ("pureql", "quantlib"), \
                f"{src.name}: imports {n} (D-11: the model never imports pureql or QuantLib)"
    assert '("Module", "QuantLib")' not in src.text and '("Module", "pureql")' not in src.text


@pytest.mark.parametrize("src", SPACES, ids=lambda s: s.name)
def test_names(src):
    for name in list(src.cells) + list(src.refs):
        assert not name.startswith("_"), f"{src.name}.{name}: names must not start with '_'"
    for name in src.cells:
        assert name not in src.refs, f"{src.name}.{name}: a Cells named like a Reference"
        assert name not in MODEL_REFS, f"{src.name}.{name}: a Cells named like a model Reference"
        assert name not in src.params, f"{src.name}.{name}: a Cells named like a Space parameter"
        assert name not in SPACE_NAMES, f"{src.name}.{name}: a Cells named like a Space"


@pytest.mark.parametrize("src", SPACES, ids=lambda s: s.name)
def test_forbidden_constructs(src):
    for fn in src.cells.values():
        where = f"{src.name}.{fn.name}"
        for node in ast.walk(fn):
            if isinstance(node, (ast.BinOp, ast.AugAssign)) and isinstance(node.op, ast.Pow):
                pytest.fail(f"{where}: '**' is forbidden (use math.pow with the cxx_pow fallback)")
            if isinstance(node, ast.Match):
                pytest.fail(f"{where}: 'match' is forbidden (use if/elif)")
            if isinstance(node, (ast.Yield, ast.YieldFrom)):
                pytest.fail(f"{where}: 'yield' is forbidden")
            if isinstance(node, ast.Call):
                f = node.func
                if isinstance(f, ast.Name) and f.id in FORBIDDEN_CALLS:
                    pytest.fail(f"{where}: {f.id}() is forbidden (sequential += only)")
                if isinstance(f, ast.Attribute) and f.attr in FORBIDDEN_ATTR_CALLS:
                    pytest.fail(f"{where}: .{f.attr}() is forbidden (sequential += only)")
                callee = f.id if isinstance(f, ast.Name) else (f.attr if isinstance(f, ast.Attribute) else None)
                if callee in ALL_CELLS and node.keywords:
                    pytest.fail(f"{where}: keyword-argument call to Cells {callee}()")


@pytest.mark.parametrize("src", SPACES, ids=lambda s: s.name)
def test_array_cells_are_used_element_wise_only(src):
    """A call to an ``*_arr()`` Cells must be the value of a full subscript."""
    for fn in src.cells.values():
        parents = {}
        for node in ast.walk(fn):
            for child in ast.iter_child_nodes(node):
                parents[child] = node
        for node in ast.walk(fn):
            if not isinstance(node, ast.Call):
                continue
            f = node.func
            name = f.id if isinstance(f, ast.Name) else (f.attr if isinstance(f, ast.Attribute) else "")
            if not name.endswith("_arr"):
                continue
            parent = parents.get(node)
            ok = isinstance(parent, ast.Subscript) and parent.value is node \
                and not isinstance(parent.slice, ast.Slice)
            assert ok, f"{src.name}.{fn.name}: {name}() used other than as X()[i] (contract rule 4)"


def _pq_anchors(path):
    text = (PQ / path).read_text(encoding="utf-8")
    return {m.group(1).strip() for m in re.finditer(r"#\s*ql:\s*(.+)$", text, re.M)}


@pytest.mark.parametrize("src", SPACES, ids=lambda s: s.name)
def test_provenance(src):
    """Every '# ported from' line is well-formed and names a real pureql anchor."""
    if not PQ.exists():
        pytest.skip("quantlib-migration checkout not found")
    for fn in src.cells.values():
        comments = [c for c in src.body_comments(fn) if c.startswith("# ported from")]
        if not comments:
            continue
        doc = ast.get_docstring(fn) or ""
        assert DERIVED_DOC_LINE in doc, f"{src.name}.{fn.name}: docstring lacks '{DERIVED_DOC_LINE}'"
        for c in comments:
            m = PROVENANCE_RE.match(c)
            assert m, f"{src.name}.{fn.name}: malformed provenance comment: {c}"
            path = m.group("path")
            assert (PQ / path).exists(), f"{src.name}.{fn.name}: no pureql file {path}"
            anchor = m.group("anchor")
            if anchor == "port rider":
                continue
            anchor = anchor[len("ql/"):]
            assert anchor in _pq_anchors(path), \
                f"{src.name}.{fn.name}: '# ql: {anchor}' not found in pureql/{path}"


DERIVED_SPACES = {"Lib", "Dates", "Bond", "Legs", "Proj", "Valuation"}


@pytest.mark.parametrize("src", [s for s in SPACES if s.name in DERIVED_SPACES], ids=lambda s: s.name)
def test_derived_space_docstring(src):
    doc = ast.get_docstring(src.tree) or ""
    assert DERIVED_DOC_LINE in doc


@pytest.mark.parametrize("src", SPACES + [ROOT_SRC], ids=lambda s: s.name)
def test_every_cells_has_a_docstring(src):
    for fn in src.cells.values():
        assert ast.get_docstring(fn), f"{src.name}.{fn.name}: missing docstring"


# Words the Cython parser reserves: as a parameter, local or Cells name they break
# the .pxd/.pyx that modelx-cython generates (e.g. 'include' -> "Expected ')'").
CYTHON_RESERVED = {
    "include", "cimport", "cdef", "cpdef", "ctypedef", "by", "sizeof", "NULL", "struct",
    "union", "enum", "packed", "public", "api", "readonly", "extern", "inline", "nogil",
    "gil", "noexcept", "const", "volatile", "signed", "unsigned", "long", "short", "char",
    "double", "bint", "void", "fused", "new", "operator", "namespace", "cppclass", "typeof",
    "DEF", "IF", "ELIF", "ELSE", "int", "float", "object",
}


@pytest.mark.parametrize("src", SPACES, ids=lambda s: s.name)
def test_no_cython_reserved_names(src):
    for fn in src.cells.values():
        names = {fn.name} | {a.arg for a in fn.args.args}
        for node in ast.walk(fn):
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
                names.add(node.id)
            elif isinstance(node, ast.arg):
                names.add(node.arg)
        bad = names & CYTHON_RESERVED
        assert not bad, f"{src.name}.{fn.name}: Cython-reserved name(s) {sorted(bad)}"
