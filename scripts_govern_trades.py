#!/usr/bin/env python3
"""Archive non-strategy rows from trades.csv; keep only 003-014."""
import csv
import shutil
from datetime import datetime
from pathlib import Path

BASE = Path("/home/admin/okx_bot")
TRADES = BASE / "trades.csv"
ARCHIVE = BASE / "trades_archive.csv"
MANUAL = BASE / "trades_manual.csv"
VALID = frozenset({"003", "006", "009", "010", "011", "012", "013", "014"})


def main():
    if not TRADES.exists() or TRADES.stat().st_size == 0:
        print("[govern] trades.csv empty or missing")
        return
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    shutil.copy2(TRADES, BASE / f"trades.csv.bak_govern_{ts}")

    with TRADES.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        print("[govern] no rows")
        return
    fieldnames = list(rows[0].keys())
    keep, archive = [], []
    for row in rows:
        sid = str(row.get("策略", "")).strip()
        if sid in VALID:
            keep.append(row)
        else:
            archive.append(row)

    with TRADES.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(keep)

    if archive:
        exists = ARCHIVE.exists() and ARCHIVE.stat().st_size > 0
        with ARCHIVE.open("a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames)
            if not exists:
                w.writeheader()
            w.writerows(archive)

    print(f"[govern] keep={len(keep)} archive={len(archive)} -> {ARCHIVE.name}")


if __name__ == "__main__":
    main()
