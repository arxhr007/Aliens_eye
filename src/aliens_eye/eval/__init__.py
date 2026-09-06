"""Reproducible evaluation over a frozen response corpus.

:mod:`aliens_eye.eval.ablate` scores a corpus under several detector
configurations at once, so the contribution of each component -- the heuristic
engine, the ML model, the blend, the structural feature groups -- can be read
off a single table rather than asserted.
"""

from .ablate import ABLATIONS, run_ablations

__all__ = ["ABLATIONS", "run_ablations"]
