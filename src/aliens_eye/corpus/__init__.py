"""Frozen HTTP response corpus: record once, replay deterministically.

Evaluating a detector against the live web is not reproducible -- platforms
change their markup, rate-limit differently on different days, and block some
networks entirely. A measured change in accuracy cannot be attributed to the
detector rather than to the web.

This package removes the network from the measurement loop:

* :mod:`aliens_eye.corpus.record` captures raw responses to disk.
* :mod:`aliens_eye.corpus.replay` serves them back through the *same*
  ``fetch_url`` interface the scanner already uses.

Because replay substitutes only the fetch, every downstream stage --
``core.analyzer`` feature extraction, ``core.detector`` scoring, ``core.features``
vectorisation -- runs byte-identical code on live and replayed responses. An
evaluation therefore measures the detector, not the harness.
"""

from .store import CorpusError, CorpusRecord, CorpusStore

__all__ = ["CorpusError", "CorpusRecord", "CorpusStore"]
