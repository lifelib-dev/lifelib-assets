"""The model reads, and survives a write_model round trip with its formulas intact."""

import modelx as mx

from helpers.model import MODEL_DIR


def _formulas(m):
    out = {}
    for sname, space in m.spaces.items():
        for cname, cells in space.cells.items():
            out[(sname, cname)] = cells.formula.source
    return out


def test_write_model_round_trip(tmp_path):
    m = mx.read_model(MODEL_DIR, name="BondPortfolio_io1")
    try:
        mx.write_model(m, tmp_path / "BondPortfolio")
        m2 = mx.read_model(tmp_path / "BondPortfolio", name="BondPortfolio_io2")
        try:
            assert _formulas(m) == _formulas(m2)
        finally:
            m2.close()
    finally:
        m.close()
