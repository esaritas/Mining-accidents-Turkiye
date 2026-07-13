#!/usr/bin/env python3
"""Build the public export. Thin wrapper over the CLI.

Equivalent to: python -m mining_accidents.cli export [options]
"""

import sys

from mining_accidents.cli import app

if __name__ == "__main__":
    app(["export", *sys.argv[1:]])
