"""
Cutting-stock optimiser — core library.

Public API:
    load_stock(path)          → dict[material, [(mm, price), ...]]
    read_bom(path, ...)       → (pieces_by_material, skipped_names)
    solve(pieces, options, …) → (total_price, bars, optimal_flag)
    report(...)               → prints a human layout to stdout
    write_csv(path, ...)      → writes a layout CSV
"""

import csv
import tomllib
from collections import defaultdict
from pathlib import Path


def load_stock(path: Path = Path("stock.toml")) -> dict[str, list[tuple[int, float]]]:
    """Load the purchasable-stock table from a TOML file.

    Expected format (see stock.toml):
        [A]
        options = [{mm = 2400, price = 180.0}, ...]
    """
    with open(path, "rb") as f:
        data = tomllib.load(f)
    return {
        mat: [(int(opt["mm"]), float(opt["price"])) for opt in conf["options"]]
        for mat, conf in data.items()
    }


def read_bom(path, length_col: str = "Title 2"):
    """Parse an Onshape BOM CSV.

    Returns (pieces, skipped):
        pieces  — dict[material] → [(length_mm, part_name), ...]
        skipped — list of names that lacked material or a parseable length
    """
    pieces: dict[str, list[tuple[int, str]]] = defaultdict(list)
    skipped: list[str] = []

    with open(path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            name = (row.get("Name") or "").strip()
            material = (row.get("Material") or "").strip()
            raw_len = (row.get(length_col) or "").strip()

            if material in ("", "- None -") or raw_len == "":
                skipped.append(name or "<unnamed>")
                continue

            try:
                length = int(round(float(raw_len)))
            except ValueError:
                skipped.append(name)
                continue

            try:
                qty = int(row.get("Quantity") or 1)
            except ValueError:
                qty = 1

            for n in range(qty):
                label = name if qty == 1 else f"{name} ({n + 1})"
                pieces[material].append((length, label))

    return dict(pieces), skipped


def solve(
    pieces: list[tuple[int, str]],
    options: list[tuple[int, float]],
    kerf: int,
    trim: int,
    time_limit: float = 30,
) -> tuple[float, list[tuple[int, list[tuple[int, str]]]], bool]:
    """Solve the 1D cutting-stock problem with CP-SAT.

    Minimises cost, not bar count, so it will mix purchasable lengths.

    pieces:   [(length_mm, name), ...]
    options:  [(bar_length_mm, price), ...]
    Returns:  (total_price, bars, optimal_flag)
              bars = [(bar_length, [(length, name), ...]), ...]
    """
    from ortools.sat.python import cp_model

    lengths = [p[0] for p in pieces]
    longest = max(lengths)
    longest_bar = max(o[0] for o in options)
    if longest > longest_bar - trim:
        raise ValueError(
            f"piece of {longest}mm does not fit the longest bar "
            f"({longest_bar}mm minus {trim}mm trim)"
        )

    n = len(pieces)
    ub = n  # worst case: one bar per piece
    m = cp_model.CpModel()

    x = {(i, b): m.NewBoolVar(f"x{i}_{b}") for i in range(n) for b in range(ub)}
    used = [m.NewBoolVar(f"u{b}") for b in range(ub)]
    pick = [
        [m.NewBoolVar(f"p{b}_{o}") for o in range(len(options))]
        for b in range(ub)
    ]

    for i in range(n):
        m.AddExactlyOne(x[i, b] for b in range(ub))

    for b in range(ub):
        m.Add(sum(pick[b]) == 1).OnlyEnforceIf(used[b])
        m.Add(sum(pick[b]) == 0).OnlyEnforceIf(used[b].Not())

        capacity = sum(
            (options[o][0] - trim + kerf) * pick[b][o]
            for o in range(len(options))
        )
        m.Add(sum((lengths[i] + kerf) * x[i, b] for i in range(n)) <= capacity)

    # symmetry-breaking: fill low-numbered bars first
    for b in range(ub - 1):
        m.Add(used[b] >= used[b + 1])

    # objective in integer cents so CP-SAT stays in the integer domain
    m.Minimize(
        sum(
            int(round(options[o][1] * 100)) * pick[b][o]
            for b in range(ub)
            for o in range(len(options))
        )
    )

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit
    solver.parameters.num_search_workers = 8
    status = solver.Solve(m)

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        raise RuntimeError("no solution found")

    bars = []
    for b in range(ub):
        if not solver.Value(used[b]):
            continue
        bar_len = next(
            options[o][0]
            for o in range(len(options))
            if solver.Value(pick[b][o])
        )
        on_bar = sorted(
            (pieces[i] for i in range(n) if solver.Value(x[i, b])),
            reverse=True,
        )
        bars.append((bar_len, on_bar))

    bars.sort(key=lambda bar: (-bar[0], -sum(p[0] for p in bar[1])))
    total = solver.ObjectiveValue() / 100.0
    optimal = status == cp_model.OPTIMAL
    return total, bars, optimal


def report(
    material: str,
    bars: list[tuple[int, list[tuple[int, str]]]],
    price: float,
    optimal: bool,
    kerf: int,
    trim: int,
) -> None:
    bought = sum(b[0] for b in bars)
    used = sum(p[0] for b in bars for p in b[1])
    count = len(bars)

    print(f"\n{'=' * 64}")
    print(
        f"MATERIAL {material}   —   {count} bars, {bought / 1000:.2f} m, "
        f"cost {price:.2f}" + ("" if optimal else "   [time limit hit]")
    )
    print("=" * 64)

    for i, (bar_len, on_bar) in enumerate(bars, 1):
        consumed = sum(p[0] for p in on_bar) + kerf * len(on_bar) + trim
        offcut = bar_len - consumed
        print(f"\n  Bar {i}:  {bar_len}mm        offcut {offcut}mm")
        for length, name in on_bar:
            print(f"      {length:>6}   {name}")

    waste = bought - used
    print(
        f"\n  used {used / 1000:.2f} m of {bought / 1000:.2f} m  "
        f"→ {100 * waste / bought:.1f}% waste"
    )


def write_csv(path, results: dict, kerf: int, trim: int) -> None:
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Material", "Bar", "Bar length", "Piece length", "Part", "Offcut"])
        for material, (_, bars, _) in results.items():
            for i, (bar_len, on_bar) in enumerate(bars, 1):
                consumed = sum(p[0] for p in on_bar) + kerf * len(on_bar) + trim
                offcut = bar_len - consumed
                for j, (length, name) in enumerate(on_bar):
                    w.writerow(
                        [material, i, bar_len, length, name, offcut if j == 0 else ""]
                    )
