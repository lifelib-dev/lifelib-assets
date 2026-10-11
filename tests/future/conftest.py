"""Fixtures of the future-t validation (plan Phase 3, Verification L5/L6).

* Every test runs inside a pureql state guard: pureql's process state
  (Settings, the clock hook, ...) is snapshotted before the test and restored
  EXACTLY after it, and a test that leaves it changed fails.
* ``new_model`` / ``set_model`` make private model instances (unique names,
  closed at teardown), as in ``tests/pv/conftest.py``. A model caches every
  value, so tests that change Data References use their own instance.
* The fuzz portfolios (``fuzz_inputs``, ``fuzz_models``, ``fuzz_pairs``;
  defined in ``helpers/pureql_val.py``) are session-scoped:
  ``test_future_fuzz.py`` (pureql, bitwise) and ``test_future_oracle.py``
  (QuantLib 1.41, T2) sample the same pairs.
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

    def make(prefix="FutureTest", input_dir=None, **refs):
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
            made[name] = pv.private_model(f"Future_{name}_", input_dir, **refs)
        return made[name]

    yield get
    for m in made.values():
        m.close()


@pytest.fixture(scope="session")
def fuzz_inputs(tmp_path_factory):
    """{set name: input directory} of the fuzz portfolios (``pureql_val.FUZZ_SETS``)."""
    return {name: pv.write_fuzz_inputs(tmp_path_factory.mktemp(f"future_fuzz_{name}"), name)
            for name in pv.FUZZ_SETS}


@pytest.fixture(scope="session")
def fuzz_models(fuzz_inputs):
    made = {name: pv.private_model(f"FutureFuzz_{name}_", d) for name, d in fuzz_inputs.items()}
    yield made
    for m in made.values():
        m.close()


@pytest.fixture(scope="session")
def fuzz_pairs(fuzz_models):
    """{set name: [(scen_id, t, b, z, category), ...]}: ``FUZZ_PAIRS`` per set, the default run is a prefix."""
    return {name: pv.sample_pairs(fuzz_models[name], pv.FUZZ_PAIRS[name], pv.FUZZ_SEED + k)
            for k, name in enumerate(sorted(pv.FUZZ_SETS))}
