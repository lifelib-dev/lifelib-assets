"""Sphinx extension for the lifelib-assets documentation.

* Before Sphinx reads the sources, it writes the generated pages under
  ``reference/`` (``assets_generated_dir``): the BondPortfolio model reference,
  read with modelx; the test suite and the scripts, parsed with :mod:`ast`; and
  a table of the demo input files. Only pages whose text changed are written,
  and only generated pages are ever deleted.
* It rewrites the relative links of the repository's Markdown files, which the
  hand-written pages ``{include}``, so that they work in the docs (see
  :mod:`.links`).
* :func:`linkcode_resolve` gives :mod:`sphinx.ext.linkcode` the GitHub URL of
  the source lines of every documented object.
"""

from pathlib import Path

from sphinx.errors import ConfigError
from sphinx.util import logging

from . import links, model, suite
from . import pysource as ps
from . import render as r

logger = logging.getLogger(__name__)

_state = {
    "rewriter": None,
    "linemap": {},  # module name -> {object name: (repo path, line)}
    "config": None,
}


def _source_url(rel_path, line):
    cfg = _state["config"]
    if not cfg.assets_github_url:
        return None
    url = f"{cfg.assets_github_url.rstrip('/')}/blob/{cfg.assets_github_branch}/{rel_path}"
    return f"{url}#L{line}" if line else url


def linkcode_resolve(domain, info):
    """The GitHub URL of a documented Python object, for sphinx.ext.linkcode."""
    if domain != "py" or _state["config"] is None:
        return None
    entry = _state["linemap"].get(info.get("module"), {}).get(info.get("fullname"))
    return _source_url(*entry) if entry else None


def _generate(app):
    cfg = app.config
    _state["config"] = cfg
    srcdir = Path(app.srcdir).resolve()
    repo_root = (srcdir / cfg.assets_repo_root).resolve()
    out_dir = (srcdir / cfg.assets_generated_dir).resolve()
    if out_dir == srcdir or not out_dir.is_relative_to(srcdir):
        raise ConfigError("assets_generated_dir must name a subdirectory of the "
                          "documentation source directory")
    pages = {}

    try:
        mdoc = model.ModelDoc(repo_root, cfg.assets_model_dir, _source_url)
        pages.update({f"model/{k}": v for k, v in mdoc.generate().items()})
        _state["linemap"].update(mdoc.linemap)
    except Exception as exc:  # modelx or a model dependency missing, or a bad model
        logger.warning(f"[assets_docs] model reference not generated: {exc!r}")

    sdoc = suite.SuiteDoc(repo_root, _source_url, logger)
    pages.update({f"tests/{k}": v for k, v in sdoc.tests_pages().items()})
    scripts = sdoc.parse_scripts(cfg.assets_model_scripts, "bond_portfolio")
    for mod in scripts:
        pages[f"bond_portfolio/{mod.modname}.md"] = sdoc.script_page(mod, scripts)
    pages.update({f"tools/{k}": v for k, v in sdoc.tools_pages().items()})
    pages["_fragments/demo_inputs.md"] = sdoc.csv_fragment(
        Path(cfg.assets_model_dir).parent.as_posix())
    for _, mod in sdoc.modules:
        _state["linemap"][mod.modname] = ps.linemap(mod)

    r.write_pages(out_dir, pages, logger)

    _state["rewriter"] = links.LinkRewriter(
        repo_root, srcdir,
        links.included_files(srcdir, skip_dirs=(Path(cfg.assets_generated_dir).parts[0],)),
        cfg.assets_github_url, cfg.assets_github_branch,
    )


def _is_generated(app, docname):
    return docname.split("/", 1)[0] == Path(app.config.assets_generated_dir).parts[0]


def _on_source_read(app, docname, source):
    rewriter = _state["rewriter"]
    if rewriter is None or _is_generated(app, docname):
        return
    path = Path(app.env.doc2path(docname))
    if path.suffix == ".md":
        source[0] = rewriter.rewrite(source[0], path, docname)


def _on_include_read(app, relative_path, parent_docname, content):
    rewriter = _state["rewriter"]
    path = (Path(app.srcdir) / relative_path).resolve()
    if rewriter is not None and path.suffix == ".md":
        content[0] = rewriter.rewrite(content[0], path, app.env.docname)


def setup(app):
    app.add_config_value("assets_repo_root", "..", "env")
    app.add_config_value("assets_github_url", "", "env")
    app.add_config_value("assets_github_branch", "main", "env")
    app.add_config_value("assets_model_dir", "bond_portfolio/BondPortfolio", "env")
    app.add_config_value("assets_model_scripts",
                         ["bond_portfolio/run.py", "bond_portfolio/generate_inputs.py"], "env")
    app.add_config_value("assets_generated_dir", "reference", "env")
    app.connect("builder-inited", _generate)
    app.connect("source-read", _on_source_read)
    app.connect("include-read", _on_include_read)
    return {"version": "1.0", "parallel_read_safe": True, "parallel_write_safe": True}
