"""The pages of the test suite, the scripts and the demo input files."""

import csv
import re
import tomllib

from . import pysource as ps
from . import render as r

TESTS_INTRO = """\
The tests live in `tests/`, one directory per area. This section is generated
from the docstrings of the test modules, which are parsed, not imported. Each
directory has a page; there every module shows its docstring and then its
fixtures, tests and helpers, with their pytest markers and parameters.
"""


def _module_order(path):
    name = path.name
    return (name != "conftest.py", name.startswith("test_"), name)


def _modname(path, root):
    rel = path.relative_to(root).with_suffix("")
    parts = rel.parts[:-1] if rel.name == "__init__" else rel.parts
    return ".".join(parts)


def _n(n, word):
    return f"{n} {word}{'' if n == 1 else 's'}"


def _parse(path, repo_root, modname, logger):
    """The parsed module, or None (with a warning) if it does not parse."""
    try:
        return ps.parse_module(path, repo_root, modname)
    except (SyntaxError, ValueError) as exc:
        if logger:
            logger.warning(f"[assets_docs] {path.relative_to(repo_root).as_posix()} "
                           f"not documented: {exc}")
        return None


def _test_modules(tests_dir, repo_root, logger):
    """{directory name ("" for tests/ itself): [Module]}."""
    groups = {}
    for path in sorted(tests_dir.rglob("*.py"), key=lambda p: (p.parent, _module_order(p))):
        if "__pycache__" in path.parts:
            continue
        mod = _parse(path, repo_root, _modname(path, tests_dir), logger)
        if mod is None or not mod.doc and not mod.funcs:
            continue
        rel = path.parent.relative_to(tests_dir).as_posix()
        groups.setdefault("" if rel == "." else rel, []).append(mod)
    return groups


def _markers(repo_root):
    """[(marker, meaning, run by default)] from pyproject.toml, and its addopts."""
    path = repo_root / "pyproject.toml"
    if not path.exists():
        return [], ""
    cfg = tomllib.loads(path.read_text(encoding="utf-8"))
    ini = cfg.get("tool", {}).get("pytest", {}).get("ini_options", {})
    addopts = ini.get("addopts", "")
    if isinstance(addopts, list):
        addopts = " ".join(addopts)
    deselected = set(re.findall(r"\bnot\s+(\w+)", addopts))
    rows = []
    for entry in ini.get("markers", []):
        name, _, meaning = entry.partition(":")
        rows.append((name.strip(), meaning.strip(), name.strip() not in deselected))
    return rows, addopts


class SuiteDoc:
    def __init__(self, repo_root, source_url, source_page, logger=None):
        self.repo_root = repo_root
        self.source_url = source_url  # (repo-relative path, line) -> GitHub URL or None
        self.source_page = source_page  # module name -> link to its highlighted source
        self.logger = logger
        self.modules = []  # (family, Module) of every parsed file, for sphinx.ext.viewcode

    # -- tests -------------------------------------------------------------

    def tests_pages(self):
        tests_dir = self.repo_root / "tests"
        groups = _test_modules(tests_dir, self.repo_root, self.logger)
        for mods in groups.values():
            self.modules.extend(("tests", m) for m in mods)
        self.referenced = set().union(*(m.role_targets for ms in groups.values() for m in ms))
        pages = {"index.md": self._tests_index(groups)}
        for rel, mods in groups.items():
            if rel:
                pages[rel.replace("/", "-") + ".md"] = self._tests_dir_page(rel, mods)
        return pages

    def _tests_index(self, groups):
        out = [r.generated_note(["tests/", "pyproject.toml"]), "# Tests\n", TESTS_INTRO]
        out.append("## Running the tests\n")
        out.append('```{include} ../../../README.md\n:relative-images:\n'
                   ':start-after: "## Running the tests"\n```\n')

        markers, addopts = _markers(self.repo_root)
        if markers:
            users = {}
            for mods in groups.values():
                for m in mods:
                    for mk in m.all_marks:
                        users.setdefault(mk, []).append(f":py:mod:`{m.modname}`")
            out.append("## Markers\n")
            out.append(
                f"The markers are declared in `pyproject.toml`, whose `addopts` is "
                f"`{addopts}`: a plain `python -m pytest` deselects the markers "
                f"marked *no* below, and `-m <marker>` selects them.\n"
            )
            out.append(r.eval_rst(r.list_table(
                ["Marker", "Meaning", "Run by default", "Used in"],
                [[r.literal(n), meaning, "yes" if default else "no",
                  ", ".join(users.get(n, [])) or "no test"]
                 for n, meaning, default in markers],
                widths=[12, 38, 10, 40],
            )))

        out.append("## Directories\n")
        rows = []
        for rel, mods in groups.items():
            if not rel:
                continue
            ntests = sum(len(m.tests) for m in mods)
            marks = list(dict.fromkeys(mk for m in mods for mk in m.all_marks))
            names = ", ".join(m.path.rsplit("/", 1)[1] for m in mods)
            rows.append([f":doc:`tests/{rel} <{rel.replace('/', '-')}>`",
                         str(ntests), ", ".join(r.literal(x) for x in marks), names])
        out.append(r.eval_rst(r.list_table(
            ["Directory", "Tests", "Markers", "Modules"], rows, widths=[18, 8, 24, 50])))

        for mod in groups.get("", []):
            out.append(f"## Shared fixtures: `{mod.path}`\n")
            out.append(ps.module_body(mod, self.source_url, self.source_page, 3,
                                      documented_helpers_only=False,
                                      referenced=self.referenced))

        data_dir = self.repo_root / "tests" / "data"
        if data_dir.exists():
            sources = {
                m.path: ps.source_text((self.repo_root / m.path).read_bytes())
                for mods in groups.values() for m in mods
            }
            modname = {m.path: m.modname for mods in groups.values() for m in mods}
            rows = []
            for f in sorted(p for p in data_dir.iterdir() if p.is_file()):
                readers = [f":py:mod:`{modname[path]}`" for path, text in sources.items()
                           if f.name in text]
                # the size in git: CRLF counted as LF, whatever core.autocrlf did
                size = len(f.read_bytes().replace(b"\r\n", b"\n"))
                rows.append([r.link(f.name, self.source_url(f.relative_to(self.repo_root)
                                                            .as_posix(), None)),
                             f"{size / 1024:,.1f} KiB",
                             ", ".join(readers) or "none"])
            out.append("## Test data\n")
            out.append(
                "`tests/data` holds the frozen reference values (goldens) that the "
                "tests compare the model with. *Named in* lists the modules whose "
                "source names the file.\n"
            )
            out.append(r.eval_rst(r.list_table(
                ["File", "Size", "Named in"], rows, widths=[35, 12, 53])))

        out.append("```{toctree}\n:hidden:\n\n" + "\n".join(
            rel.replace("/", "-") for rel in groups if rel) + "\n```\n")
        return "\n".join(out)

    def _tests_dir_page(self, rel, mods):
        ntests = sum(len(m.tests) for m in mods)
        out = [r.generated_note([f"tests/{rel}/"]), f"# tests/{rel}\n"]
        out.append(f"{_n(len(mods), 'module')}, {_n(ntests, 'test function')}.\n")
        rows = [[f":py:mod:`{m.path.rsplit('/', 1)[1]} <{m.modname}>`",
                 str(len(m.tests)) if m.tests else "",
                 ", ".join(r.literal(x) for x in m.all_marks),
                 r.summary(m.doc)] for m in mods]
        out.append(r.eval_rst(r.list_table(
            ["Module", "Tests", "Markers", "Summary"], rows, widths=[22, 7, 14, 57])))
        for m in mods:
            out.append(f"## {m.path.rsplit('/', 1)[1]}\n")
            out.append(ps.module_body(m, self.source_url, self.source_page, 3,
                                      documented_helpers_only=m.tests != [],
                                      referenced=self.referenced))
        return "\n".join(out)

    # -- scripts -----------------------------------------------------------

    def parse_scripts(self, rel_paths, family):
        """[Module] of the scripts ``rel_paths``, which form one family."""
        mods = []
        for rel in rel_paths:
            path = self.repo_root / rel
            mod = _parse(path, self.repo_root, path.stem, self.logger)
            if mod is not None:
                mods.append(mod)
        self.modules.extend((family, m) for m in mods)
        return mods

    def script_page(self, mod, family_mods):
        """The page of one script; ``family_mods`` are the scripts of its family."""
        referenced = set().union(*(m.role_targets for m in family_mods))
        out = [r.generated_note([mod.path]), f"# {mod.path}\n"]
        out.append(ps.module_body(mod, self.source_url, self.source_page, 2,
                                  documented_helpers_only=True, referenced=referenced))
        return "\n".join(out)

    def tools_pages(self):
        tools = self.repo_root / "tools"
        paths = sorted(p for p in tools.rglob("*.py") if "__pycache__" not in p.parts)
        mods = self.parse_scripts(
            [p.relative_to(self.repo_root).as_posix() for p in paths], "tools")
        pages, rows, names = {}, [], []
        for mod in mods:
            p = self.repo_root / mod.path
            name = p.relative_to(tools).with_suffix("").as_posix().replace("/", "-")
            pages[f"{name}.md"] = self.script_page(mod, mods)
            names.append(name)
            rows.append([f":doc:`{mod.path} <{name}>`", r.summary(mod.doc)])
        out = [r.generated_note(["tools/"]), "# tools\n"]
        out.append(
            "The scripts in `tools/` build, benchmark and maintain the model. This "
            "page and the pages below are generated from their docstrings and "
            "their command-line options.\n"
        )
        out.append(r.eval_rst(r.list_table(["Script", "Summary"], rows, widths=[30, 70])))
        out.append("```{toctree}\n:hidden:\n\n" + "\n".join(names) + "\n```\n")
        pages["index.md"] = "\n".join(out)
        return pages

    # -- the demo inputs ---------------------------------------------------

    def csv_fragment(self, rel_dir):
        """A Markdown table of the CSV files of ``rel_dir``: rows and columns."""
        rows = []
        for p in sorted((self.repo_root / rel_dir).glob("*.csv")):
            with p.open(encoding="utf-8", newline="") as f:
                data = list(csv.reader(f))
            header, body = (data[0], data[1:]) if data else ([], [])
            cols = ", ".join(f"`{c}`" for c in header)
            url = self.source_url(p.relative_to(self.repo_root).as_posix(), None)
            rows.append(f"| {r.md_link(p.name, url)} | {len(body)} | {cols} |")
        return (r.generated_note([f"{rel_dir}/*.csv"])
                + "\n| File | Rows | Columns |\n|---|---:|---|\n" + "\n".join(rows) + "\n")
