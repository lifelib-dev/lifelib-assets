```{include} ../README.md
:relative-images:
```

## This documentation

| Section | What it covers |
|---|---|
| [Project](project/index.md) | The repository layout, the modelling decisions, the NOTICE for the code derived from QuantLib, the licence, and the scripts in `tools/`. |
| [bond_portfolio](bond_portfolio/index.md) | The `bond_portfolio` directory: the model, the demo input files, the driver `run.py`, the input generator `generate_inputs.py`, and the model's own documents. |
| [Model reference](reference/model/index.md) | `BondPortfolio` Space by Space, generated from the docstrings of its Spaces and Cells. |
| [Tests](reference/tests/index.md) | The test suite in `tests/`, generated from the docstrings of the test modules. |
| [Development notes](development.md) | The plan, the model contract, the performance record and the modelx-cython issues, kept in `docs/`. |

```{toctree}
:hidden:
:maxdepth: 2

project/index
bond_portfolio/index
reference/model/index
reference/tests/index
development
```
