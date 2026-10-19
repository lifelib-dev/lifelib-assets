# Sphinx configuration for the lifelib-assets documentation.
#
# Build with `make html` in this directory (make.bat on Windows). The pages
# under reference/ are generated on every build by the extension in
# _ext/assets_docs: the model reference (read with modelx), the tests and the
# scripts (parsed from their docstrings). See _ext/assets_docs/__init__.py.

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "_ext"))

from assets_docs import linkcode_resolve  # noqa: E402, F401

project = "lifelib-assets"
author = "lifelib Developers"
copyright = "2026, lifelib Developers"

extensions = [
    "myst_parser",
    "sphinx.ext.linkcode",
    "assets_docs",
]

root_doc = "index"
exclude_patterns = ["_build", "reference/_fragments", "Thumbs.db", ".DS_Store"]

# `x` in a docstring is code (tests/helpers/approx.py writes it so).
default_role = "literal"
# Show quotes, '--' and '...' as written: the Markdown and the docstrings hold
# literal values, messages and command-line options in their prose.
smartquotes = False

# -- MyST --------------------------------------------------------------------

myst_enable_extensions = ["colon_fence"]
myst_heading_anchors = 4

# -- Python objects ----------------------------------------------------------

add_module_names = False
toc_object_entries = False
python_display_short_literal_types = True

# -- assets_docs -------------------------------------------------------------

assets_github_url = "https://github.com/lifelib-dev/lifelib-assets"
assets_github_branch = "main"
assets_model_dir = "bond_portfolio/BondPortfolio"
assets_model_scripts = ["bond_portfolio/run.py", "bond_portfolio/generate_inputs.py"]
assets_generated_dir = "reference"

# -- HTML --------------------------------------------------------------------

html_theme = "pydata_sphinx_theme"
html_title = "lifelib-assets"
html_static_path = ["_static"]
html_css_files = ["custom.css"]
html_theme_options = {
    "github_url": assets_github_url,
    "show_toc_level": 2,
    "navigation_with_keys": False,
    "header_links_before_dropdown": 6,
    "secondary_sidebar_items": ["page-toc"],
}
html_show_sourcelink = False
