#!/usr/bin/env python3
"""Generate review packets. Thin wrapper over the CLI.

Equivalent to: python -m mining_accidents.cli packets [options]
"""

import sys

from mining_accidents.cli import app

if __name__ == "__main__":
    app(["packets", *sys.argv[1:]])
