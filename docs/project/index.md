# Project

lifelib-assets holds asset models for [lifelib](https://lifelib.io), built
with [modelx](https://modelx.io). Its first model is `BondPortfolio`, a bond
portfolio model whose financial logic is transcribed from quantlib-migration's
`pureql`, a pure-Python port of the fixed-rate bond subset of QuantLib v1.43.
The model reproduces pureql's numbers bit for bit, and so do its exported
pure-Python package and the package compiled by modelx-cython.

## Repository layout

| Path | Contents |
|---|---|
| `bond_portfolio/` | The `BondPortfolio` model, its demo input files, the driver `run.py`, the input generator `generate_inputs.py`, and the model's documents. See [bond_portfolio](../bond_portfolio/index.md). |
| `tests/` | The pytest suite. It compares the model with pureql bit for bit, and with QuantLib 1.41 behind the `oracle` marker. See [Tests](../reference/tests/index.md). |
| `tools/` | Scripts that export and compile the model, benchmark it, calibrate spreads, and generate `NOTICE.md`. See [tools](../reference/tools/index.md). |
| `docs/` | This documentation: the development notes, the Sphinx configuration, and the extension that generates the reference pages. |
| `README.md` | The project description, shown on the [home page](../index.md). |
| `DECISIONS.md` | The modelling policies: what is derived and how, fidelity, the v1 scope and the valuation policies. See [Decisions](decisions.md). |
| `NOTICE.md` | The notice for the files derived from QuantLib. See [NOTICE](notice.md). |
| `LICENSE.txt` | The MIT License of the project's own files. See [License](license.md). |
| `pyproject.toml` | The project metadata, its dependencies (modelx, numpy, pandas), and the pytest configuration: test paths, markers, and the tests deselected by default. |

The export and the compiled package are built in the directory that
`tools/buildpaths.py` chooses: `BONDPORTFOLIO_BUILD` if it is set; otherwise
`~/.cache/lifelib-assets/build` when the project is in a OneDrive folder, else
`build/` in the project (git-ignored). See [](../reference/tools/buildpaths.md).

## Requirements

- **The model**: Python 3.13 or later, modelx 0.33 or later, numpy and pandas.
- **The compiled package**: modelx-cython and a C compiler; build it with
  `tools/build_cy.py`, from PowerShell on Windows.
- **The tests**: pytest, and a quantlib-migration checkout next to this
  project (`../quantlib-migration`), or the `PUREQL_SRC` environment variable
  set to the `src` directory of a checkout; the tests import `pureql` from
  there. The `oracle` tests also need the QuantLib 1.41 Python binding;
  without it they are skipped.
- **This documentation**: Sphinx, MyST-Parser, the PyData Sphinx Theme, and
  modelx with numpy and pandas, which reading the model imports; see
  `docs/requirements.txt`.

## Building this documentation

In `docs/`, with the packages of `docs/requirements.txt` installed in the
active environment, run

```
make html
```

`make.bat` does this on Windows, `Makefile` elsewhere; the pages are written
to `docs/_build/html`. In PowerShell, type `.\make html`: PowerShell does not
run commands from the current directory. `make.bat` runs `sphinx-build` from
the `PATH`, or the command in the `SPHINXBUILD` environment variable, and
returns its exit code. Every build regenerates the pages under
`docs/reference/` (model reference, tests, scripts) from the docstrings, so
they are not kept in git. The extension that does this is
`docs/_ext/assets_docs`.

```{toctree}
:hidden:
:maxdepth: 1

decisions
notice
license
../reference/tools/index
```
