# bond_portfolio

`bond_portfolio/` holds the `BondPortfolio` model and what is needed to run
it: a demo input set, the driver that runs the model and writes its outputs,
a generator of synthetic input sets, and the model's documents.

| Path | What it is |
|---|---|
| `BondPortfolio/` | The modelx model, in modelx's serializer format: `__init__.py` holds the model docstring and the model-level References, and each Space has its own `__init__.py`. See the [model reference](../reference/model/index.md). |
| `bonds.csv`, `valuation_dates.csv`, `curve_params.csv`, ... | The demo input set. The model reads it when `Data.input_dir` is not set, since its default is the directory containing the model. See [the demo inputs](#the-demo-inputs) below. |
| `run.py` | The driver: runs the model on a directory of input files and writes the cash flows, the valuations and a run summary. See [](../reference/bond_portfolio/run.md). |
| `generate_inputs.py` | Writes seeded synthetic input sets of any size, and the coverage set used to compile the model. See [](../reference/bond_portfolio/generate_inputs.md). |
| `model.md` | The model: Spaces, inputs, settings, outputs, running, limits, memory and tests. See [](model.md). |
| `inputs.md` | The input files: their columns, value formats and defaults. See [](inputs.md). |
| `technical-notes.md` | What a valuation at a future date includes, rule by rule. See [](technical-notes.md). |

## The model

`BondPortfolio` has seven Spaces. `Data` reads the inputs and holds the run
settings; `Lib` and `Dates` hold the numerics and the date algebra shared by
the other Spaces; `Bond[b]` builds the schedule and the leg of bond `b`;
`Legs` gathers the legs of all bonds into flat arrays; `Proj` buckets the
cash flows into the projection periods between valuation dates; and
`Valuation[scen_id, t]` values every bond at valuation date `t` under
scenario `scen_id`. The [model reference](../reference/model/index.md)
documents every Space and Cells from the model's docstrings and lists the
References with their values; [](model.md) describes how they fit together.

## The demo inputs

The CSV files next to `BondPortfolio/` are a small input set for trying the
model, specified in [](inputs.md). `bonds.csv` lists the bonds, one row per
bond index `b`; `coupon_rates.csv` gives step-up coupon rates;
`valuation_dates.csv` the valuation dates `t`; `curve_params.csv` and
`curve_nodes.csv` the discount curve of every `(scen_id, t)`; `spreads.csv`
the spreads; `prices.csv` the quoted prices, from which the yields and the
z-spreads are solved; and `yields.csv` the quoted yields, at which the risk
measures are taken. The table is read from the files when the documentation
is built.

```{include} ../reference/_fragments/demo_inputs.md
```

For larger portfolios, `generate_inputs.py` writes input sets in the same
format; `tools/cy/sample_inputs` holds the coverage set it generates.

## Running the model

```
python bond_portfolio/run.py --inputs bond_portfolio --out out
```

values the demo inputs in modelx mode. `--mode export` and `--mode compiled`
run the exported and the compiled packages, which `tools/build_cy.py` builds;
`--output-level 2` and `3` add the analytics. On the demo inputs these levels
also need `--solver-errors nan`: the demo set has a yield that is not
Compounded, and its Macaulay duration raises under the default policy. The
[run.py page](../reference/bond_portfolio/run.md) lists the steps, the output
files and the options, and [](model.md) shows how to run the model
interactively.

```{toctree}
:hidden:
:maxdepth: 1

model
inputs
technical-notes
../reference/bond_portfolio/run
../reference/bond_portfolio/generate_inputs
```
