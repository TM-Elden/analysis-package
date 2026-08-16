"""C6 evidence layer: a deterministic corpus scan (`scan.py`) plus typed drift detectors
(`detectors.py`) over it. This is stage 1 of the planner-bot pipeline only (design report
`data/fathm-phase4-readiness/report.md` section 5.2 in the firstmate repo) - the LLM-drafting
stage (turning a `Finding` into a proposal) is a later chunk (P4.4) and does not live here.

Hard invariant, load-bearing across both modules: nothing in this package aggregates by
`author` or any `owners.*` identifier. See `detectors.py`'s module docstring and
`test_detectors.py::test_no_author_or_owner_keys_anywhere_in_scan_or_findings` for the shape
this buys.
"""

from __future__ import annotations
