"""bond_portfolio/run.py end to end, and the Phase 1 Spaces in export mode.

``run.py`` is run as a script on the coverage inputs into ``tmp_path``; the
two CSV files must reproduce ``Legs.cashflow_frame()``, ``Proj.bond_cf_table()``
and ``Proj.period_table()`` of a model instance of the test's own, value for
value (floats read back with round-trip precision and compared bit for bit).
"""

import subprocess
import sys

import pandas as pd
import pytest

from cashflow_checks import COVERAGE, DEMO, ROOT, private_model, same
from helpers import modes

RUN = ROOT / "bond_portfolio" / "run.py"


def read(path):
    return pd.read_csv(path, dtype={"bond_key": str, "date": str, "accrual_start": str, "accrual_end": str,
                                    "ref_start": str, "ref_end": str, "period_start": str, "period_end": str},
                       keep_default_na=False, na_values={"nominal": [""], "rate": [""],
                                                         "accrual_period": [""]},
                       float_precision="round_trip")


@pytest.fixture(scope="module")
def m():
    model = private_model("RunTest")
    yield model
    model.close()


@pytest.mark.parametrize("input_dir", [COVERAGE, DEMO], ids=["coverage", "demo"])
def test_run_py_writes_the_model_outputs(m, tmp_path, input_dir):
    out = tmp_path / "out"
    proc = subprocess.run([sys.executable, "-B", str(RUN), "--inputs", str(input_dir), "--out", str(out)],
                          capture_output=True, text=True, timeout=600)
    assert proc.returncode == 0, proc.stderr
    assert "cashflows.csv" in proc.stdout

    m.Data.input_dir = str(input_dir)
    cf = read(out / "cashflows.csv")
    exp = m.Legs.cashflow_frame()
    assert list(cf.columns) == list(exp.columns)
    assert len(cf) == len(exp) == m.Legs.n_flows()
    for c in exp.columns:
        if exp[c].dtype.kind == "f":
            assert same(cf[c].astype(float).tolist(), exp[c].tolist()), c
        else:
            assert cf[c].tolist() == exp[c].tolist(), c

    pf = read(out / "period_cashflows.csv")
    assert list(pf.columns) == ["level", "bond_key", "per", "period_start", "period_end", "coupon",
                                "amortization", "redemption", "total"]
    bonds = pf[pf["level"] == "bond"].reset_index(drop=True)
    port = pf[pf["level"] == "portfolio"].reset_index(drop=True)
    bt = m.Proj.bond_cf_table()
    assert bonds["bond_key"].tolist() == bt["bond_key"].tolist()
    assert bonds["per"].tolist() == bt["per"].tolist()
    for c in ("coupon", "amortization", "redemption"):
        assert same(bonds[c].tolist(), bt[c].tolist()), c
    assert same(bonds["total"].tolist(),
                [c + a + r for c, a, r in zip(bt["coupon"], bt["amortization"], bt["redemption"])])
    pt = m.Proj.period_table()
    assert port["per"].tolist() == pt["per"].tolist() == list(range(m.Data.n_times() + 1))
    assert (port["bond_key"] == "").all()
    for c in ("period_start", "period_end"):
        assert port[c].tolist() == pt[c].tolist(), c
    for c in ("coupon", "amortization", "redemption", "total"):
        assert same(port[c].tolist(), pt[c].tolist()), c
    # every bond row carries its period's bounds
    bounds = dict(zip(pt["per"], zip(pt["period_start"], pt["period_end"])))
    assert [bounds[p] for p in bonds["per"]] == list(zip(bonds["period_start"], bonds["period_end"]))


def test_run_py_reports_invalid_inputs(tmp_path):
    (tmp_path / "in").mkdir()
    proc = subprocess.run([sys.executable, "-B", str(RUN), "--inputs", str(tmp_path / "in"),
                           "--out", str(tmp_path / "out")], capture_output=True, text=True, timeout=600)
    assert proc.returncode == 1
    assert "bonds.csv: input file not found" in proc.stderr


def test_export_mode_equals_modelx(m, tmp_path):
    """The exported (no-modelx) model gives bit-identical Bond, Legs and Proj results on the coverage inputs."""
    pkg = modes.export_package(tmp_path)
    e = modes.new_instance(pkg, COVERAGE)
    m.Data.input_dir = str(COVERAGE)
    ce, cm = e.Legs.leg_columns(), m.Legs.leg_columns()
    assert sorted(ce) == sorted(cm)
    for k in cm:
        assert modes.same_bits(ce[k], cm[k]), k
    for b in range(m.Data.n_bonds()):
        for name in ("schedule", "coupons", "coupon_amounts", "accrual_periods", "notional_schedule",
                     "redemption_flows", "leg", "maturity_date", "calendar"):
            assert modes.same_bits(getattr(e.Bond[b], name)(), getattr(m.Bond[b], name)()), (b, name)
    assert modes.same_bits(e.Proj.bucket_arr(), m.Proj.bucket_arr())
    assert modes.same_bits(e.Proj.bucket_sums(), m.Proj.bucket_sums())
    for per in range(m.Data.n_times() + 1):
        for name in ("coupon_cf", "amortization_cf", "redemption_cf", "total_cf", "period_start", "period_end"):
            assert modes.same_bits(getattr(e.Proj, name)(per), getattr(m.Proj, name)(per)), (per, name)
    assert e.Legs.cashflow_frame().equals(m.Legs.cashflow_frame())
    assert e.Proj.bond_cf_table().equals(m.Proj.bond_cf_table())
    assert e.Proj.period_table().equals(m.Proj.period_table())
    assert e.Legs.check_limits() is True
