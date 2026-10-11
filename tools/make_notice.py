"""Generate ``NOTICE.md`` from the QuantLib licence file shipped with quantlib-migration.

The notice must reproduce the QuantLib copyright-holder list, the three further
attributions and the BSD-3-Clause text *verbatim* (quantlib-migration
``docs/ATTRIBUTION_TEMPLATE.md`` section 3). Generating it from
``LICENSES/QuantLib-LICENSE.TXT`` keeps it verbatim, and
``tests/lint/test_notice.py`` re-checks the generated file against the source.

Usage::

    python tools/make_notice.py [path/to/quantlib-migration]
"""

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_QLM = ROOT.parent / "quantlib-migration"

QL_TAG = "v1.43"
QL_COMMIT = "6b57206e04598f092efee66e3b367efc84771995"

# Line ranges (1-based, inclusive) in LICENSES/QuantLib-LICENSE.TXT.
HOLDERS = (1, 192)
ATTRIBUTIONS = (194, 202)
BSD_TEXT = (205, 231)

DERIVED_FILES = """\
The derived files are the Space definitions of the modelx model in
``bond_portfolio/BondPortfolio/`` whose formulas carry the comment
``# ported from pureql/... QuantLib v1.43, BSD-3-Clause`` (the ``Lib``,
``Dates``, ``Data``, ``Bond``, ``Legs``, ``Proj`` and ``Valuation``
Spaces), and any package generated from that model by
``modelx.export_model`` or by ``modelx-cython`` (the build directory of
``tools/build_cy.py``). Every other file in this project is the project's
own work, licensed under the MIT License (``LICENSE.txt``)."""


def read_lines(path, first, last):
    lines = path.read_text(encoding="utf-8").splitlines()
    return "\n".join(lines[first - 1:last])


def build(qlm: pathlib.Path) -> str:
    lic = qlm / "LICENSES" / "QuantLib-LICENSE.TXT"
    holders = read_lines(lic, *HOLDERS)
    attributions = read_lines(lic, *ATTRIBUTIONS)
    bsd = read_lines(lic, *BSD_TEXT)
    return f"""\
# NOTICE

This project includes code derived from QuantLib (https://www.quantlib.org),
tag {QL_TAG}, commit {QL_COMMIT}, by way of `pureql`,
a pure-Python port. The derived files are licensed BSD-3-Clause.

## Which files are derived

{DERIVED_FILES}

## QuantLib copyright holders

```
{holders}
```

## Further attributions

```
{attributions}
```

## Licence of the derived files (BSD 3-Clause)

```
{bsd}
```

## Non-endorsement

This project is NOT part of QuantLib and is not endorsed by the QuantLib Group
or its contributors.
"""


def main(argv):
    qlm = pathlib.Path(argv[1]) if len(argv) > 1 else DEFAULT_QLM
    text = build(qlm)
    (ROOT / "NOTICE.md").write_text(text, encoding="utf-8", newline="\n")
    print("wrote", ROOT / "NOTICE.md")


if __name__ == "__main__":
    main(sys.argv)
