#!/usr/bin/env python3
"""Pre-push privacy gate for cbi_plus. Exit 0 = clean, 1 = private data tracked.

cbi_plus code legitimately says "INRIX"/"RITIS" everywhere (it implements those
loaders), so unlike gui4gmns this gate screens CONTENT SHAPE, not names:

  1. nothing tracked under outputs/ or additional/ (the private areas);
  2. no tracked CSV that IS a raw probe/detector readings table
     (a `measurement_tstamp` or `tmc_code` data column with many rows);
  3. no tracked file larger than 10 MB (raw data smell);
  4. no tracked TMC_Identification tables outside benchmarks/ examples.

Run:  python validate_no_private_data.py     (from the repo root)
"""
import subprocess
import sys
from pathlib import Path

SIZE_LIMIT_MB = 10.0
RAW_HEADER_TOKENS = {"measurement_tstamp", "tmc_code"}
ALLOWED_DATA_PREFIXES = ("benchmarks/",)   # public PeMS March-2018 cases


def tracked() -> list[str]:
    out = subprocess.run(["git", "ls-files"], capture_output=True, text=True,
                         check=True).stdout
    return [l for l in out.splitlines() if l.strip()]


def main() -> None:
    files = tracked()
    bad: list[str] = []

    for f in files:
        p = Path(f)
        if f.startswith(("outputs/", "additional/")):
            bad.append(f"{f}  (private area tracked)")
            continue
        if p.exists() and p.stat().st_size > SIZE_LIMIT_MB * 1e6:
            bad.append(f"{f}  ({p.stat().st_size/1e6:.0f} MB > {SIZE_LIMIT_MB:.0f} MB)")
            continue
        if p.suffix.lower() == ".csv" and p.exists() \
                and not f.startswith(ALLOWED_DATA_PREFIXES):
            try:
                head = open(p, encoding="utf-8", errors="ignore").readline().lower()
            except OSError:
                continue
            cols = {c.strip() for c in head.split(",")}
            if RAW_HEADER_TOKENS & cols:
                # data-shaped: only a handful of doc/template rows are OK
                n = sum(1 for _ in open(p, encoding="utf-8", errors="ignore"))
                if n > 200:
                    bad.append(f"{f}  (raw readings table, {n} rows)")

    print(f"tracked files: {len(files)}")
    if bad:
        print(f"\n!! {len(bad)} PRIVATE-looking tracked file(s) — DO NOT PUSH:")
        for b in bad:
            print("   ", b)
        sys.exit(1)
    print("clean: no private-looking files tracked.")
    sys.exit(0)


if __name__ == "__main__":
    main()
