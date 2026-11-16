#!/usr/bin/env python3
"""Pick the SDK platform package used for comparison only (never published) from `sdkmanager --list` output.

  sdkmanager --list | pick_platform.py API

Prefers the final release of the API level: platforms;android-API, then platforms;android-API.0, then the highest
platforms;android-API.N without a pre-release suffix; pre-release (beta/rc/preview/ext) packages are used only
when nothing else exists. Prints every candidate to stderr and the chosen package to stdout.
"""
import re, sys

api = sys.argv[1]
cands = sorted(set(re.findall(r"platforms;android-%s[^\s|]*" % re.escape(api), sys.stdin.read())))
print("candidates: %s" % (", ".join(cands) or "none"), file=sys.stderr)


def key(p):
    tail = p.split("android-" + api, 1)[1]
    final = re.fullmatch(r"(\.\d+)?", tail) is not None
    minor = int(tail[1:]) if final and tail else 0
    return (final, tail == "", tail == ".0", minor)


if cands:
    best = max(cands, key=key)
    print("chosen: %s (%s)" % (best, "final" if key(best)[0] else "PRE-RELEASE"), file=sys.stderr)
    print(best)
