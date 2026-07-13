#!/usr/bin/env python3
"""Import manual source-document/claim files. Thin wrapper over the CLI.

Equivalent to: python -m mining_accidents.cli import-manual [options]
"""

import sys

from mining_accidents.cli import app

if __name__ == "__main__":
    app(["import-manual", *sys.argv[1:]])
