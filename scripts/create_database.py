#!/usr/bin/env python3
"""Create or upgrade the SQLite database. Thin wrapper over the CLI.

Equivalent to: python -m mining_accidents.cli create-db [options]
"""

import sys

from mining_accidents.cli import app

if __name__ == "__main__":
    app(["create-db", *sys.argv[1:]])
