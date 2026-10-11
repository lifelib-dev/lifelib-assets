"""Shared pytest fixtures.

The model under test is read once per session from ``bond_portfolio/BondPortfolio``.
Tests that need their own inputs write CSV files into ``tmp_path`` and point
``Data.input_dir`` at them through :func:`helpers.model.use_inputs`.
"""

import pytest

from helpers import model as model_helpers


@pytest.fixture(scope="session")
def model():
    """The BondPortfolio model, read once per session."""
    return model_helpers.load_model()


@pytest.fixture
def sample_inputs_dir():
    """The directory of the small sample input set shipped with the project."""
    return model_helpers.SAMPLE_INPUTS
