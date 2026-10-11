"""Fixtures of the Phase 4 analytics tests (docs/model-contract.md 4.8).

* Every test runs inside a pureql state guard: pureql's process state
  (Settings, the clock hook, ...) is snapshotted before the test and restored
  EXACTLY after it, and a test that leaves it changed fails (the oracle in
  ``helpers/pureql_val.py`` must restore what it moves).
* ``new_model`` / ``set_model`` make private model instances (unique names,
  closed at teardown), as in ``tests/pv/conftest.py``. A model caches every
  value, so a test that changes Data References (the analytics settings and
  policies) uses its own instance and never the session model.
"""

import pytest

from helpers import pureql_val as pv
from pureql import _state


@pytest.fixture(autouse=True)
def pureql_state_guard():
    """Fail a test that leaves pureql's process-global state changed; restore it either way."""
    before = _state.snapshot_all()
    yield
    changed = _state.changed_since(before)
    _state.restore_all(before)
    assert not changed, f"the test left pureql global state changed: {changed}"


@pytest.fixture
def new_model():
    """``new_model(prefix, input_dir=None, **data_refs)``: private instances, closed at teardown."""
    made = []

    def make(prefix="AnalyticsTest", input_dir=None, **refs):
        m = pv.private_model(prefix, input_dir, **refs)
        made.append(m)
        return m

    yield make
    for m in made:
        m.close()


@pytest.fixture(scope="module")
def set_model():
    """``set_model(name, input_dir=None, **data_refs)``: one private instance per name per module."""
    made = {}

    def get(name, input_dir=None, **refs):
        if name not in made:
            made[name] = pv.private_model(f"Analytics_{name}_", input_dir, **refs)
        return made[name]

    yield get
    for m in made.values():
        m.close()
