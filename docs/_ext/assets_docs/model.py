"""The model reference: one page per Space, from the model's docstrings.

The model is read with ``modelx.read_model``, so the pages show the model as
modelx sees it: the Spaces and their parameters, the Cells in definition
order with their parameters and whether they are cached, and the References.
The signatures come from the model's source files, parsed with :mod:`ast`,
and sphinx.ext.viewcode shows the files themselves, linked from every entry.
"""

import ast
import inspect

from . import render as r

INTRO = """\
This reference is generated from the docstrings of the model's Spaces and
Cells: `{model_dir}` is read with modelx {mx_version} every time the
documentation is built. Each Space has a page listing its Cells, in the order
they are defined, and its References.
"""


def _source_index(path):
    """{name: (signature, line)} of the Cells and References in a Space file."""
    index = {}
    tree = ast.parse(path.read_bytes(), filename=str(path))
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            index[node.name] = (ast.unparse(node.args), node.lineno)
        elif isinstance(node, ast.Assign) and len(node.targets) == 1 \
                and isinstance(node.targets[0], ast.Name):
            sig = ast.unparse(node.value.args) if isinstance(node.value, ast.Lambda) else None
            index[node.targets[0].id] = (sig, node.lineno)
    return index


def _is_space(value):
    return hasattr(value, "cells") and hasattr(value, "fullname")


def _value_text(value):
    """A Reference value as RST."""
    if _is_space(value):
        return f":py:mod:`~{value.fullname}` (a Space)"
    if inspect.ismodule(value):
        return f"module {r.literal(value.__name__)}"
    text = repr(value)
    if "\n" in text:  # e.g. a DataFrame
        return f"a {r.literal(type(value).__name__)}"
    if len(text) > 80:
        text = text[:77] + "..."
    return r.literal(text)


def _own_refs(space):
    impl = getattr(space, "_impl", None)
    own = getattr(impl, "own_refs", None)
    if own is not None:
        return list(own.keys())
    model_refs = set(space.model.refs)
    return [n for n in space.refs if n not in model_refs and not n.startswith("_")]


def _page_name(space, model_name):
    return space.fullname[len(model_name) + 1:]


def _space_rows(space, model_name):
    params = space.parameters
    return [
        f":py:mod:`{_page_name(space, model_name)} <{space.fullname}>`",
        ", ".join(r.literal(p) for p in params) if params else "",
        str(len(space.cells)),
        r.summary(space.doc),
    ]


class ModelDoc:
    """Builds the pages of the model reference."""

    def __init__(self, repo_root, model_dir, source_url, source_page):
        self.repo_root = repo_root
        self.model_dir = repo_root / model_dir
        self.model_rel = self.model_dir.relative_to(repo_root).as_posix()
        self.source_url = source_url  # (repo-relative path, line) -> GitHub URL or None
        self.source_page = source_page  # module name -> link to its highlighted source
        self.sources = {}  # module name -> source file, for sphinx.ext.viewcode

    def _src(self, path):
        return path.relative_to(self.repo_root).as_posix()

    def generate(self):
        """{relative page path: text}."""
        import modelx as mx

        model = mx.read_model(str(self.model_dir))
        try:
            return self._pages(model, mx.__version__)
        finally:
            model.close()

    def _pages(self, model, mx_version):
        name = model.name
        spaces = []

        def walk(space):
            spaces.append(space)
            for child in space.spaces.values():
                walk(child)

        for space in model.spaces.values():
            walk(space)

        pages = {"index.md": self._index(model, spaces, mx_version)}
        for space in spaces:
            pages[_page_name(space, name) + ".md"] = self._space_page(space, name)
        return pages

    # -- the model page ----------------------------------------------------

    def _index(self, model, spaces, mx_version):
        init = self.model_dir / "__init__.py"
        src = self._src(init)
        out = [r.generated_note([self.model_rel]), f"# {model.name} model reference\n"]
        out.append(INTRO.format(model_dir=self.model_rel, mx_version=mx_version))
        out.append(r.eval_rst(f".. py:module:: {model.name}"))
        out.append(r.eval_rst(r.clean(model.doc)))

        out.append("## Spaces\n")
        out.append(r.eval_rst(r.list_table(
            ["Space", "Parameters", "Cells", "Summary"],
            [_space_rows(s, model.name) for s in spaces],
            widths=[15, 15, 8, 62],
        )))

        refs = [(n, v) for n, v in model.refs.items() if not n.startswith("_")]
        modules = [(n, v) for n, v in refs if inspect.ismodule(v)]
        consts = [(n, v) for n, v in refs if not inspect.ismodule(v)]
        out.append("## Model References\n")
        out.append(
            "The model-level References are visible from every Space. "
            "The modules:\n"
        )
        out.append(r.eval_rst(r.list_table(
            ["Name", "Value"],
            [[r.literal(n), _value_text(v)] for n, v in modules],
            widths=[30, 70],
        )))
        out.append(
            f"The constants: codes, limits and numerical constants, in the "
            f"order of {r.md_link(src, self.source_url(src, None))}.\n"
        )
        out.append(r.eval_rst(r.list_table(
            ["Name", "Value"],
            [[r.literal(n), _value_text(v)] for n, v in consts],
            widths=[40, 60],
        )))
        out.append("```{toctree}\n:hidden:\n\n" + "\n".join(
            _page_name(s, model.name) for s in spaces) + "\n```\n")
        return "\n".join(out)

    # -- a Space page ------------------------------------------------------

    def _space_page(self, space, model_name):
        file = self.model_dir.joinpath(*_page_name(space, model_name).split(".")) / "__init__.py"
        src = self._src(file)
        index = _source_index(file)
        self.sources[space.fullname] = file

        cells = list(space.cells.values())
        uncached = [c for c in cells if not c.is_cached]
        refs = _own_refs(space)
        params = space.parameters
        page = _page_name(space, model_name)

        if params:
            item = f"{page}[{', '.join(params)}]"
            params_text = (", ".join(r.literal(p) for p in params)
                           + f": the items are {r.literal(item)}")
        else:
            params_text = "none: a single Space"
        facts = [
            ("Full name", r.literal(space.fullname)),
            ("Parameters", params_text),
            ("Cells", f"{len(cells)} ({len(uncached)} not cached)"),
            ("References", ", ".join(r.literal(n) for n in refs) or "none"),
            ("Source", r.link(src, self.source_page(space.fullname))),
        ]
        if space.spaces:
            facts.insert(3, ("Spaces", ", ".join(
                f":py:mod:`~{s.fullname}`" for s in space.spaces.values())))

        title = f"{page}[{', '.join(params)}]" if params else page
        out = [r.generated_note([src]), r.source_note(r.digest(file.read_bytes())),
               f"# {title}\n"]
        out.append(r.eval_rst(f".. py:module:: {space.fullname}\n\n" + r.field_table(facts)))
        if space.doc:
            out.append(r.eval_rst(r.clean(space.doc)))

        out.append("## Cells\n")
        rows = []
        for c in cells:
            sig = index.get(c.name, (None, None))[0]
            sig = sig if sig is not None else ", ".join(c.parameters)
            rows.append([
                f":py:func:`{c.name}`",
                r.literal(sig) if sig else "",
                "" if c.is_cached else "no",
                r.summary(c.doc),
            ])
        out.append(r.eval_rst(r.list_table(
            ["Cells", "Parameters", "Cached", "Summary"], rows, widths=[22, 20, 8, 50])))

        out.append("## Cells details\n")
        blocks = []
        for c in cells:
            sig = index.get(c.name, (None, None))[0]
            sig = sig if sig is not None else ", ".join(c.parameters)
            body = r.clean(c.doc) or "*No docstring.*"
            if not c.is_cached:
                body += "\n\n:Cached: no (the formula runs on every call)"
            blocks.append(f".. py:function:: {c.name}({sig})\n\n{r.indent(body)}\n")
        out.append(r.eval_rst("\n".join(blocks)))

        if refs:
            out.append("## References\n")
            blocks = []
            for n in refs:
                value = space.refs[n]
                if _is_space(value):
                    blocks.append(f".. py:data:: {n}\n\n   Interface to the "
                                  f":py:mod:`~{value.fullname}` Space.\n")
                elif inspect.ismodule(value):
                    blocks.append(f".. py:data:: {n}\n\n   The module "
                                  f"{r.literal(value.__name__)}.\n")
                else:
                    text = repr(value)
                    if "\n" in text or len(text) > 80:  # e.g. a DataFrame
                        blocks.append(f".. py:data:: {n}\n\n   A {r.literal(type(value).__name__)}.\n")
                    else:
                        blocks.append(f".. py:data:: {n}\n   :value: {text}\n")
            out.append(r.eval_rst("\n".join(blocks)))
        return "\n".join(out)
