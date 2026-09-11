"""
Sweep driver: solve a folder of bom_<value>.csv files and plot cost vs. dimension.

Usage:
    uv run sweep boms/
    uv run sweep boms/ --output cost.png
    uv run sweep boms/ --pattern "bench_*.csv" --stock stock.toml
    python -m cutlist.sweep boms/

Expected filenames: bom_1400.csv, bom_1500.csv, …
The integer in the stem is used as the x-axis value (e.g. bench length in mm).
"""

import argparse
import re
import sys
from pathlib import Path

from cutlist import load_stock, read_bom, solve


def _parse_value(stem: str) -> int | None:
    """Extract the first integer from a filename stem."""
    m = re.search(r"(\d+)", stem)
    return int(m.group(1)) if m else None


def _run_sweep(
    bom_dir: Path,
    pattern: str,
    stock: dict,
    kerf: int,
    trim: int,
    time_limit: float,
    length_col: str,
) -> list[tuple[int, float, bool]]:
    """Return [(value, total_cost, all_optimal), …] sorted by value."""
    files = sorted(bom_dir.glob(pattern))
    if not files:
        sys.exit(f"no files matching {pattern!r} in {bom_dir}")

    points: list[tuple[int, float, bool]] = []

    for f in files:
        value = _parse_value(f.stem)
        if value is None:
            print(f"skipping {f.name} — no integer in filename", file=sys.stderr)
            continue

        pieces, skipped = read_bom(f, length_col)
        if skipped:
            print(
                f"{f.name}: skipped {len(skipped)} row(s): " + ", ".join(skipped),
                file=sys.stderr,
            )

        total = 0.0
        all_optimal = True
        ok = True

        for material in sorted(pieces):
            if material not in stock:
                print(
                    f"{f.name}: material {material!r} not in stock.toml — skipping file",
                    file=sys.stderr,
                )
                ok = False
                break
            price, _, optimal = solve(
                pieces[material], stock[material], kerf, trim, time_limit
            )
            total += price
            if not optimal:
                all_optimal = False

        if ok:
            points.append((value, total, all_optimal))

    points.sort()
    return points


def _print_table(points: list[tuple[int, float, bool]]) -> None:
    header = f"{'value':>8}   {'cost':>10}   note"
    print(header)
    print("-" * len(header))
    for i, (value, cost, optimal) in enumerate(points):
        note = ""
        if not optimal:
            note = "[time limit]"
        elif i < len(points) - 1 and points[i + 1][1] > cost:
            note = "← plateau edge"
        print(f"{value:>8}   {cost:>10.2f}   {note}")


def _plot(points: list[tuple[int, float, bool]], output: Path | None) -> None:
    import matplotlib.pyplot as plt

    xs = [p[0] for p in points]
    ys = [p[1] for p in points]

    fig, ax = plt.subplots(figsize=(11, 5))

    # step-function: cost stays constant until the next cliff
    ax.step(xs, ys, where="post", linewidth=2, color="steelblue")
    ax.scatter(xs, ys, s=30, zorder=5, color="steelblue")

    # annotate the right-hand end of each plateau (best place to sit)
    for i in range(len(points) - 1):
        value, cost, _ = points[i]
        next_cost = points[i + 1][1]
        if next_cost > cost:
            ax.annotate(
                f"{value:,}",
                (value, cost),
                textcoords="offset points",
                xytext=(0, 8),
                ha="center",
                fontsize=8,
                color="darkblue",
                fontweight="bold",
            )

    ax.set_xlabel("Dimension (mm)")
    ax.set_ylabel("Total stock cost")
    ax.set_title("Stock cost vs. bench dimension")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()

    if output:
        fig.savefig(output, dpi=150)
        print(f"plot saved to {output}")
    else:
        plt.show()


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Sweep a folder of BOM CSVs and plot cost vs. dimension."
    )
    ap.add_argument(
        "bom_dir",
        type=Path,
        nargs="?",
        default=Path("."),
        help="directory containing bom_*.csv files (default: current directory)",
    )
    ap.add_argument(
        "--pattern",
        default="bom_*.csv",
        help="glob pattern for BOM files (default: bom_*.csv)",
    )
    ap.add_argument(
        "--stock",
        type=Path,
        default=Path("stock.toml"),
        metavar="FILE",
        help="TOML stock-config file (default: stock.toml)",
    )
    ap.add_argument("--kerf", type=int, default=3,
                    help="mm lost per cut (default 3)")
    ap.add_argument("--trim", type=int, default=10,
                    help="mm docked off each bar end (default 10)")
    ap.add_argument("--length-col", default="Title 2",
                    help="BOM column holding the part length (default: 'Title 2')")
    ap.add_argument("--time-limit", type=float, default=30,
                    help="CP-SAT time limit per solve in seconds (default 30)")
    ap.add_argument(
        "--output",
        type=Path,
        metavar="FILE",
        help="save the plot here (PNG/PDF/SVG); omit to display interactively",
    )
    ap.add_argument(
        "--no-plot",
        action="store_true",
        help="print the table only, do not open or save a plot",
    )
    args = ap.parse_args()

    try:
        stock = load_stock(args.stock)
    except FileNotFoundError:
        sys.exit(f"stock file not found: {args.stock}")

    points = _run_sweep(
        args.bom_dir, args.pattern, stock,
        args.kerf, args.trim, args.time_limit, args.length_col,
    )

    if not points:
        sys.exit("no valid data points — check filenames and BOM contents")

    _print_table(points)

    if not args.no_plot:
        _plot(points, args.output)


if __name__ == "__main__":
    main()
