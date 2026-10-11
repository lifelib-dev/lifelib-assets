"""Calibrate z-spreads at t = 0 with the MODEL, and write an input set that feeds them forward.

    python tools/calibrate_spreads.py --inputs DIR --out DIR [--mode modelx|export|compiled] [--scen K]

DECISIONS.md D-4: spreads are calibrated at t = 0 by the model itself, never by
pureql, and fed forward to every valuation date.

1. The model (``bond_portfolio/run.py``'s loader, so any of the three modes)
   reads ``--inputs`` and runs ``Data.check_inputs()``; the solver error
   policy is ``ERR_RAISE``, so a failed solve stops the tool with pureql's
   message and the bond's key.
2. Every bond with a price at t = 0 in ``prices.csv`` is solved for its
   z-spread, ``Valuation[scen_id, 0].zspread(b)``: Brent over the plain curve
   of (scen_id, 0), in that item's spread conventions (``spread_compounding``
   / ``spread_frequency`` of curve_params.csv), with the ``zspread_*``
   settings of ``Data``. Without ``--scen`` each scenario is calibrated at its
   own t = 0, and a bond priced at t = 0 must be priced there in every
   scenario. With ``--scen K`` the spreads solved at (K, 0) are given to every
   scenario. A bond that is not tradable at t = 0 (``zspread`` NaN) is left
   as it is, with a note.
3. ``--out`` receives a copy of the input set in which every calibrated bond
   has ``spread_id = bond_key`` in bonds.csv, and spreads.csv carries its
   spread at every (scen_id, t) (any earlier rows of that spread_id are
   replaced). The spreads are written with Python's shortest round-trip
   representation, so the model reads back exactly the solved doubles.
4. The output is checked: a fresh model on ``--out`` passes
   ``check_inputs()``, and at (scen_id, 0) every calibrated bond's engine
   price equals the price from its spread (``clean_from_z``) bit for bit;
   the largest difference from the quoted price is printed (it is the
   solver's accuracy, not zero).

A spread is a number in the conventions of each (scen_id, t): if the spread
conventions change over t, the same number means a different curve there.
"""

import argparse
import csv
import importlib.util
import math
import pathlib
import shutil
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
ERR_RAISE = 0
PRICE_CLEAN = 1
INPUT_FILES = ("bond_file", "coupon_rate_file", "val_date_file", "curve_param_file", "curve_node_file",
               "spread_file", "price_file", "yield_file")


def _run_module():
    spec = importlib.util.spec_from_file_location("bond_portfolio_run", ROOT / "bond_portfolio" / "run.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _new_model(mode, input_dir):
    """A fresh model in ``mode`` on ``input_dir`` with ``ERR_RAISE``; returns (model, unwrap, close)."""
    run = _run_module()
    m, unwrap = run.load(mode)
    m.Data.input_dir = str(pathlib.Path(input_dir).resolve())
    m.Data.solver_error_policy = ERR_RAISE

    def close():
        if mode == "modelx":
            m.close()

    return m, unwrap, close


def solve_spreads(m, unwrap, scen=None, log=print):
    """{(scen_id, bond_key): z} solved by the model at t = 0 (see the module docstring)."""
    import numpy as np

    S, N = int(m.Data.n_scen()), int(m.Data.n_bonds())
    keys = list(m.Data.bond_keys())
    slots = np.asarray(m.Data.px_slot_arr())
    vals = np.asarray(m.Data.px_val_arr())
    scens = list(range(1, S + 1)) if scen is None else [int(scen)]
    for s in scens:
        if not (1 <= s <= S):
            raise ValueError(f"--scen {s} outside 1..{S}")
    priced = {}
    for s in scens:
        slot = int(slots[s - 1, 0])
        priced[s] = [] if slot < 0 else [b for b in range(N) if not math.isnan(float(vals[slot, b]))]
    if scen is None and S > 1:
        everywhere = set(priced[1])
        anywhere = set(priced[1])
        for s in scens[1:]:
            everywhere &= set(priced[s])
            anywhere |= set(priced[s])
        partial = sorted(anywhere - everywhere)
        if partial:
            raise ValueError("bonds priced at t = 0 in some scenarios only (price them in every scenario, or "
                             "use --scen K to calibrate on one scenario): "
                             + ", ".join(keys[b] for b in partial[:20]) + (" ..." if len(partial) > 20 else ""))
    out = {}
    for s in scens:
        item = m.Valuation[s, 0]
        for b in priced[s]:
            try:
                z = float(item.zspread(b))
            except Exception as e:  # noqa: BLE001 - name the bond
                err = unwrap(e)
                raise ValueError(f"zspread of bond '{keys[b]}' at (scen_id {s}, t 0): {err}") from None
            if math.isnan(z):
                log(f"note: bond '{keys[b]}' is not tradable at (scen_id {s}, t 0); left uncalibrated")
                continue
            out[(s, keys[b])] = z
    if scen is not None:
        out = {(s, key): z for (k, key), z in out.items() for s in range(1, S + 1)}
    # a bond skipped in one scenario cannot be fed forward in the others
    by_key = {}
    for s, key in out:
        by_key.setdefault(key, set()).add(s)
    for key, ss in by_key.items():
        if len(ss) != S:
            raise ValueError(f"bond '{key}' could be calibrated in scenario(s) {sorted(ss)} only")
    return out


def write_input_set(m, inputs, out, spreads):
    """Copy the input set ``inputs`` to ``out`` with the calibrated ``spreads`` ({(scen_id, bond_key): z})."""
    inputs, out = pathlib.Path(inputs), pathlib.Path(out)
    out.mkdir(parents=True, exist_ok=True)
    names = {ref: str(getattr(m.Data, ref)) for ref in INPUT_FILES}
    for ref, name in names.items():
        if ref in ("bond_file", "spread_file"):
            continue
        if (inputs / name).exists():
            shutil.copyfile(inputs / name, out / name)
    keys = sorted({key for _, key in spreads})
    S, T = int(m.Data.n_scen()), int(m.Data.n_times())

    with open(inputs / names["bond_file"], newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        fields = list(reader.fieldnames)
        rows = list(reader)
    if "spread_id" not in fields:
        fields.append("spread_id")
    used = {}
    for r in rows:
        sid = (r.get("spread_id") or "").strip()
        if sid and r["bond_key"].strip() not in keys:
            used[sid] = r["bond_key"].strip()
    clash = [k for k in keys if k in used]
    if clash:
        raise ValueError("a calibrated bond_key is already the spread_id of another bond: "
                         + ", ".join(f"'{k}' (used by '{used[k]}')" for k in clash))
    for r in rows:
        if r["bond_key"].strip() in keys:
            r["spread_id"] = r["bond_key"].strip()
    with open(out / names["bond_file"], "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, lineterminator="\n")
        w.writeheader()
        for r in rows:
            w.writerow({k: ("" if r.get(k) is None else r[k]) for k in fields})

    sp_fields = ["scen_id", "t", "spread_id", "spread"]
    sp_rows = []
    if (inputs / names["spread_file"]).exists():
        with open(inputs / names["spread_file"], newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            sp_fields = list(reader.fieldnames)
            sp_rows = [r for r in reader if r["spread_id"].strip() not in keys]
    for key in keys:
        for s in range(1, S + 1):
            for t in range(T):
                row = {k: "" for k in sp_fields}
                row.update({"scen_id": str(s), "t": str(t), "spread_id": key, "spread": repr(spreads[(s, key)])})
                sp_rows.append(row)
    with open(out / names["spread_file"], "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=sp_fields, lineterminator="\n")
        w.writeheader()
        for r in sp_rows:
            w.writerow(r)


def verify(mode, out, spreads):
    """The largest |engine clean price - quoted clean price| at t = 0 of the calibrated bonds, after the bitwise checks."""
    m, unwrap, close = _new_model(mode, out)
    try:
        try:
            m.Data.check_inputs()
        except Exception as e:  # noqa: BLE001
            raise unwrap(e) from None
        keys = list(m.Data.bond_keys())
        worst = 0.0
        for (s, key), z in spreads.items():
            b = keys.index(key)
            v = m.Valuation[s, 0]
            if float(v.spread(b)) != z:
                raise AssertionError(f"bond '{key}' (scen_id {s}): the written spread does not read back exactly")
            cp, cz = float(v.clean_price(b)), float(v.clean_from_z(b, z))
            if cp != cz and not (math.isnan(cp) and math.isnan(cz)):
                raise AssertionError(f"bond '{key}' (scen_id {s}): engine clean price {cp!r} differs from "
                                     f"clean_from_z {cz!r}")
            px, typ = float(v.price_in(b)), int(v.price_type_in(b))
            quoted_clean = px if typ == PRICE_CLEAN else px - float(v.accrued_amount(b))
            worst = max(worst, abs(cp - quoted_clean))
        return worst
    finally:
        close()


def calibrate(inputs, out, mode="modelx", scen=None, log=print):
    """Calibrate at t = 0 and write the input set ``out``; return {(scen_id, bond_key): z}."""
    m, unwrap, close = _new_model(mode, inputs)
    try:
        try:
            m.Data.check_inputs()
            m.Legs.check_limits()
        except Exception as e:  # noqa: BLE001
            raise unwrap(e) from None
        spreads = solve_spreads(m, unwrap, scen, log)
        write_input_set(m, inputs, out, spreads)
    finally:
        close()
    if spreads:
        worst = verify(mode, out, spreads)
        log(f"calibrated {len({k for _, k in spreads})} bond(s); largest |clean price - quote| at t = 0: {worst:.3g}")
    else:
        log("no bond is priced at t = 0; the input set is copied unchanged")
    return spreads


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--inputs", required=True, help="directory of the input CSV files")
    ap.add_argument("--out", required=True, help="directory for the calibrated input set")
    ap.add_argument("--mode", choices=("modelx", "export", "compiled"), default="modelx")
    ap.add_argument("--scen", type=int, help="calibrate on scenario K only and give its spreads to every scenario")
    args = ap.parse_args(argv)
    if pathlib.Path(args.out).resolve() == pathlib.Path(args.inputs).resolve():
        print("calibrate_spreads.py: --out must differ from --inputs", file=sys.stderr)
        return 1
    try:
        spreads = calibrate(args.inputs, args.out, args.mode, args.scen)
    except ValueError as e:
        print(f"calibrate_spreads.py: {e}", file=sys.stderr)
        return 1
    for (s, key), z in sorted(spreads.items()):
        print(f"  scen_id {s}  {key}: {z!r}")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
