# Development notes

These documents, kept in `docs/`, record how `BondPortfolio` was planned,
specified, measured and compiled.

| Document | Contents |
|---|---|
| [Plan](plan.md) | The plan the model was built to: context and constraints, the design (project layout, Space tree, inputs, future-t semantics, modelx-cython rules, fidelity policy), the phases, the verification, and the risks. |
| [Model contract](model-contract.md) | The binding interface between the Spaces: authoring rules, provenance and licence, the model-level References (codes and compile-time limits), the coding rules, the Spaces and Cells with their signatures and return types, the tests, and what was built in Phases 1 to 4. |
| [Performance record](performance.md) | The measured run times and memory: how they are produced, the results by mode, the analytics by output level, and the modelx-cython improvements of Phase 5. |
| [modelx-cython issues](mx2cy-issues.md) | The modelx-cython and exporter issues found while building the model, the workaround each needed, and their status after Phase 5. |

```{toctree}
:hidden:
:maxdepth: 1

plan
model-contract
performance
mx2cy-issues
```
