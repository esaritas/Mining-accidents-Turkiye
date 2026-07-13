#!/usr/bin/env python3
"""Run the quality-check suite. Thin wrapper over the CLI.

Equivalent to: python -m mining_accidents.cli qc [options]
"""

import sys

from mining_accidents.cli import app

if __name__ == "__main__":
    app(["qc", *sys.argv[1:]])
