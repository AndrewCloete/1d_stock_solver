"""
CLI entry point for the `cutlist` command.

Usage:
    uv run cutlist BOM.csv
    uv run cutlist BOM.csv --stock stock.toml --kerf 4 --trim 20 --csv layout.csv
    python -m cutlist BOM.csv
"""

import argparse
import sys
from pathlib import Path

from cutlist import console, load_stock, print_shopping_list, read_bom, report, solve, write_csv

DEFAULT_KERF = 3   # mm lost per cut
DEFAULT_TRIM = 10  # mm docked off each bar end for squaring


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Solve the 1D cutting-stock problem from an Onshape BOM CSV."
    )
    ap.add_argument("bom", help="path to the BOM CSV")
    ap.add_argument(
        "--stock",
        type=Path,
        default=Path("stock.toml"),
        metavar="FILE",
        help="TOML file listing purchasable lengths and prices (default: stock.toml)",
    )
    ap.add_argument("--kerf", type=int, default=DEFAULT_KERF,
                    help=f"mm lost per cut (default {DEFAULT_KERF})")
    ap.add_argument("--trim", type=int, default=DEFAULT_TRIM,
                    help=f"mm docked off each bar end (default {DEFAULT_TRIM})")
    ap.add_argument("--length-col", default="Title 2",
                    help="BOM column that holds the part length (default: 'Title 2')")
    ap.add_argument("--csv", metavar="FILE",
                    help="also write the cutting layout to this CSV")
    ap.add_argument("--time-limit", type=float, default=30,
                    help="CP-SAT time limit in seconds (default 30)")
    args = ap.parse_args()

    try:
        stock = load_stock(args.stock)
    except FileNotFoundError:
        sys.exit(f"stock file not found: {args.stock}")

    pieces, skipped = read_bom(args.bom, args.length_col)

    if skipped:
        print(
            f"skipped {len(skipped)} row(s) with no material or no length: "
            + ", ".join(skipped),
            file=sys.stderr,
        )

    if not pieces:
        sys.exit("nothing to optimise — check the column names")

    results: dict = {}
    grand_total = 0.0

    for material in sorted(pieces):
        if material not in stock:
            print(
                f"\nmaterial {material!r} not in {args.stock} — add it",
                file=sys.stderr,
            )
            continue
        price, bars, optimal = solve(
            pieces[material], stock[material],
            args.kerf, args.trim, args.time_limit,
        )
        results[material] = (price, bars, optimal)
        grand_total += price
        report(material, bars, price, optimal, args.kerf, args.trim)

    print_shopping_list(results, stock, grand_total)

    console.save_svg("out/out.svg", title="Cutlist")

    if args.csv:
        write_csv(args.csv, results, args.kerf, args.trim)
        print(f"\nlayout written to {args.csv}")


if __name__ == "__main__":
    main()
