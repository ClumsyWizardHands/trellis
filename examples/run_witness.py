#!/usr/bin/env python3
"""A complete witness cycle, offline — no API key, no network.

This demonstrates the whole trellis working at once: EMP loading (with the
soul refusal live), age-annotated sensing, Y/N/T opinions with lineage, the
bounded loop, external verification, the staged outbox, and the epitaph.

The cycle itself lives in `trellis.cli.run_demo` so it travels with the
installed package and stays identical to `trellis demo`. This wrapper just
points it at an isolated, freshly-reset state directory so it is repeatable
(a persisted `.state` used to collide on the second run).

Run:  python3 examples/run_witness.py
Or:   trellis demo
Swap MockProvider for a real seat to go live — nothing else changes.
"""

import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from trellis.cli import run_demo

HERE = Path(__file__).parent


def main():
    # Isolated + reset each run, so the demo never collides on persisted state.
    state = Path(os.environ.get("TRELLIS_DEMO_STATE") or (HERE / ".state"))
    shutil.rmtree(state, ignore_errors=True)
    run_demo(state)


if __name__ == "__main__":
    main()
