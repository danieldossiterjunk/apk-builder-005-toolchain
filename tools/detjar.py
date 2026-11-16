#!/usr/bin/env python3
"""Deterministic jar/zip writer: sorted entries, fixed timestamps, no extra fields.

Usage: detjar.py <input-dir> <output.jar>
"""
import os
import sys
import zipfile

FIXED = (2009, 1, 1, 0, 0, 0)


def main() -> int:
    src, out = sys.argv[1], sys.argv[2]
    names = []
    for root, _dirs, files in os.walk(src):
        for f in files:
            full = os.path.join(root, f)
            names.append(os.path.relpath(full, src).replace(os.sep, "/"))
    names.sort()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for n in names:
            zi = zipfile.ZipInfo(n, FIXED)
            zi.compress_type = zipfile.ZIP_DEFLATED
            zi.external_attr = 0o644 << 16
            with open(os.path.join(src, n), "rb") as fh:
                z.writestr(zi, fh.read())
    print(f"{out}: {len(names)} entries")
    return 0


if __name__ == "__main__":
    sys.exit(main())
