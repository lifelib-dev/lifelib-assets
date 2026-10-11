"""Access to the BondPortfolio model from tests."""

import pathlib

import modelx as mx

ROOT = pathlib.Path(__file__).resolve().parents[2]
MODEL_DIR = ROOT / "bond_portfolio" / "BondPortfolio"
SAMPLE_INPUTS = ROOT / "bond_portfolio"

_MODEL = None


def load_model():
    """Read the model once and return it (shared by every test of a session)."""
    global _MODEL
    if _MODEL is None:
        _MODEL = mx.read_model(MODEL_DIR, name="BondPortfolio_test")
    return _MODEL


def use_inputs(model, input_dir):
    """Point the model at a directory of input CSV files.

    Assigning the Reference clears every value that depends on it, so the next
    calculation reads the new inputs.
    """
    input_dir = str(input_dir)
    if model.Data.input_dir != input_dir:
        model.Data.input_dir = input_dir
    return model
