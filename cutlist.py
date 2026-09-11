#!/usr/bin/env python3
"""Backward-compat shim. Prefer: uv run cutlist BOM.csv"""
from cutlist.__main__ import main

if __name__ == "__main__":
    main()
