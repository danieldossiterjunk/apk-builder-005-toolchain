#!/usr/bin/env python3
"""Report the release-configuration values of the aconfig flags pinned for the AAPT2 build (report only).

  aconfig_values.py FLAGS_ACONFIG BUILD_RELEASE_DIR PINNED_VALUES

FLAGS_ACONFIG is the package's declaration file (frameworks/base/core/java/android/content/res/flags.aconfig);
BUILD_RELEASE_DIR is a checkout of platform/build/release at the same tag. For every pinned flag the report
gives its declaration (namespace, read-only or not) and the value set by each release configuration that
mentions it, so the pinned value can be checked against the configurations of the release.
"""
import os, re, sys

decl_file, rel_dir, pinned_file = sys.argv[1:4]
text = open(decl_file, encoding="utf-8").read()
pkg = re.search(r'^\s*package:\s*"([^"]+)"', text, re.M).group(1)
decls = {}
for m in re.finditer(r"flag\s*\{(.*?)\n\}", text, re.S):
    body = m.group(1)
    name = re.search(r'name:\s*"([^"]+)"', body).group(1)
    ro = re.search(r"is_fixed_read_only:\s*(true|false)", body)
    ns = re.search(r'namespace:\s*"([^"]+)"', body)
    decls[name] = {"namespace": ns.group(1) if ns else None, "is_fixed_read_only": ro.group(1) if ro else "false"}
pinned = {}
for line in open(pinned_file, encoding="utf-8"):
    line = line.split("#", 1)[0].strip()
    if line:
        n, v = line.split(); pinned[n] = v
vals = {}
for root, _, files in os.walk(rel_dir):
    for f in files:
        if not f.endswith(".textproto"): continue
        p = os.path.join(root, f)
        t = open(p, encoding="utf-8", errors="replace").read()
        for m in re.finditer(r"flag_value\s*\{(.*?)\}", t, re.S):
            b = m.group(1)
            pk = re.search(r'package:\s*"([^"]+)"', b); nm = re.search(r'name:\s*"([^"]+)"', b)
            st = re.search(r"state:\s*(\w+)", b); pm = re.search(r"permission:\s*(\w+)", b)
            if pk and nm and pk.group(1) == pkg and nm.group(1) in pinned:
                vals.setdefault(nm.group(1), []).append((os.path.relpath(p, rel_dir), st.group(1) if st else "?", pm.group(1) if pm else "?"))
print("package %s (%d flags declared)" % (pkg, len(decls)))
for n, v in pinned.items():
    print("\n%s: pinned %s; declared: %s" % (n, v, decls.get(n, "NOT DECLARED")))
    for p, st, pm in sorted(vals.get(n, [])):
        print("   %-70s %s %s" % (p, st, pm))
    if not vals.get(n):
        print("   no release configuration sets it (aconfig default: DISABLED)")
