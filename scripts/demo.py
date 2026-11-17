#!/usr/bin/env python3
"""Run the Data Vault 2.0 end-to-end demo (see src/datavault/demo.py)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from datavault.demo import print_demo, run_demo

if __name__ == "__main__":
    print_demo(run_demo())
