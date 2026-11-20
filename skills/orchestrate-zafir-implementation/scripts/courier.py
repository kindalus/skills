#!/usr/bin/env python3
"""Entry point of courier v2 (scripts/courier/). ``courier.py legacy ...`` runs the v1 file mailbox."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from courier.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
