"""The Data Space: readers, parsers, input arrays, check_inputs and generate_inputs.py.

docs/model-contract.md section 4.3, bond_portfolio/inputs.md. The expected
values are computed independently here, from the CSV text and pureql (dates,
periods and enum values), and compared with ``==``.

A private model instance is used so that switching ``Data.input_dir`` between
input sets does not disturb the session model other tests share.
"""

import csv
import importlib.util
import math
import pathlib
import re
import shutil

import modelx as mx
import numpy as np
import pytest

from helpers.model import MODEL_DIR
from helpers.pureql_ref import pq_calendar, pq_date, pq_daycounter, pq_period, ql, serial
from pureql.time.calendars.target import TARGET
from pureql.time.calendars.unitedstates import UnitedStates
from pureql.time.daycounters.actual360 import Actual360
from pureql.time.daycounters.thirty360 import Thirty360

ROOT = MODEL_DIR.parents[1]
DEMO = ROOT / "bond_portfolio"
COVERAGE = ROOT / "tools" / "cy" / "sample_inputs"

_spec = importlib.util.spec_from_file_location("generate_inputs", DEMO / "generate_inputs.py")
gen = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gen)

CALENDARS = {"NullCalendar": 0, "TARGET": 1, "UnitedStates.Settlement": 2, "UnitedStates.GovernmentBond": 3}
DAY_COUNTERS = {"Actual360": 1, "Actual365Fixed": 2, "Thirty360.USA": 10, "Thirty360.BondBasis": 11,
                "Thirty360.ISMA": 11, "Thirty360.European": 12, "Thirty360.EurobondBasis": 12}
UNITS = {"D": 0, "W": 1, "M": 2, "Y": 3}


@pytest.fixture(scope="module")
def m():
    model = mx.read_model(MODEL_DIR, name="BondPortfolio_test_data")
    yield model
    model.close()


@pytest.fixture
def data(m):
    m.Data.input_dir = str(DEMO)
    return m.Data


def using(m, input_dir):
    m.Data.input_dir = str(input_dir)
    return m.Data


def assert_value_error(call, pattern):
    """``call()`` raises ValueError (wrapped in modelx's FormulaError at the top level) matching ``pattern``."""
    with pytest.raises((ValueError, mx.core.errors.FormulaError)) as ei:
        call()
    text = str(ei.value)
    if isinstance(ei.value, mx.core.errors.FormulaError):
        assert "ValueError" in text, text
    assert re.search(pattern, text), f"{pattern!r} not in:\n{text}"


def read_csv(path):
    if not pathlib.Path(path).exists():
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return [{k.strip(): (v or "").strip() for k, v in r.items()} for r in csv.DictReader(f)]


def pq_serial_of(iso):
    """Serial of an ISO date through pureql's Date(d, m, y), or 0 for blank."""
    if not iso:
        return 0
    y, mo, d = (int(x) for x in iso.split("-"))
    return serial(ql.Date(d, ql.Month(mo), y))


def enum_value(enum, name):
    return int(getattr(enum, name))


# ----------------------------------------------------------------------------- parsers

def test_calendar_code_names_match_pureql(data):
    built = {"NullCalendar": ql.NullCalendar(), "TARGET": TARGET(),
             "UnitedStates.Settlement": UnitedStates(UnitedStates.Settlement),
             "UnitedStates.GovernmentBond": UnitedStates(UnitedStates.GovernmentBond)}
    for name, code in CALENDARS.items():
        assert data.calendar_code(name) == code
        assert pq_calendar(code) == built[name]
    assert (data.calendar_code("NullCalendar"), data.calendar_code("TARGET")) == (data.CAL_NULL, data.CAL_TARGET)


def test_daycounter_code_names_match_pureql_pairs(data):
    """BondBasis/ISMA and European/EurobondBasis share an implementation in thirty360._implementation."""
    built = {"Actual360": Actual360(), "Actual365Fixed": ql.Actual365Fixed(),
             "Thirty360.USA": Thirty360(Thirty360.USA), "Thirty360.BondBasis": Thirty360(Thirty360.BondBasis),
             "Thirty360.ISMA": Thirty360(Thirty360.ISMA), "Thirty360.European": Thirty360(Thirty360.European),
             "Thirty360.EurobondBasis": Thirty360(Thirty360.EurobondBasis)}
    for name, code in DAY_COUNTERS.items():
        assert data.daycounter_code(name) == code
        assert pq_daycounter(code) == built[name], name
        assert pq_daycounter(code).name() == built[name].name()


@pytest.mark.parametrize("parser,enum,prefix", [
    ("bdc_code", ql.BusinessDayConvention, "BDC_"),
    ("comp_code", ql.Compounding, "COMP_"),
    ("freq_code", ql.Frequency, "FREQ_"),
    ("rule_code", ql.DateGeneration.Rule, "RULE_"),
])
def test_enum_parsers_take_every_pureql_member_name(data, parser, enum, prefix):
    fn = getattr(data, parser)
    for name, member in enum.__members__.items():
        assert fn(name) == int(member), name
        assert type(fn(name)) is int
    for ref, value in data.model.refs.items():
        if ref.startswith(prefix):
            assert value in [int(x) for x in enum.__members__.values()], ref


def test_type_code_parsers(data):
    assert data.bond_type_code("FixedRate") == 0 == data.BOND_FIXED
    assert data.bond_type_code("ZeroCoupon") == 1 == data.BOND_ZERO
    assert data.curve_type_code("ZeroCurve") == 0 == data.CURVE_ZERO
    assert data.curve_type_code("FlatForward") == 1 == data.CURVE_FLAT
    assert data.price_type_code("Dirty") == int(ql.Bond.Price.Type.Dirty) == data.PRICE_DIRTY
    assert data.price_type_code("Clean") == int(ql.Bond.Price.Type.Clean) == data.PRICE_CLEAN


@pytest.mark.parametrize("parser,text,pattern", [
    ("calendar_code", "UnitedKingdom", r"unknown or unsupported calendar 'UnitedKingdom'"),
    ("calendar_code", "target", r"calendar 'target'"),
    ("calendar_code", "", r"calendar ''"),
    ("daycounter_code", "ActualActual.ISDA", r"unknown or unsupported day counter 'ActualActual.ISDA'"),
    ("daycounter_code", "Thirty360", r"day counter 'Thirty360'"),
    ("daycounter_code", "Thirty360.Italian", r"day counter 'Thirty360.Italian'"),
    ("bdc_code", "following", r"unknown business day convention 'following'"),
    ("comp_code", "Discrete", r"unknown compounding 'Discrete'"),
    ("freq_code", "SemiAnnual", r"unknown frequency 'SemiAnnual'"),
    ("rule_code", "DateGeneration.Backward", r"unknown date generation rule"),
    ("bond_type_code", "AmortizingFixedRate", r"unsupported bond type 'AmortizingFixedRate'"),
    ("curve_type_code", "NelsonSiegel", r"unsupported curve type 'NelsonSiegel'"),
    ("price_type_code", "Mid", r"unknown price type 'Mid'"),
    ("tenor_n", "", r"invalid tenor ''"),
    ("tenor_n", "M", r"invalid tenor 'M'"),
    ("tenor_n", "6", r"invalid tenor '6'"),
    ("tenor_n", "-6M", r"invalid tenor '-6M'"),
    ("tenor_n", "6X", r"invalid tenor '6X'"),
    ("tenor_n", "1.5Y", r"invalid tenor '1.5Y'"),
    ("tenor_unit", "6 M", r"invalid tenor '6 M'"),
    ("flag", "yes", r"invalid flag 'yes'"),
    ("flag", "2", r"invalid flag '2'"),
    ("int_text", "1.0", r"invalid integer '1.0'"),
    ("int_text", "", r"invalid integer ''"),
    ("float_text", "4%", r"invalid number '4%'"),
    ("float_text", "nan", r"invalid number 'nan' \(not finite\)"),
    ("iso_serial", "2015-9-16", r"invalid date '2015-9-16' \(expected ISO YYYY-MM-DD\)"),
    ("iso_serial", "2015/09/16", r"invalid date"),
    ("iso_serial", "20150916", r"invalid date"),
    ("iso_serial", "2015-02-30", r"invalid date '2015-02-30'"),
    ("iso_serial", "2015-13-01", r"invalid date"),
    ("iso_serial", "abcd-ef-gh", r"invalid date"),
])
def test_parsers_reject_unknown_text(data, parser, text, pattern):
    assert_value_error(lambda: getattr(data, parser)(text), pattern)


@pytest.mark.parametrize("text,n,unit", [
    ("6M", 6, "M"), ("1Y", 1, "Y"), ("2W", 2, "W"), ("10D", 10, "D"), ("0D", 0, "D"),
    ("12m", 12, "M"), ("30Y", 30, "Y"), ("3M", 3, "M"), ("1M", 1, "M"),
])
def test_tenor_parsers(data, text, n, unit):
    assert data.tenor_n(text) == n
    assert data.tenor_unit(text) == UNITS[unit] == int(getattr(ql.TimeUnit, {"D": "Days", "W": "Weeks",
                                                                              "M": "Months", "Y": "Years"}[unit]))
    assert pq_period(data.tenor_n(text), data.tenor_unit(text)) == ql.Period(n, ql.TimeUnit(UNITS[unit]))


def test_flag_and_number_parsers(data):
    assert [data.flag(s) for s in ("", "0", "1", "true", "True", "FALSE")] == [0, 0, 1, 1, 1, 0]
    assert data.int_text("-1") == -1 and data.int_text("+3") == 3 and data.int_text("12") == 12
    assert data.float_text("0.04") == 0.04 and type(data.float_text("100")) is float


def test_iso_serial_matches_pureql_over_the_whole_range(data):
    """Every serial 367..109574: the ISO text of pureql's Date gives the same serial back."""
    f = data.iso_serial
    for s in range(367, 109575):
        d = pq_date(s)
        text = f"{d.year():04d}-{int(d.month()):02d}-{d.dayOfMonth():02d}"
        assert f(text) == s, text
    assert f("") == 0
    assert f("1901-01-01") == 367 and f("2199-12-31") == 109574
    assert type(f("2015-09-16")) is int


# ----------------------------------------------------------------------------- readers

def test_readers_return_string_frames(data):
    bt = data.bond_table()
    assert len(bt) == data.n_bonds() == len(read_csv(DEMO / "bonds.csv"))
    assert all(isinstance(x, str) for x in bt["redemption"].tolist())
    assert "" in bt["spread_id"].tolist()
    assert list(data.yield_table().columns) == ["scen_id", "t", "bond_key", "yield"]
    assert list(data.price_table().columns) == ["scen_id", "t", "bond_key", "price", "price_type"]
    assert data.price_table()["price"].tolist() == ["80.0", "80.0"]


def test_optional_files_absent(m, tmp_path):
    """Only the three required files: the optional tables are empty and check_inputs passes."""
    rows = [r for r in read_csv(DEMO / "bonds.csv") if r["bond_key"] in ("HEADLINE_10Y", "ZCB_10Y")]
    for r in rows:
        r["spread_id"] = ""
    write_csv(tmp_path / "bonds.csv", rows)
    shutil.copy(DEMO / "valuation_dates.csv", tmp_path)
    write_csv(tmp_path / "curve_params.csv",
              [dict(scen_id="1", t=str(t), curve_type="FlatForward", day_counter="Actual365Fixed",
                    flat_rate="0.03") for t in range(4)])
    d = using(m, tmp_path)
    for reader, cols in (("coupon_rate_table", ["bond_key", "k", "rate"]),
                         ("curve_node_table", ["scen_id", "t", "node", "rate", "date", "tenor"]),
                         ("spread_table", ["scen_id", "t", "spread_id", "spread"])):
        df = getattr(d, reader)()
        assert len(df) == 0 and list(df.columns) == cols
    assert d.check_inputs() is True
    assert d.spread_ids() == () and d.n_spread_ids() == 0
    assert d.sp_arr().shape == (1, 4, 0)
    assert d.n_nodes_total() == 0 and d.n_cnt_arr().shape == (1, 4)
    assert d.cr_cnt_arr()[0] == 1 and d.cr_cnt_arr()[1] == 0
    assert d.c_flat_arr()[0, 3] == 0.03 and d.c_comp_arr()[0, 0] == 2 and d.c_sp_freq_arr()[0, 0] == -1


def test_input_path_defaults_to_model_parent(m):
    m.Data.input_dir = ""
    try:
        assert pathlib.Path(m.Data.input_path()).resolve() == DEMO.resolve()
    finally:
        m.Data.input_dir = str(DEMO)


# ----------------------------------------------------------------------------- arrays

def expected_bond_arrays(input_dir):
    """The bond arrays of contract 4.3, computed from the CSV text and pureql (inputs.md defaults)."""
    bonds = read_csv(pathlib.Path(input_dir) / "bonds.csv")
    vec = {}
    for r in read_csv(pathlib.Path(input_dir) / "coupon_rates.csv"):
        vec.setdefault(r["bond_key"], []).append((int(r["k"]), float(r["rate"])))
    sids = []
    for r in read_csv(pathlib.Path(input_dir) / "spreads.csv") + bonds:
        if r["spread_id"] and r["spread_id"] not in sids:
            sids.append(r["spread_id"])
    bdc = lambda s, dflt: enum_value(ql.BusinessDayConvention, s or dflt)  # noqa: E731
    e = {k: [] for k in ("b_type", "b_face", "b_settle_days", "b_calendar", "b_issue", "b_redemption",
                         "b_spread_idx", "b_eff", "b_term", "b_tenor_n", "b_tenor_unit", "b_conv",
                         "b_term_conv", "b_rule", "b_eom", "b_first", "b_ntl", "b_accrual_dc", "b_first_dc",
                         "b_pay_conv", "b_pay_cal", "cr_lo", "cr_cnt", "cr_rate", "b_maturity", "b_ydc",
                         "b_ycomp", "b_yfreq")}
    for r in bonds:
        fixed = r["bond_type"] == "FixedRate"
        e["b_type"].append(0 if fixed else 1)
        e["b_face"].append(float(r["face_amount"]))
        e["b_settle_days"].append(int(r["settlement_days"]))
        e["b_calendar"].append(CALENDARS[r["calendar"]])
        e["b_issue"].append(pq_serial_of(r["issue_date"]))
        e["b_redemption"].append(float(r["redemption"]) if r["redemption"] else 100.0)
        e["b_spread_idx"].append(sids.index(r["spread_id"]) if r["spread_id"] else -1)
        e["b_eff"].append(pq_serial_of(r["effective_date"]))
        e["b_term"].append(pq_serial_of(r["termination_date"]))
        tenor = r["tenor"] or "0D"
        e["b_tenor_n"].append(int(tenor[:-1]))
        e["b_tenor_unit"].append(UNITS[tenor[-1].upper()])
        conv = bdc(r["convention"], "Following")
        e["b_conv"].append(conv)
        e["b_term_conv"].append(bdc(r["termination_convention"], "Following") if r["termination_convention"]
                                else conv)
        e["b_rule"].append(enum_value(ql.DateGeneration.Rule, r["rule"] or "Backward"))
        e["b_eom"].append(1 if r["end_of_month"].lower() in ("1", "true") else 0)
        e["b_first"].append(pq_serial_of(r["first_date"]))
        e["b_ntl"].append(pq_serial_of(r["next_to_last_date"]))
        adc = DAY_COUNTERS[r["accrual_day_counter"]] if r["accrual_day_counter"] else 0
        e["b_accrual_dc"].append(adc)
        e["b_first_dc"].append(DAY_COUNTERS[r["first_period_day_counter"]] if r["first_period_day_counter"] else 0)
        e["b_pay_conv"].append(bdc(r["payment_convention"], "Following"))
        e["b_pay_cal"].append(CALENDARS[r["payment_calendar"]] if r["payment_calendar"] else -1)
        e["cr_lo"].append(len(e["cr_rate"]))
        if fixed:
            if r["bond_key"] in vec:
                e["cr_rate"].extend(x for _, x in sorted(vec[r["bond_key"]]))
            else:
                e["cr_rate"].append(float(r["coupon_rate"]))
        e["cr_cnt"].append(len(e["cr_rate"]) - e["cr_lo"][-1])
        e["b_maturity"].append(pq_serial_of(r["maturity_date"]))
        e["b_ydc"].append(DAY_COUNTERS[r["yield_day_counter"]] if r["yield_day_counter"]
                          else (adc if fixed else 2))
        e["b_ycomp"].append(enum_value(ql.Compounding, r["yield_compounding"] or "Compounded"))
        if r["yield_frequency"]:
            yf = enum_value(ql.Frequency, r["yield_frequency"])
        elif fixed:
            yf = int(ql.Period(int(tenor[:-1]), ql.TimeUnit(UNITS[tenor[-1].upper()])).frequency())
            if yf in (-1, 0, 999):
                yf = 1
        else:
            yf = 1
        e["b_yfreq"].append(yf)
    return e


FLOAT_ARRAYS = {"b_face", "b_redemption", "cr_rate", "c_flat", "n_rate", "sp"}


def check_array(arr, expected, name):
    dtype = np.float64 if name in FLOAT_ARRAYS else np.int64
    assert isinstance(arr, np.ndarray) and arr.dtype == dtype, name
    assert arr.flags["C_CONTIGUOUS"], name
    exp = np.asarray(expected, dtype=dtype)
    assert arr.shape == exp.shape, name
    if dtype == np.float64:
        assert np.array_equal(arr, exp, equal_nan=True), name
    else:
        assert np.array_equal(arr, exp), name


@pytest.mark.parametrize("input_dir", [DEMO, COVERAGE], ids=["demo", "coverage"])
def test_bond_arrays_match_the_csv(m, input_dir):
    d = using(m, input_dir)
    for name, values in expected_bond_arrays(input_dir).items():
        check_array(getattr(d, name + "_arr")(), values, name)
    assert d.bond_keys() == tuple(r["bond_key"] for r in read_csv(pathlib.Path(input_dir) / "bonds.csv"))
    assert d.n_bonds() == len(d.bond_keys())


def test_generated_bond_arrays_match_the_csv(m, tmp_path):
    gen.write_tables(tmp_path, gen.generate(300, 2, 3, 5))
    d = using(m, tmp_path)
    for name, values in expected_bond_arrays(tmp_path).items():
        check_array(getattr(d, name + "_arr")(), values, name)


@pytest.mark.parametrize("input_dir", [DEMO, COVERAGE], ids=["demo", "coverage"])
def test_coupon_csr_is_consistent(m, input_dir):
    d = using(m, input_dir)
    n = d.n_bonds()
    lo, cnt, rates = d.cr_lo_arr(), d.cr_cnt_arr(), d.cr_rate_arr()
    assert lo[0] == 0
    for b in range(n - 1):
        assert lo[b + 1] == lo[b] + cnt[b]
    assert lo[n - 1] + cnt[n - 1] == len(rates)
    for b in range(n):
        assert (cnt[b] == 0) == (d.b_type_arr()[b] == d.BOND_ZERO)
    vecs = {}
    for r in read_csv(pathlib.Path(input_dir) / "coupon_rates.csv"):
        vecs.setdefault(r["bond_key"], []).append((int(r["k"]), float(r["rate"])))
    assert vecs, "the input set has a step-up bond"
    for key, v in vecs.items():
        b = d.bond_keys().index(key)
        assert list(rates[lo[b]:lo[b] + cnt[b]]) == [x for _, x in sorted(v)]


@pytest.mark.parametrize("input_dir", [DEMO, COVERAGE], ids=["demo", "coverage"])
def test_scenario_time_arrays_match_the_csv(m, input_dir):
    input_dir = pathlib.Path(input_dir)
    d = using(m, input_dir)
    vds = read_csv(input_dir / "valuation_dates.csv")
    cps = read_csv(input_dir / "curve_params.csv")
    S, T = max(int(r["scen_id"]) for r in cps), len(vds)
    assert (d.n_scen(), d.n_times()) == (S, T)
    vd = [0] * T
    for r in vds:
        vd[int(r["t"])] = pq_serial_of(r["val_date"])
    check_array(d.val_date_arr(), vd, "val_date")
    exp = {k: np.full((S, T), -1, dtype=np.int64) for k in
           ("c_type", "c_dc", "c_comp", "c_freq", "c_extrap", "c_sp_comp", "c_sp_freq")}
    exp["c_flat"] = np.full((S, T), np.nan)
    for r in cps:
        s, t = int(r["scen_id"]) - 1, int(r["t"])
        exp["c_type"][s, t] = {"ZeroCurve": 0, "FlatForward": 1}[r["curve_type"]]
        exp["c_dc"][s, t] = DAY_COUNTERS[r["day_counter"]]
        exp["c_comp"][s, t] = enum_value(ql.Compounding, r["compounding"] or "Continuous")
        exp["c_freq"][s, t] = enum_value(ql.Frequency, r["frequency"] or "Annual")
        exp["c_extrap"][s, t] = int(r["extrapolate"] or 0)
        exp["c_flat"][s, t] = float(r["flat_rate"]) if r["flat_rate"] else math.nan
        exp["c_sp_comp"][s, t] = enum_value(ql.Compounding, r["spread_compounding"] or "Continuous")
        exp["c_sp_freq"][s, t] = enum_value(ql.Frequency, r["spread_frequency"] or "NoFrequency")
    for name, values in exp.items():
        check_array(getattr(d, name + "_arr")(), values, name)
    sids = list(d.spread_ids())
    sp = np.full((S, T, len(sids)), np.nan)
    for r in read_csv(input_dir / "spreads.csv"):
        sp[int(r["scen_id"]) - 1, int(r["t"]), sids.index(r["spread_id"])] = float(r["spread"])
    check_array(d.sp_arr(), sp, "sp")
    assert d.n_spread_ids() == len(sids)


@pytest.mark.parametrize("input_dir", [DEMO, COVERAGE], ids=["demo", "coverage"])
def test_node_csr_and_tenor_resolution(m, input_dir):
    """Nodes are grouped per (scen, t) in node order; a tenor node is val_date(t) + Period (pureql)."""
    input_dir = pathlib.Path(input_dir)
    d = using(m, input_dir)
    vds = {int(r["t"]): r["val_date"] for r in read_csv(input_dir / "valuation_dates.csv")}
    groups = {}
    for r in read_csv(input_dir / "curve_nodes.csv"):
        groups.setdefault((int(r["scen_id"]) - 1, int(r["t"])), []).append(r)
    lo, cnt, dates, rates = d.n_lo_arr(), d.n_cnt_arr(), d.n_date_arr(), d.n_rate_arr()
    for a, name in ((lo, "n_lo"), (cnt, "n_cnt"), (dates, "n_date"), (rates, "n_rate")):
        assert a.dtype == (np.float64 if name in FLOAT_ARRAYS else np.int64) and a.flags["C_CONTIGUOUS"]
    assert lo.shape == cnt.shape == (d.n_scen(), d.n_times())
    n_tenor = 0
    pos = 0
    for s in range(d.n_scen()):
        for t in range(d.n_times()):
            rows = sorted(groups.get((s, t), []), key=lambda r: int(r["node"]))
            assert cnt[s, t] == len(rows)
            if rows:
                assert lo[s, t] == pos
            for k, r in enumerate(rows):
                if r["date"]:
                    expected = pq_serial_of(r["date"])
                else:
                    n, unit = int(r["tenor"][:-1]), UNITS[r["tenor"][-1].upper()]
                    expected = serial(pq_date(pq_serial_of(vds[t])) + pq_period(n, unit))
                    n_tenor += 1
                assert dates[lo[s, t] + k] == expected
                assert rates[lo[s, t] + k] == float(r["rate"])
            pos += len(rows)
    assert pos == len(dates) == len(rates) == d.n_nodes_total()
    assert n_tenor > 0


def test_month_end_tenor_nodes_resolve_like_pureql(m, tmp_path):
    """Tenor nodes from a month-end valuation date (31 Jan, leap February) against Date + Period."""
    for p in DEMO.glob("*.csv"):
        shutil.copy(p, tmp_path)
    write_csv(tmp_path / "valuation_dates.csv", [dict(t="0", val_date="2016-01-31"),
                                                 dict(t="1", val_date="2016-02-29")])
    write_csv(tmp_path / "curve_params.csv", [dict(scen_id=str(s), t=str(t), curve_type="ZeroCurve",
                                                   day_counter="Actual365Fixed")
                                              for s in (1, 2) for t in (0, 1)])
    tenors = ["0D", "1D", "1W", "2W", "1M", "3M", "6M", "1Y", "4Y", "30Y"]
    write_csv(tmp_path / "curve_nodes.csv", [dict(scen_id=str(s), t=str(t), node=str(k), tenor=tn, rate="0.01")
                                             for s in (1, 2) for t in (0, 1) for k, tn in enumerate(tenors)])
    write_csv(tmp_path / "spreads.csv", [dict(scen_id=str(s), t=str(t), spread_id=sid, spread="0.01")
                                         for s in (1, 2) for t in (0, 1) for sid in ("IG", "HY")])
    d = using(m, tmp_path)
    assert d.check_inputs() is True
    for s in range(2):
        for t, v in enumerate(("2016-01-31", "2016-02-29")):
            for k, tn in enumerate(tenors):
                exp = serial(pq_date(pq_serial_of(v)) + pq_period(int(tn[:-1]), UNITS[tn[-1]]))
                assert d.n_date_arr()[d.n_lo_arr()[s, t] + k] == exp, (v, tn)


@pytest.mark.parametrize("input_dir", [DEMO, COVERAGE], ids=["demo", "coverage"])
def test_every_array_cells_has_the_contract_shape(m, input_dir):
    d = using(m, input_dir)
    N, S, T, K = d.n_bonds(), d.n_scen(), d.n_times(), d.n_spread_ids()
    for name in d.cells:
        if not name.endswith("_arr"):
            continue
        a = d.cells[name]()
        assert isinstance(a, np.ndarray) and a.flags["C_CONTIGUOUS"], name
        assert a.dtype in (np.int64, np.float64), name
        if name.startswith("b_") or name in ("cr_lo_arr", "cr_cnt_arr"):
            assert a.shape == (N,), name
        elif name.startswith("c_") or name in ("n_lo_arr", "n_cnt_arr"):
            assert a.shape == (S, T), name
        elif name == "sp_arr":
            assert a.shape == (S, T, K)
        elif name == "val_date_arr":
            assert a.shape == (T,)
        elif name in ("px_slot_arr", "yl_slot_arr"):  # contract 4.8: the sparse quote slots
            assert a.shape == (S, T), name
        elif name in ("px_val_arr", "px_type_arr"):
            assert a.shape == (int((np.asarray(d.px_slot_arr()) >= 0).sum()), N), name
        elif name == "yl_val_arr":
            assert a.shape == (int((np.asarray(d.yl_slot_arr()) >= 0).sum()), N), name
        else:
            assert a.ndim == 1, name
    assert type(d.n_bonds()) is int and type(d.n_scen()) is int and type(d.n_nodes_total()) is int


# ----------------------------------------------------------------------------- check_inputs

def test_check_inputs_passes_on_the_demo_inputs(data):
    assert data.check_inputs() is True


def test_check_inputs_passes_on_the_coverage_inputs(m):
    assert using(m, COVERAGE).check_inputs() is True


def test_check_inputs_passes_on_generated_inputs(m, tmp_path):
    gen.write_tables(tmp_path, gen.generate(500, 3, 6, 11, step="3M"))
    assert using(m, tmp_path).check_inputs() is True


def write_csv(path, rows, columns=None):
    columns = columns or list(dict.fromkeys(k for r in rows for k in r))
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(columns)
        for r in rows:
            w.writerow([r.get(c, "") for c in columns])


def mutate(tmp_path, fname, fn, columns=None):
    """Copy the demo inputs to tmp_path and apply ``fn(rows) -> rows`` to ``fname``."""
    for p in DEMO.glob("*.csv"):
        shutil.copy(p, tmp_path)
    path = tmp_path / fname
    rows = read_csv(path)
    original = list(rows[0].keys())
    rows = fn(rows)
    write_csv(path, rows, columns or (list(dict.fromkeys(k for r in rows for k in r)) if rows else original))
    return tmp_path


def set_field(key, col, value, keycol="bond_key"):
    def fn(rows):
        for r in rows:
            if r[keycol] == key:
                r[col] = value
        return rows
    return fn


def where(pred, col, value):
    def fn(rows):
        for r in rows:
            if pred(r):
                r[col] = value
        return rows
    return fn


BAD_INPUTS = [
    ("bonds.csv", set_field("HEADLINE_10Y", "calendar", "UnitedKingdom"),
     r"bonds.csv line 2 \(bond_key 'HEADLINE_10Y'\): calendar: unknown or unsupported calendar 'UnitedKingdom'"),
    ("bonds.csv", set_field("HEADLINE_10Y", "accrual_day_counter", "ActualActual.ISDA"),
     r"accrual_day_counter: unknown or unsupported day counter 'ActualActual.ISDA'"),
    ("bonds.csv", set_field("HEADLINE_10Y", "rule", "Forward"),
     r"HEADLINE_10Y'\): rule Forward is not supported in this model version"),
    ("bonds.csv", set_field("HEADLINE_10Y", "effective_date", ""),
     r"HEADLINE_10Y'\): effective_date is required for a FixedRate bond"),
    ("bonds.csv", set_field("HEADLINE_10Y", "tenor", ""), r"tenor is required for a FixedRate bond"),
    ("bonds.csv", set_field("HEADLINE_10Y", "tenor", "6"), r"tenor: invalid tenor '6'"),
    ("bonds.csv", set_field("HEADLINE_10Y", "coupon_rate", ""), r"no coupon rate"),
    ("bonds.csv", set_field("EUR_ISMA_STEPUP_FWD", "coupon_rate", "0.02"),
     r"coupon rates given both in coupon_rate and in coupon_rates.csv"),
    ("bonds.csv", set_field("HEADLINE_10Y", "termination_date", "2015-09-15"),
     r"effective_date 2015-09-15 is not earlier than termination_date 2015-09-15"),
    ("bonds.csv", set_field("HEADLINE_10Y", "issue_date", "1900-06-01"),
     r"issue_date: date 1900-06-01 outside 1901-01-01..2199-12-31"),
    ("bonds.csv", set_field("HEADLINE_10Y", "first_date", "2015-31-01"), r"first_date: invalid date '2015-31-01'"),
    ("bonds.csv", set_field("ZCB_10Y", "maturity_date", ""), r"maturity_date is required for a ZeroCoupon bond"),
    ("bonds.csv", set_field("ZCB_10Y", "bond_type", "Amortizing"), r"unsupported bond type 'Amortizing'"),
    ("bonds.csv", set_field("ZCB_10Y", "bond_key", "HEADLINE_10Y"),
     r"line 6 \(bond_key 'HEADLINE_10Y'\): duplicate bond_key \(first on line 2\)"),
    ("bonds.csv", set_field("ZCB_10Y", "settlement_days", "9"), r"settlement_days 9 outside 0..MAX_SETTLE_DAYS"),
    ("bonds.csv", set_field("ZCB_10Y", "face_amount", "100,000"), r"face_amount: invalid number '100,000'"),
    ("bonds.csv", set_field("ZCB_10Y", "yield_frequency", "NoFrequency"),
     r"yield_frequency NoFrequency is not allowed with yield_compounding Compounded"),
    ("bonds.csv", set_field("HEADLINE_10Y", "yield_frequency", "Once"),
     r"yield_frequency Once is not allowed with yield_compounding Compounded"),
    ("bonds.csv", set_field("HEADLINE_10Y", "end_of_month", "yes"), r"end_of_month: invalid flag 'yes'"),
    ("bonds.csv", set_field("HEADLINE_10Y", "spread_id", "NOPE"),
     r"spread_id 'NOPE' \(used by bond 'HEADLINE_10Y'\) has no spread at \(scen_id, t\) \(1, 0\)"),
    ("bonds.csv", lambda rows: [{k: v for k, v in r.items() if k != "calendar"} for r in rows],
     r"bonds.csv: missing required column\(s\): calendar"),
    ("coupon_rates.csv", lambda rows: rows[:2] + rows[3:], r"k must run 0, 1, ..., 3 without gaps"),
    ("coupon_rates.csv", lambda rows: rows + [dict(bond_key="ZCB_10Y", k="0", rate="0.01")],
     r"coupon rates given for a bond that is not FixedRate"),
    ("coupon_rates.csv", lambda rows: rows + [dict(bond_key="GHOST", k="0", rate="0.01")],
     r"bond_key not in bonds.csv"),
    ("valuation_dates.csv", where(lambda r: r["t"] == "2", "val_date", "2016-03-16"),
     r"val_date of t=2 is not later than that of t=1 \(valuation dates must be strictly increasing\)"),
    ("valuation_dates.csv", where(lambda r: r["t"] == "3", "t", "4"), r"t 4 outside 0..3"),
    ("valuation_dates.csv", lambda rows: [], r"valuation_dates.csv: no valuation dates"),
    ("curve_params.csv", lambda rows: [r for r in rows if not (r["scen_id"] == "2" and r["t"] == "1")],
     r"the \(scen_id, t\) grid 1..2 x 0..3 is not dense; missing: \(2, 1\)"),
    ("curve_params.csv", lambda rows: rows + [dict(rows[0])], r"duplicate \(scen_id, t\) \(first on line 2\)"),
    ("curve_params.csv", where(lambda r: r["scen_id"] == "1" and r["t"] == "0", "flat_rate", ""),
     r"flat_rate is required for a FlatForward curve"),
    ("curve_params.csv", where(lambda r: r["scen_id"] == "1" and r["t"] == "0", "curve_type", "NelsonSiegel"),
     r"curve_type: unknown or unsupported curve type 'NelsonSiegel'"),
    ("curve_params.csv", where(lambda r: r["scen_id"] == "1" and r["t"] == "0", "day_counter", "Business252"),
     r"day_counter: unknown or unsupported day counter 'Business252'"),
    ("curve_params.csv", where(lambda r: r["scen_id"] == "1" and r["t"] == "3", "frequency", "NoFrequency"),
     r"\(scen_id 1, t 3\): frequency NoFrequency is not allowed with compounding Compounded"),
    ("curve_params.csv", where(lambda r: r["scen_id"] == "2" and r["t"] == "1", "spread_compounding",
                               "SimpleThenCompounded"),
     r"spread_frequency \(blank: NoFrequency\) is not allowed with spread_compounding SimpleThenCompounded"),
    ("curve_params.csv", where(lambda r: r["scen_id"] == "2" and r["t"] == "0", "extrapolate", "maybe"),
     r"extrapolate: invalid flag 'maybe'"),
    ("curve_params.csv", where(lambda r: r["scen_id"] == "2" and r["t"] == "3", "t", "7"),
     r"t outside 0..3 \(the rows of valuation_dates.csv\)"),
    ("curve_nodes.csv", lambda rows: [r for r in rows if not (r["scen_id"] == "2" and r["t"] == "0"
                                                              and r["node"] != "0")],
     r"\(scen_id 2, t 0, ZeroCurve\): a ZeroCurve needs at least 2 nodes \(got 1\)"),
    ("curve_nodes.csv", where(lambda r: r["scen_id"] == "2" and r["t"] == "0" and r["node"] == "0",
                              "date", "2015-09-17"),
     r"\(scen_id 2, t 0, ZeroCurve\): node 0 must be the valuation date"),
    ("curve_nodes.csv", where(lambda r: r["scen_id"] == "2" and r["t"] == "0" and r["node"] == "3",
                              "date", "2016-01-01"),
     r"\(scen_id 2, t 0, ZeroCurve\): node dates must be strictly increasing \(node 3"),
    ("curve_nodes.csv", where(lambda r: r["scen_id"] == "1" and r["t"] == "1" and r["node"] == "4",
                              "node", "40"),
     r"\(scen_id 1, t 1, ZeroCurve\): node numbers must run 0, 1, ..., k-1"),
    ("curve_nodes.csv", where(lambda r: r["scen_id"] == "1" and r["t"] == "1" and r["node"] == "2",
                              "date", "2017-03-16"),
     r"\(scen_id 1, t 1, node 2\): give exactly one of date and tenor"),
    ("curve_nodes.csv", where(lambda r: r["scen_id"] == "1" and r["t"] == "1" and r["node"] == "2",
                              "tenor", "1Q"),
     r"\(scen_id 1, t 1, node 2\): tenor: invalid tenor '1Q'"),
    ("curve_nodes.csv", where(lambda r: r["scen_id"] == "1" and r["t"] == "1" and r["node"] == "8",
                              "tenor", "200Y"),
     r"tenor 200Y from val_date"),
    ("curve_nodes.csv", where(lambda r: r["scen_id"] == "1" and r["t"] == "1" and r["node"] == "2",
                              "rate", ""),
     r"rate: invalid number ''"),
    ("curve_nodes.csv", lambda rows: rows + [dict(scen_id="3", t="0", node="0", date="2015-09-16", tenor="",
                                                  rate="0.01")],
     r"\(scen_id 3, t 0, node 0\): \(scen_id, t\) is not in the curve_params.csv grid"),
    ("spreads.csv", lambda rows: [r for r in rows if not (r["scen_id"] == "2" and r["t"] == "3"
                                                          and r["spread_id"] == "HY")],
     r"spread_id 'HY' \(used by bond 'NULL_A365F_LONGFIRST'\) has no spread at \(scen_id, t\) \(2, 3\)"),
    ("spreads.csv", lambda rows: rows + [dict(rows[0])], r"duplicate \(scen_id, t, spread_id\)"),
    ("spreads.csv", where(lambda r: r["scen_id"] == "1" and r["t"] == "0", "spread", "abc"),
     r"spread: invalid number 'abc'"),
    ("prices.csv", lambda rows: [dict(scen_id="1", t="0", bond_key="HEADLINE_10Y", price="101", price_type="Mid"),
                                 dict(scen_id="1", t="9", bond_key="GHOST", price="x", price_type="")],
     r"price_type: unknown price type 'Mid'(.|\n)*prices.csv line 3: bond_key 'GHOST' not in bonds.csv"),
    ("yields.csv", lambda rows: [{"scen_id": "1", "t": "0", "bond_key": "ZCB_10Y", "yield": "0.03"},
                                 {"scen_id": "1", "t": "0", "bond_key": "ZCB_10Y", "yield": "0.03"}],
     r"yields.csv line 3: duplicate \(scen_id, t, bond_key\)"),
]


@pytest.mark.parametrize("fname,fn,pattern", BAD_INPUTS, ids=[f"{i:02d}-{b[0]}" for i, b in enumerate(BAD_INPUTS)])
def test_check_inputs_rejects_bad_inputs(m, tmp_path, fname, fn, pattern):
    cols = {"prices.csv": ["scen_id", "t", "bond_key", "price", "price_type"],
            "yields.csv": ["scen_id", "t", "bond_key", "yield"]}.get(fname)
    if fname in ("prices.csv", "yields.csv"):
        for p in DEMO.glob("*.csv"):
            shutil.copy(p, tmp_path)
        write_csv(tmp_path / fname, fn([]), cols)
    else:
        mutate(tmp_path, fname, fn)
    d = using(m, tmp_path)
    assert_value_error(d.check_inputs, r"invalid inputs in .* \(\d+ problem\(s\)\):(.|\n)*" + pattern)


def test_check_inputs_reports_a_missing_required_file(m, tmp_path):
    for p in DEMO.glob("*.csv"):
        if p.name != "curve_params.csv":
            shutil.copy(p, tmp_path)
    assert_value_error(using(m, tmp_path).check_inputs, r"curve_params.csv: input file not found")


def test_check_inputs_lists_every_problem_of_a_stage(m, tmp_path):
    def fn(rows):
        rows[0]["calendar"] = "Mars"
        rows[1]["face_amount"] = "lots"
        rows[2]["payment_convention"] = "Sometimes"
        return rows
    mutate(tmp_path, "bonds.csv", fn)
    with pytest.raises((ValueError, mx.core.errors.FormulaError)) as ei:
        using(m, tmp_path).check_inputs()
    text = str(ei.value)
    assert "(3 problem(s))" in text
    for part in ("calendar 'Mars'", "invalid number 'lots'", "business day convention 'Sometimes'"):
        assert part in text


def test_array_cells_name_the_line_of_a_bad_value(m, tmp_path):
    mutate(tmp_path, "bonds.csv", set_field("ZCB_10Y", "calendar", "Mars"))
    assert_value_error(using(m, tmp_path).b_calendar_arr,
                       r"bonds.csv line 6 \(bond_key 'ZCB_10Y'\): unknown or unsupported calendar 'Mars'")


def test_sp_arr_is_nan_where_a_spread_is_absent(m, tmp_path):
    mutate(tmp_path, "spreads.csv", lambda rows: [r for r in rows if not (r["scen_id"] == "2" and r["t"] == "1"
                                                                          and r["spread_id"] == "IG")])
    d = using(m, tmp_path)
    ig = d.spread_ids().index("IG")
    assert math.isnan(d.sp_arr()[1, 1, ig])
    assert d.sp_arr()[1, 0, ig] == 0.0085


# ----------------------------------------------------------------------------- demo inputs vs pureql

def demo_bond(key, input_dir=DEMO):
    rows = {r["bond_key"]: r for r in read_csv(pathlib.Path(input_dir) / "bonds.csv")}
    vec = [float(r["rate"]) for r in sorted(read_csv(pathlib.Path(input_dir) / "coupon_rates.csv"),
                                            key=lambda r: int(r["k"])) if r["bond_key"] == key]
    return gen.pureql_bond(rows[key], vec)


def test_demo_headline_row_is_the_readme_bond():
    """bonds.csv HEADLINE_10Y on the (1, 0) curve reproduces the quantlib-migration README figures with pureql."""
    bond = demo_bond("HEADLINE_10Y")
    cps = {(r["scen_id"], r["t"]): r for r in read_csv(DEMO / "curve_params.csv")}
    cp = cps[("1", "0")]
    today = pq_date(pq_serial_of(read_csv(DEMO / "valuation_dates.csv")[0]["val_date"]))
    old = ql.Settings.instance().evaluationDate()
    try:
        ql.Settings.instance().setEvaluationDate(today)
        curve = ql.FlatForward(today, float(cp["flat_rate"]), pq_daycounter(DAY_COUNTERS[cp["day_counter"]]))
        bond.setPricingEngine(ql.DiscountingBondEngine(ql.Handle(curve)))
        assert bond.NPV() == 108.36776235612268
        assert bond.cleanPrice() == 108.34563953853349
        assert len(bond.cashflows()) == 21
    finally:
        ql.Settings.instance().setEvaluationDate(old)


def test_demo_cached_zero_rows_are_the_bonds_cpp_bonds():
    """bonds.cpp testCachedZero: the three ZCB rows give the cached clean prices with pureql (1e-6, as upstream)."""
    today = ql.Date(22, ql.Month(11), 2004)
    old = ql.Settings.instance().evaluationDate()
    try:
        ql.Settings.instance().setEvaluationDate(today)
        curve = ql.FlatForward(today, 0.03, Actual360())
        for key, cached in (("ZCB_2008", 88.551726), ("ZCB_2007", 91.278949), ("ZCB_2006", 94.098006)):
            bond = demo_bond(key)
            bond.setPricingEngine(ql.DiscountingBondEngine(ql.Handle(curve)))
            assert abs(bond.cleanPrice() - cached) <= 1.0e-6, key
    finally:
        ql.Settings.instance().setEvaluationDate(old)


def test_demo_zcb_10y_quotes_are_the_tracer_case():
    """tracer_bonds.json zcb-10y on the (1, 0) flat curve: the demo's price quote and spread conventions give
    the golden z-spread with pureql (solver accuracy; the golden is QuantLib 1.41's)."""
    bond = demo_bond("ZCB_10Y")
    cp = {(r["scen_id"], r["t"]): r for r in read_csv(DEMO / "curve_params.csv")}[("1", "0")]
    quote = {(r["scen_id"], r["t"], r["bond_key"]): r for r in read_csv(DEMO / "prices.csv")}[("1", "0", "ZCB_10Y")]
    today = ql.Date(16, ql.Month(9), 2015)
    old = ql.Settings.instance().evaluationDate()
    try:
        ql.Settings.instance().setEvaluationDate(today)
        curve = ql.FlatForward(today, float(cp["flat_rate"]), ql.Actual365Fixed())
        bond.setPricingEngine(ql.DiscountingBondEngine(ql.Handle(curve)))
        assert bond.NPV() == 74.0635575694049
        z = ql.BondFunctions.zSpread(bond, ql.Bond.Price(float(quote["price"]), ql.Bond.Price.Type.Clean), curve,
                                     getattr(ql.Compounding, cp["spread_compounding"]),
                                     getattr(ql.Frequency, cp["spread_frequency"]))
        assert abs(z - -0.007876841509350115) < 1e-11
    finally:
        ql.Settings.instance().setEvaluationDate(old)


@pytest.mark.parametrize("input_dir", [DEMO, COVERAGE], ids=["demo", "coverage"])
def test_input_bonds_construct_in_pureql(input_dir):
    tables = {name: (None, read_csv(pathlib.Path(input_dir) / name)) for name in ("bonds.csv", "coupon_rates.csv")}
    for _, row in enumerate(tables["bonds.csv"][1]):
        for c in gen.BOND_COLUMNS:
            row.setdefault(c, "")
    assert gen.validate(tables) is True


def price_with_pureql(input_dir):
    """Every bond at every (scen, t) on the input curve (plain or spreaded), with pureql: NPV, clean
    price when tradable, and the z-spread of every price quote. Returns the number of z-spreads solved."""
    from pureql.math.interpolations.linearinterpolation import Linear
    from pureql.termstructures.yield_.zerocurve import ZeroCurve
    from pureql.termstructures.yield_.zerospreadedtermstructure import ZeroSpreadedTermStructure

    input_dir = pathlib.Path(input_dir)
    bonds = read_csv(input_dir / "bonds.csv")
    vds = read_csv(input_dir / "valuation_dates.csv")
    nodes = read_csv(input_dir / "curve_nodes.csv")
    spreads = {(r["scen_id"], r["t"], r["spread_id"]): float(r["spread"]) for r in read_csv(input_dir / "spreads.csv")}
    prices = {(r["scen_id"], r["t"], r["bond_key"]): r for r in read_csv(input_dir / "prices.csv")}
    pq = {b["bond_key"]: demo_bond(b["bond_key"], input_dir) for b in bonds}
    comp = lambda s, dflt: getattr(ql.Compounding, s or dflt)  # noqa: E731
    freq = lambda s, dflt: getattr(ql.Frequency, s or dflt)  # noqa: E731
    solved = 0
    old = ql.Settings.instance().evaluationDate()
    try:
        for cp in read_csv(input_dir / "curve_params.csv"):
            s, t = cp["scen_id"], cp["t"]
            v = pq_date(pq_serial_of(vds[int(t)]["val_date"]))
            ql.Settings.instance().setEvaluationDate(v)
            dc = pq_daycounter(DAY_COUNTERS[cp["day_counter"]])
            if cp["curve_type"] == "FlatForward":
                curve = ql.FlatForward(v, float(cp["flat_rate"]), dc, comp(cp["compounding"], "Continuous"),
                                       freq(cp["frequency"], "Annual"))
            else:
                nd = sorted((r for r in nodes if (r["scen_id"], r["t"]) == (s, t)), key=lambda r: int(r["node"]))
                ds = [pq_date(pq_serial_of(r["date"])) if r["date"]
                      else v + pq_period(int(r["tenor"][:-1]), UNITS[r["tenor"][-1]]) for r in nd]
                curve = ZeroCurve(ds, [float(r["rate"]) for r in nd], dc, ql.NullCalendar(), Linear(),
                                  comp(cp["compounding"], "Continuous"), freq(cp["frequency"], "Annual"))
            if cp["extrapolate"] == "1":
                curve.enableExtrapolation()
            for b in bonds:
                bond = pq[b["bond_key"]]
                h = ql.Handle(curve)
                if b["spread_id"]:
                    zs = ZeroSpreadedTermStructure(h, ql.Handle(ql.SimpleQuote(spreads[(s, t, b["spread_id"])])),
                                                   comp(cp["spread_compounding"], "Continuous"),
                                                   freq(cp["spread_frequency"], "NoFrequency"))
                    if cp["extrapolate"] == "1":
                        zs.enableExtrapolation()
                    h = ql.Handle(zs)
                bond.setPricingEngine(ql.DiscountingBondEngine(h))
                assert math.isfinite(bond.NPV())
                if bond.notional(bond.settlementDate()) != 0:
                    assert math.isfinite(bond.cleanPrice())
                q = prices.get((s, t, b["bond_key"]))
                if q:
                    kind = ql.Bond.Price.Type.Dirty if q["price_type"] == "Dirty" else ql.Bond.Price.Type.Clean
                    z = ql.BondFunctions.zSpread(bond, ql.Bond.Price(float(q["price"]), kind), curve,
                                                 comp(cp["spread_compounding"], "Continuous"),
                                                 freq(cp["spread_frequency"], "NoFrequency"))
                    assert math.isfinite(z)
                    solved += 1
    finally:
        ql.Settings.instance().setEvaluationDate(old)
    return solved


def test_coverage_inputs_price_in_pureql_at_every_scenario_and_date():
    """The mx2cy sample must raise nothing: every bond prices on every (scen, t) curve, and every quote solves."""
    assert price_with_pureql(COVERAGE) == len(read_csv(COVERAGE / "prices.csv"))


def test_demo_inputs_price_in_pureql_at_every_scenario_and_date():
    assert price_with_pureql(DEMO) == len(read_csv(DEMO / "prices.csv"))


# ----------------------------------------------------------------------------- generate_inputs.py

def test_generate_inputs_is_deterministic(tmp_path):
    args = ["--n-bonds", "200", "--n-scen", "2", "--n-times", "5", "--seed", "42"]
    assert gen.main(args + ["--out", str(tmp_path / "a")]) == 0
    assert gen.main(args + ["--out", str(tmp_path / "b")]) == 0
    assert gen.main(args[:-1] + ["43", "--out", str(tmp_path / "c")]) == 0
    names = sorted(p.name for p in (tmp_path / "a").iterdir())
    assert names == ["bonds.csv", "coupon_rates.csv", "curve_nodes.csv", "curve_params.csv", "spreads.csv",
                     "valuation_dates.csv"]
    for n in names:
        assert (tmp_path / "a" / n).read_bytes() == (tmp_path / "b" / n).read_bytes(), n
    assert (tmp_path / "a" / "bonds.csv").read_bytes() != (tmp_path / "c" / "bonds.csv").read_bytes()
    assert len(read_csv(tmp_path / "a" / "bonds.csv")) == 200
    assert len(read_csv(tmp_path / "a" / "curve_params.csv")) == 10


def test_sample_inputs_are_the_generated_coverage_set(tmp_path):
    """tools/cy/sample_inputs is exactly what ``generate_inputs.py --coverage`` writes."""
    assert gen.main(["--coverage", "--out", str(tmp_path)]) == 0
    names = sorted(p.name for p in tmp_path.iterdir())
    assert names == sorted(p.name for p in COVERAGE.glob("*.csv"))
    for n in names:
        assert (tmp_path / n).read_bytes() == (COVERAGE / n).read_bytes(), n


def test_coverage_inputs_cover_the_v1_conventions(m):
    bonds = read_csv(COVERAGE / "bonds.csv")
    cps = read_csv(COVERAGE / "curve_params.csv")
    vds = [pq_serial_of(r["val_date"]) for r in read_csv(COVERAGE / "valuation_dates.csv")]
    fixed = [b for b in bonds if b["bond_type"] == "FixedRate"]
    assert {b["bond_type"] for b in bonds} == {"FixedRate", "ZeroCoupon"}
    assert {b["calendar"] for b in bonds} == set(CALENDARS)
    assert {b["payment_calendar"] for b in bonds} - {""} == set(CALENDARS)
    assert {b["accrual_day_counter"] for b in fixed} == set(DAY_COUNTERS)
    assert {c["day_counter"] for c in cps} >= {"Actual360", "Actual365Fixed", "Thirty360.USA"}
    assert {b["convention"] for b in fixed} == set(ql.BusinessDayConvention.__members__)
    assert {b["payment_convention"] for b in bonds} - {""} == set(ql.BusinessDayConvention.__members__)
    assert {b["settlement_days"] for b in bonds} == {"0", "1", "2", "3"}
    assert {b["tenor"] for b in fixed} >= {"0D", "1M", "3M", "6M", "1Y", "2W"}
    assert any(b["first_date"] for b in fixed) and any(b["next_to_last_date"] for b in fixed)
    assert any(b["end_of_month"] == "1" for b in fixed)
    assert any(b["first_period_day_counter"] for b in fixed)
    assert any(b["spread_id"] for b in bonds) and any(not b["spread_id"] for b in bonds)
    assert any(pq_serial_of(b["issue_date"]) > vds[0] for b in bonds), "a forward-start bond"
    matured = [b for b in bonds if b["bond_type"] == "FixedRate" and pq_serial_of(b["termination_date"]) < vds[-1]]
    assert matured and any(b["bond_type"] == "ZeroCoupon" and pq_serial_of(b["maturity_date"]) < vds[-1]
                           for b in bonds)
    every_comp = set(ql.Compounding.__members__)
    assert {c["compounding"] or "Continuous" for c in cps} == every_comp
    assert {c["spread_compounding"] or "Continuous" for c in cps} == every_comp
    assert {b["yield_compounding"] or "Compounded" for b in bonds} == every_comp
    assert {c["curve_type"] for c in cps} == {"ZeroCurve", "FlatForward"}
    assert {c["extrapolate"] for c in cps} == {"0", "1"}
    nodes = read_csv(COVERAGE / "curve_nodes.csv")
    assert any(r["date"] for r in nodes) and any(r["tenor"] for r in nodes)
    assert len({(c["scen_id"], c["t"]) for c in cps}) == 8 and len(vds) == 4
    assert read_csv(COVERAGE / "coupon_rates.csv") and read_csv(COVERAGE / "prices.csv")
    assert {r["price_type"] or "Clean" for r in read_csv(COVERAGE / "prices.csv")} == {"Clean", "Dirty"}
    assert read_csv(COVERAGE / "yields.csv")
    d = using(m, COVERAGE)
    assert d.check_inputs() is True and d.n_scen() == 2 and d.n_times() == 4


def test_generated_bonds_construct_in_pureql():
    assert gen.validate(gen.generate(400, 1, 1, 3)) is True


@pytest.mark.slow
@pytest.mark.parametrize("seed", [101, 102, 103])
def test_generated_bonds_construct_in_pureql_sweep(seed):
    assert gen.validate(gen.generate(12000, 1, 1, seed)) is True


@pytest.mark.slow
def test_check_inputs_on_a_full_size_generated_portfolio(tmp_path):
    gen.write_tables(tmp_path, gen.generate(12000, 3, 121, 9))
    m = mx.read_model(MODEL_DIR, name="BondPortfolio_test_data_big")
    try:
        d = using(m, tmp_path)
        assert d.check_inputs() is True
        assert d.n_bonds() == 12000 and d.sp_arr().shape == (3, 121, 5)
        for name, values in expected_bond_arrays(tmp_path).items():
            check_array(getattr(d, name + "_arr")(), values, name)
    finally:
        m.close()


@pytest.mark.slow
def test_generated_inputs_price_in_pureql(tmp_path):
    gen.write_tables(tmp_path, gen.generate(150, 2, 4, 21, step="1Y"))
    price_with_pureql(tmp_path)
