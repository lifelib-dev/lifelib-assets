"""The frozen QuantLib 1.41 goldens of quantlib-migration, replayed against the model's cash flows.

``tests/data/tracer_bonds.json`` is a verbatim copy of quantlib-migration's
``tests/data/tracer_bonds.json`` (provenance in
``tests/data/tracer_bonds.provenance.json``, checked below). Each frozen key
carries its tolerance tier: ``exact`` (==), ``value`` (T2: relative 1e-12,
absolute floor 1e-14) or ``solver`` (absolute 1e-11). The comparison reads
the tier from the file, as quantlib-migration's own replay does
(``tests/differential/test_bond_vs_oracle.py``).

Cases in v1 scope: ``zerocouponbond[zcb-10y,*]`` (TARGET, Following). The
other cases use a calendar (UnitedKingdom), a rule (Forward) or a day
counter (ActualActual.ISDA) outside v1. ``fixedratebond[frb-annual,*]`` is
the one Backward fixed-rate golden; its DATES do not depend on the day
counter, so it is replayed for its date and structure keys with the day
counter replaced by Actual365Fixed in the model input (amounts, accrual
periods and accrual days are not compared).

Oracle skew OS-02: QuantLib 1.41 hard-codes the regularity of the
effective-date stub of a backward schedule as False where v1.43 computes
it. ``isRegular`` itself is not frozen in these goldens; through
FixedRateLeg it could move the first coupon's reference start, but not for
frb-annual, whose schedule is Unadjusted and regular (the 1.41 reference
start ``end - 1Y`` is the accrual start).
"""

import hashlib
import json
import pathlib

import pytest

from cashflow_checks import DEMO, gen, model_leg_records, private_model
from helpers.approx import assert_t2
from helpers.model import MODEL_DIR

DATA = MODEL_DIR.parents[1] / "tests" / "data"
GOLDEN = DATA / "tracer_bonds.json"
PROVENANCE = DATA / "tracer_bonds.provenance.json"

#: Golden keys of the bond cases this phase (cash flows) replays; the rest are Phase 2+.
CASHFLOW_KEYS = {"settlementDays", "maturityDate", "issueDate", "notional", "cashflows"}
LATER_PHASE_KEYS = {
    "settlementDate", "startDate", "isExpired", "isTradable", "accruedAmount", "NPV", "settlementValue",
    "cleanPriceFromCurve", "dirtyPriceFromCurve", "yieldBrent", "yieldRidder", "durationSimple",
    "durationMacaulay", "durationModified", "convexity", "basisPointValue", "yieldValueBasisPoint",
    "bpsOnCurve", "zSpread", "cleanPriceFromZSpread", "atmRate", "atmRateError",
    "dirtyMinusCleanMinusAccrued",
}
#: Per-flow keys whose value does not depend on the day counter.
DATE_KEYS = ("date", "isCoupon", "accrualStartDate", "accrualEndDate", "referencePeriodStart",
             "referencePeriodEnd", "exCouponDate", "nominal", "rate")


@pytest.fixture(scope="module")
def golden():
    return json.loads(GOLDEN.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def m():
    model = private_model("GoldenTest")
    yield model
    model.close()


def iso(serial):
    import datetime
    return "" if serial == 0 else (datetime.date(1899, 12, 30) + datetime.timedelta(days=serial)).isoformat()


def compare(expected, actual, tier, what):
    if tier == "exact":
        assert actual == expected, f"{what}: model {actual!r} vs golden {expected!r}"
    elif tier == "value":
        if expected is None:
            assert actual is None, f"{what}: model {actual!r} vs golden None"
        else:
            assert_t2(actual, expected, f"{what} (T2)")
    else:
        raise AssertionError(f"{what}: tier {tier} is not used by the cash-flow keys")


def model_flows(mb):
    """The model leg in the shape of a golden ``cashflows`` entry."""
    out = []
    for rec in model_leg_records(mb):
        d, kind, amount, acc_s, acc_e, ref_s, ref_e, nominal, rate, ap = rec
        out.append({"date": iso(d), "amount": amount, "isCoupon": kind == 0,
                    "accrualStartDate": iso(acc_s), "accrualEndDate": iso(acc_e), "accrualPeriod": ap,
                    "rate": rate, "nominal": nominal, "exCouponDate": "",
                    "referencePeriodStart": iso(ref_s), "referencePeriodEnd": iso(ref_e)})
    return out


def test_golden_copy_is_the_recorded_one():
    prov = json.loads(PROVENANCE.read_text(encoding="utf-8"))
    assert hashlib.sha256(GOLDEN.read_bytes()).hexdigest() == prov["sha256"]
    qlm = MODEL_DIR.parents[2] / "quantlib-migration" / "tests" / "data" / "tracer_bonds.json"
    if qlm.exists():
        assert qlm.read_bytes() == GOLDEN.read_bytes(), "quantlib-migration's goldens moved on: re-copy them"


def test_golden_provenance_is_the_141_oracle(golden):
    assert golden["schema"] == "tracer-golden/1"
    assert golden["provenance"]["oracle_version"] == "1.41"
    assert golden["evaluationDate"] == "2015-09-16"


@pytest.mark.parametrize("curve", ["flat", "zero"])
def test_zcb_10y(golden, m, curve):
    """The demo row ZCB_10Y is the tracer zcb-10y bond; its cash-flow keys at their frozen tiers."""
    case = golden["cases"][f"bonds/zerocouponbond[zcb-10y,{curve}]"]
    params, result, tiers = case["params"], case["result"], case["tiers"]
    assert set(result) == CASHFLOW_KEYS | LATER_PHASE_KEYS

    m.Data.input_dir = str(DEMO)
    b = m.Data.bond_keys().index("ZCB_10Y")
    mb = m.Bond[b]
    # the fixture IS the bond the golden froze
    row = m.Data.bond_table().iloc[b]
    assert {
        "settlementDays": mb.settlement_days(), "calendar": row["calendar"], "faceAmount": mb.face_amount(),
        "maturityDate": iso(mb.maturity_in()), "paymentConvention": row["payment_convention"],
        "redemption": mb.redemption(), "issueDate": iso(mb.issue_date()),
    } == params["bond"]
    # and its yield-quote conventions are the golden's
    assert (row["yield_day_counter"], row["yield_compounding"], row["yield_frequency"]) == \
        (params["yieldDayCounter"], params["compounding"], params["frequency"])

    compare(result["settlementDays"], mb.settlement_days(), tiers["settlementDays"], "settlementDays")
    compare(result["maturityDate"], iso(mb.maturity_date()), tiers["maturityDate"], "maturityDate")
    compare(result["issueDate"], iso(mb.issue_date()), tiers["issueDate"], "issueDate")
    # notional(settlementDate): the frozen settlement date precedes the redemption date
    ns_dates, ns_notionals = mb.notional_schedule()
    assert result["settlementDate"] <= iso(ns_dates[1])
    compare(result["notional"], ns_notionals[0], tiers["notional"], "notional")

    flows = model_flows(mb)
    assert len(flows) == len(result["cashflows"]) == 1
    for i, (mf, gf) in enumerate(zip(flows, result["cashflows"])):
        for key, expected in gf.items():
            if key == "accrualDays":
                assert expected is None  # a redemption has none
                continue
            compare(expected, mf[key], tiers[f"cashflows.{i}.{key}"], f"cashflows.{i}.{key}")


@pytest.mark.parametrize("curve", ["flat", "zero"])
def test_frb_annual_dates(golden, m, tmp_path, curve):
    """frb-annual (Backward, TARGET, Unadjusted): every date and structure key of the leg.

    ActualActual.ISDA is outside v1, so the model is given Actual365Fixed; the
    dates, the coupon/redemption structure, the nominal and the rate do not
    depend on the day counter. Amounts and accrual periods are not compared.
    """
    case = golden["cases"][f"bonds/fixedratebond[frb-annual,{curve}]"]
    p, s, result, tiers = case["params"]["bond"], case["params"]["schedule"], case["result"], case["tiers"]
    assert s["rule"] == "DateGeneration.Backward" and p["dayCounter"] == "ActualActual.ISDA"
    row = dict.fromkeys(gen.BOND_COLUMNS, "")
    row.update({
        "bond_key": "frb-annual", "bond_type": "FixedRate", "face_amount": repr(p["faceAmount"]),
        "settlement_days": str(p["settlementDays"]), "calendar": s["calendar"], "issue_date": p["issueDate"],
        "redemption": repr(p["redemption"]), "effective_date": s["effectiveDate"],
        "termination_date": s["terminationDate"], "tenor": s["tenor"], "convention": s["convention"],
        "termination_convention": s["terminationDateConvention"], "rule": "Backward",
        "end_of_month": "1" if s["endOfMonth"] else "0", "coupon_rate": repr(p["coupons"][0]),
        "accrual_day_counter": "Actual365Fixed",  # substitute: ActualActual.ISDA is not in v1
        "payment_convention": p["paymentConvention"],
    })
    tables = gen.generate(1, 1, 1, 1)
    tables["bonds.csv"] = (gen.BOND_COLUMNS, [row])
    tables["coupon_rates.csv"] = (gen.COUPON_RATE_COLUMNS, [])
    gen.write_tables(tmp_path, tables)
    m.Data.input_dir = str(tmp_path)
    mb = m.Bond[0]

    compare(result["settlementDays"], mb.settlement_days(), tiers["settlementDays"], "settlementDays")
    compare(result["maturityDate"], iso(mb.maturity_date()), tiers["maturityDate"], "maturityDate")
    compare(result["issueDate"], iso(mb.issue_date()), tiers["issueDate"], "issueDate")
    flows = model_flows(mb)
    assert len(flows) == len(result["cashflows"]) == 11
    for i, (mf, gf) in enumerate(zip(flows, result["cashflows"])):
        for key in DATE_KEYS:
            compare(gf[key], mf[key], tiers[f"cashflows.{i}.{key}"], f"cashflows.{i}.{key}")
