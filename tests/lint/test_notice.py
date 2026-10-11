"""NOTICE.md: present, outside the model directory, and verbatim (docs/ATTRIBUTION_TEMPLATE.md)."""

import importlib.util
import pathlib

import pytest

from helpers.model import MODEL_DIR

ROOT = MODEL_DIR.parents[1]
QLM = ROOT.parent / "quantlib-migration"


def test_notice_is_at_the_project_root_not_in_the_model():
    assert (ROOT / "NOTICE.md").is_file()
    assert not list(MODEL_DIR.rglob("NOTICE*"))


def test_notice_is_what_make_notice_generates():
    if not (QLM / "LICENSES" / "QuantLib-LICENSE.TXT").exists():
        pytest.skip("quantlib-migration checkout not found")
    spec = importlib.util.spec_from_file_location("make_notice", ROOT / "tools" / "make_notice.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert (ROOT / "NOTICE.md").read_text(encoding="utf-8") == mod.build(QLM)


def test_notice_carries_the_required_statements():
    text = (ROOT / "NOTICE.md").read_text(encoding="utf-8")
    for needle in [
        "tag v1.43, commit 6b57206e04598f092efee66e3b367efc84771995",
        "Monte Carlo",
        "Argonne National Laboratory",
        "Stephen Joe and Frances",
        "Redistributions of source code must retain the above copyright notice",
        "NOT part of QuantLib and is not endorsed by the QuantLib Group",
    ]:
        assert needle in text


def test_notice_names_every_derived_space():
    """Every Space whose formulas carry the provenance comment is listed in "Which files are derived"."""
    text = (ROOT / "NOTICE.md").read_text(encoding="utf-8")
    section = text.split("## Which files are derived", 1)[1].split("\n## ", 1)[0]
    derived = sorted(p.parent.name for p in MODEL_DIR.glob("*/__init__.py")
                     if "# ported from pureql/" in p.read_text(encoding="utf-8"))
    assert derived, "no Space carries the provenance comment"
    missing = [name for name in derived if f"``{name}``" not in section]
    assert not missing, f"NOTICE.md does not list the derived Space(s) {missing} (edit tools/make_notice.py)"


def test_no_name_contains_quantlib():
    for p in ROOT.rglob("*"):
        if any(part in (".git", "build") for part in p.parts):
            continue
        assert "quantlib" not in p.name.lower(), p
