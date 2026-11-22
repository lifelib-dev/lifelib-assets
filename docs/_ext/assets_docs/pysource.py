"""Pages for Python files that are documented without importing them.

The test modules import pureql and QuantLib, and the scripts run when
imported, so these files are parsed with :mod:`ast`: the pages show their
docstrings, signatures, pytest fixtures and markers, the constants and class
attributes with ``#:`` doc comments, and the command-line options.
"""

import ast
import io
import re
import tokenize
from dataclasses import dataclass, field

from . import render as r

_SKIP_MARKS = {"parametrize", "usefixtures", "filterwarnings"}
_ROLE_TARGET = re.compile(
    r":(?:py:)?(?:func|data|class|meth|attr|obj|const):`(?:[^`<]*<)?~?(\.?)([\w.]+)(?:\(\))?>?`")
_ENUM_START = re.compile(r"^\(?(?:\d+|[A-Za-z]|#)[.)]\s")


@dataclass
class Func:
    name: str
    sig: str
    doc: str
    line: int
    kind: str  # "test", "fixture" or "helper"
    marks: list = field(default_factory=list)
    case_marks: list = field(default_factory=list)  # marks of some parametrized cases
    params: list = field(default_factory=list)
    fixture: dict = field(default_factory=dict)
    uses: list = field(default_factory=list)
    methods: list = field(default_factory=list)  # for classes
    attrs: list = field(default_factory=list)  # (name, value, "#:" comment, line), for classes
    is_class: bool = False


@dataclass
class Module:
    path: str  # repository-relative, posix
    modname: str
    doc: str
    funcs: list
    marks: list
    options: list
    constants: dict  # name -> line
    values: dict  # name -> source text of the value
    comments: dict  # name -> its "#:" doc comment
    digest: str  # of the source file

    @property
    def role_targets(self):
        """The objects that the module's docstrings and comments cross-reference.

        Sphinx looks a plain short name up in the referencing module only, so
        it is qualified with the module name; a ``.name`` may be any module's.
        """
        docs = [self.doc, *self.comments.values()]
        for f in self.funcs:
            docs.append(f.doc)
            docs.extend(m.doc for m in f.methods)
            docs.extend(a[2] for a in f.attrs)
        return {t if dot or "." in t else f"{self.modname}.{t}"
                for d in docs for dot, t in _ROLE_TARGET.findall(d)}

    @property
    def tests(self):
        out = []
        for f in self.funcs:
            if f.kind == "test":
                out.extend([m for m in f.methods if m.kind == "test"] if f.is_class else [f])
        return out

    @property
    def all_marks(self):
        seen = list(self.marks)
        for f in self.tests:
            seen.extend(m for m in f.marks + f.case_marks if m not in seen)
        return seen


def source_text(source):
    """The text of Python source bytes, decoded as Python does (BOM, coding line)."""
    encoding, _ = tokenize.detect_encoding(io.BytesIO(source).readline)
    return source.decode(encoding, errors="replace")


def _dotted(node):
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))


def _strings(node):
    """The strings of a string literal (comma-split) or of a list/tuple of them."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [s.strip() for s in node.value.split(",") if s.strip()]
    if isinstance(node, (ast.List, ast.Tuple)):
        return [e.value for e in node.elts
                if isinstance(e, ast.Constant) and isinstance(e.value, str)]
    return []


def _mark_of(node, defs=None):
    """(mark name, call node or None) if ``node`` is a pytest mark, else None.

    A name bound at module level (``slow = pytest.mark.slow``) is followed.
    """
    if defs and isinstance(node, ast.Name) and isinstance(defs.get(node.id), ast.expr):
        node = defs[node.id]
    call = node if isinstance(node, ast.Call) else None
    name = _dotted(call.func if call else node)
    for prefix in ("pytest.mark.", "mark."):
        if name.startswith(prefix):
            return name[len(prefix):], call
    return None


def _fixture_of(node):
    """The fixture options if ``node`` is a fixture decorator, else None."""
    call = node if isinstance(node, ast.Call) else None
    if _dotted(call.func if call else node) not in ("pytest.fixture", "fixture"):
        return None
    opts = {}
    for kw in call.keywords if call else []:
        if kw.arg in ("scope", "autouse", "name"):
            opts[kw.arg] = ast.literal_eval(kw.value) if isinstance(kw.value, ast.Constant) \
                else ast.unparse(kw.value)
        elif kw.arg == "params":
            opts["params"] = True
    return opts


def _walk(node, defs, seen):
    """``ast.walk``, also through the module-level definitions of the names met."""
    for sub in ast.walk(node):
        yield sub
        if isinstance(sub, ast.Name) and sub.id in defs and sub.id not in seen:
            seen.add(sub.id)
            yield from _walk(defs[sub.id], defs, seen)


def _case_marks(call, defs):
    """The marks that ``pytest.param(..., marks=...)`` gives to some cases of a
    parametrize call, following module-level helpers and lists of cases."""
    out, seen = [], set()
    values = list(call.args[1:]) + [k.value for k in call.keywords if k.arg == "argvalues"]
    for node in values:
        for sub in _walk(node, defs, seen):
            if isinstance(sub, ast.Call) and _dotted(sub.func) in ("pytest.param", "param"):
                for kw in sub.keywords:
                    if kw.arg == "marks":
                        for m in _walk(kw.value, defs, set()):
                            mk = _mark_of(m)
                            if mk and mk[0] not in _SKIP_MARKS and mk[0] not in out:
                                out.append(mk[0])
    return out


def _marks_of_body(body, defs):
    """The marks of a ``pytestmark = ...`` assignment in a module or class body."""
    marks = []
    for node in body:
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "pytestmark" for t in node.targets):
            values = node.value.elts if isinstance(node.value, (ast.List, ast.Tuple)) \
                else [node.value]
            for v in values:
                mk = _mark_of(v, defs)
                if mk and mk[0] not in _SKIP_MARKS and mk[0] not in marks:
                    marks.append(mk[0])
    return marks


def _doc_comment(lines, lineno):
    """The ``#:`` comment block right above line ``lineno`` (1-based), or ""."""
    doc, i = [], lineno - 2
    while i >= 0 and lines[i].lstrip().startswith("#:"):
        doc.insert(0, lines[i].lstrip()[2:].removeprefix(" "))
        i -= 1
    return "\n".join(doc).strip()


def _func(node, defs, lines):
    marks, case_marks, params, uses, fixture = [], [], [], [], None
    for deco in node.decorator_list:
        fx = _fixture_of(deco)
        if fx is not None:
            fixture = fx
            continue
        mk = _mark_of(deco, defs)
        if mk is None:
            continue
        name, call = mk
        if name == "parametrize":
            argnames = (call.args[:1] or [k.value for k in call.keywords
                                          if k.arg == "argnames"]) if call else []
            if argnames:
                params.extend(p for p in _strings(argnames[0]) if p not in params)
                case_marks.extend(m for m in _case_marks(call, defs) if m not in case_marks)
        elif name == "usefixtures" and call:
            uses.extend(a.value for a in call.args if isinstance(a, ast.Constant))
        elif name not in _SKIP_MARKS and name not in marks:
            marks.append(name)
    is_class = isinstance(node, ast.ClassDef)
    if is_class:
        marks.extend(m for m in _marks_of_body(node.body, defs) if m not in marks)
    if fixture is not None:
        kind = "fixture"
    elif node.name.startswith("Test" if is_class else "test"):
        kind = "test"
    else:
        kind = "helper"
    f = Func(
        name=node.name,
        sig="" if is_class else ast.unparse(node.args),
        doc=ast.get_docstring(node) or "",
        line=node.lineno,
        kind=kind,
        marks=marks,
        case_marks=[m for m in case_marks if m not in marks],
        params=params,
        fixture=fixture or {},
        uses=uses,
        is_class=is_class,
    )
    if is_class:
        for item in node.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                m = _func(item, defs, lines)
                if m.kind == "test" and kind != "test":
                    m.kind = "helper"  # a test* method of a helper class
                m.marks = list(dict.fromkeys(marks + m.marks))
                m.case_marks = [x for x in dict.fromkeys(case_marks + m.case_marks)
                                if x not in m.marks]
                f.methods.append(m)
            elif isinstance(item, ast.Assign) and len(item.targets) == 1 \
                    and isinstance(item.targets[0], ast.Name):
                if comment := _doc_comment(lines, item.lineno):
                    f.attrs.append((item.targets[0].id, ast.unparse(item.value),
                                    comment, item.lineno))
    return f


def _options(tree):
    """The ``add_argument`` calls of an argparse parser, in source order."""
    opts = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "add_argument"):
            continue
        flags = [a.value for a in node.args
                 if isinstance(a, ast.Constant) and isinstance(a.value, str)]
        if not flags:
            continue
        kw = {k.arg: k.value for k in node.keywords if k.arg}
        opt = {"flags": flags, "line": node.lineno}
        for key in ("help", "metavar"):
            if key in kw:
                v = kw[key]
                opt[key] = v.value if isinstance(v, ast.Constant) else ast.unparse(v)
        for key in ("default", "choices", "type", "action", "required", "nargs"):
            if key in kw:
                opt[key] = ast.unparse(kw[key])
        opts.append(opt)
    return sorted(opts, key=lambda o: o["line"])


def parse_module(path, repo_root, modname):
    """A :class:`Module` from the source file ``path``; raises SyntaxError."""
    source = path.read_bytes()
    tree = ast.parse(source, filename=str(path))
    lines = re.split(r"\r\n?|\n", source_text(source))  # the lines Python counts
    defs = {}  # module-level functions, and the values of module-level names
    for n in tree.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            defs[n.name] = n
        elif isinstance(n, ast.Assign) or isinstance(n, ast.AnnAssign) and n.value:
            for t in n.targets if isinstance(n, ast.Assign) else [n.target]:
                if isinstance(t, ast.Name):
                    defs[t.id] = n.value
    funcs = [
        _func(node, defs, lines) for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    ]
    constants, values, comments = {}, {}, {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets = [node.target]
        else:
            targets = []
        for t in targets:
            if isinstance(t, ast.Name):
                constants[t.id] = node.lineno
                values[t.id] = ast.unparse(node.value)
                if comment := _doc_comment(lines, node.lineno):
                    comments[t.id] = comment
    return Module(
        path=path.relative_to(repo_root).as_posix(),
        modname=modname,
        doc=ast.get_docstring(tree) or "",
        funcs=funcs,
        marks=_marks_of_body(tree.body, defs),
        options=_options(tree),
        constants=constants,
        values=values,
        comments=comments,
        digest=r.digest(source),
    )


def viewcode_tags(tree):
    """{name: (type, first line, last line)} of a module's definitions, as
    sphinx.ext.viewcode wants them; members are ``Class.member``."""
    tags = {}

    def add(prefix, body):
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                start = min([d.lineno for d in node.decorator_list] + [node.lineno])
                kind = "class" if isinstance(node, ast.ClassDef) else "def"
                tags[prefix + node.name] = (kind, start, node.end_lineno)
                if kind == "class":
                    add(f"{prefix}{node.name}.", node.body)
            elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for t in targets:
                    if isinstance(t, ast.Name):
                        tags.setdefault(prefix + t.id, ("other", node.lineno, node.end_lineno))

    add("", tree.body)
    return tags


# -- rendering -------------------------------------------------------------

def _marks_text(marks):
    return ", ".join(r.literal(m) for m in marks)


def _no_lone_enumerator(doc):
    """A docstring opening with a label such as ``(a)`` is a paragraph, not a one-item list."""
    paras = doc.split("\n\n", 2)
    lines = paras[0].splitlines()
    if (lines and _ENUM_START.match(lines[0])
            and not any(_ENUM_START.match(x.lstrip()) for x in lines[1:])
            and not (len(paras) > 1 and _ENUM_START.match(paras[1]))):
        return "\\" + doc
    return doc


def _data_block(directive, name, value, comment):
    block = f".. {directive}:: {name}\n"
    if "\n" not in value and len(value) <= 60:
        block += f"   :value: {value}\n"
    if comment:
        block += "\n" + r.indent(comment) + "\n"
    return block


def _func_block(f, directive="py:function", module_marks=()):
    if f.is_class:
        head = f".. py:class:: {f.name}"
    else:
        head = f".. {directive}:: {f.name}({f.sig})"
    body = _no_lone_enumerator(r.clean(f.doc))
    fields = []
    if f.kind == "fixture":
        scope = f.fixture.get("scope", "function")
        extra = []
        if f.fixture.get("autouse"):
            extra.append("autouse")
        if f.fixture.get("params"):
            extra.append("parametrized")
        if f.fixture.get("name"):
            extra.append(f"requested as {r.literal(f.fixture['name'])}")
        fields.append(f":Fixture: scope {r.literal(scope)}"
                      + (f"; {', '.join(extra)}" if extra else ""))
    marks = [m for m in f.marks if m not in module_marks]
    if marks:
        fields.append(f":Markers: {_marks_text(marks)}")
    case_marks = [m for m in f.case_marks if m not in module_marks and m not in marks]
    if case_marks:
        fields.append(f":Markers of some cases: {_marks_text(case_marks)}")
    if f.params:
        fields.append(f":Parametrized over: {', '.join(r.literal(p) for p in f.params)}")
    if f.uses:
        fields.append(f":Uses fixtures: {', '.join(r.literal(u) for u in f.uses)}")
    if fields:
        body = (body + "\n\n" if body else "") + "\n".join(fields)
    text = head + "\n"
    if body:
        text += "\n" + r.indent(body) + "\n"
    for name, value, comment, _ in f.attrs:
        text += "\n" + r.indent(_data_block("py:attribute", name, value, comment)) + "\n"
    for m in f.methods:
        text += "\n" + r.indent(_func_block(m, "py:method", module_marks + tuple(f.marks))) + "\n"
    return text


def _section(title, funcs, level, module_marks=()):
    if not funcs:
        return ""
    blocks = "\n".join(_func_block(f, module_marks=tuple(module_marks)) for f in funcs)
    return f"{'#' * level} {title}\n\n" + r.eval_rst(blocks)


def _constants_section(mod, names, level):
    blocks = [_data_block("py:data", n, mod.values[n], mod.comments.get(n))
              for n in sorted(names, key=mod.constants.get)]
    if not blocks:
        return ""
    return f"{'#' * level} Constants\n\n" + r.eval_rst("\n".join(blocks))


def module_body(mod, source_url, source_page, level, documented_helpers_only,
                referenced=frozenset()):
    """The page text of one module, its sections at heading ``level``.

    Helpers without a docstring are shown unless ``documented_helpers_only``,
    or unless the module would show nothing else. The helpers and module
    constants that docstrings cross-reference (named in ``referenced``, see
    :attr:`Module.role_targets`) are always shown, and so are the constants
    with a ``#:`` doc comment.

    The Source row links to the module's highlighted source in the docs
    (``source_page``), which sphinx.ext.viewcode writes only for a module
    with documented objects; otherwise it links to the file (``source_url``).
    """
    def is_ref(name):
        full = f"{mod.modname}.{name}"
        return any(full == t or full.endswith("." + t) for t in referenced)

    fixtures = [f for f in mod.funcs if f.kind == "fixture"]
    tests_ = [f for f in mod.funcs if f.kind == "test"]
    helpers = [f for f in mod.funcs if f.kind == "helper" and (
        is_ref(f.name) or not f.name.startswith("_")
        and (f.doc or not documented_helpers_only))]
    funcs = {f.name for f in mod.funcs}
    constants = [n for n in mod.constants if n not in funcs and n != "pytestmark"
                 and (is_ref(n) or n in mod.comments)]
    if not (fixtures or tests_ or helpers or constants):
        # nothing documented: show the public functions, undocumented as they are
        helpers = [f for f in mod.funcs if f.kind == "helper" and not f.name.startswith("_")]

    if fixtures or tests_ or helpers or constants:
        source = r.link(mod.path, source_page(mod.modname))
    else:
        source = r.link(mod.path, source_url(mod.path, None))
    facts = [("Source", source)]
    tests = mod.tests
    if tests:
        facts.append(("Tests", str(len(tests))))
    if mod.marks:
        facts.append(("Markers", _marks_text(mod.marks) + " (every test of the module)"))
    head = f".. py:module:: {mod.modname}\n\n" + r.field_table(facts)
    out = [r.eval_rst(head)]
    # A literal block (::) in these docstrings is a command or a formula, not
    # Python. The highlight directive is not in the first block: there it
    # would move the module target off the heading.
    out.append(r.eval_rst(".. highlight:: text\n\n"
                          + (r.clean(mod.doc) or "*No module docstring.*")))

    if mod.options:
        rows = []
        for o in mod.options:
            flags = ", ".join(r.literal(f) for f in o["flags"])
            if "metavar" in o:
                flags += f" {r.literal(o['metavar'])}"
            notes = []
            if o.get("required") == "True":
                notes.append("required")
            if "choices" in o:
                notes.append(f"one of {r.literal(o['choices'])}")
            if "default" in o and o["default"] not in ("None", "[]"):
                notes.append(f"default {r.literal(o['default'])}")
            if o.get("action") in ("'store_true'", "'store_false'"):
                notes.append("flag")
            elif o.get("action") == "'append'":
                notes.append("repeatable")
            rows.append([flags, o.get("help", ""), "; ".join(notes)])
        out.append(f"{'#' * level} Command-line options\n")
        out.append(r.eval_rst(r.list_table(["Option", "Help", "Notes"], rows,
                                           widths=[30, 45, 25])))

    out.append(_section("Fixtures", fixtures, level, mod.marks))
    out.append(_section("Tests", tests_, level, mod.marks))
    out.append(_section("Functions" if not tests_ and not fixtures else "Helpers",
                        helpers, level, mod.marks))
    out.append(_constants_section(mod, constants, level))
    # last, so that the module target stays at the heading
    out.append(r.source_note(mod.digest))
    return "\n".join(s for s in out if s)
