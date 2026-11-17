#!/usr/bin/env python3
"""Feature-flag values for compiling the framework resources (frameworks/base core/res) with AAPT2.

  feature_flags.py CORE_RES BUILD_RELEASE_DIR RELEASE_CONFIG OUT_FLAGS_TXT OUT_REPORT_JSON [DECL_DIR ...]

Android 15+ resources may carry android:featureFlag="[!]package.flag". AAPT2 must be told every such flag
(--feature-flags name[:READ_ONLY|READ_WRITE]=true|false); Soong takes the values from the release
configuration. This script does the same from platform/build/release at the same tag:
  * the release configuration (e.g. cp1a for android-17.0.0_r1, whose build IDs start with CP1A) is read from
    release_configs/<name>.textproto, following "inherits" to its ancestors, and its aconfig value sets are
    the aconfig/<set>/ directories named by "aconfig_value_sets" (or aconfig/<name>/ when none are named);
  * a flag value file <package>/<flag>_flag_values.textproto in a later (more specific) set overrides an
    earlier one;
  * a flag no value file mentions keeps aconfig's default: DISABLED, and READ_ONLY only when its declaration
    (found in DECL_DIR *.aconfig files) says is_fixed_read_only: true, otherwise READ_WRITE.
OUT_FLAGS_TXT gets one "name:PERMISSION=value" per line (AAPT2 reads a comma-separated list; the workflow
joins the lines). The report lists where each value came from.
"""
import json, os, re, sys

core_res, rel_dir, config, out_txt, out_json = sys.argv[1:6]
decl_dirs = sys.argv[6:]

# 1. flags referenced by the resources
refs = {}
for root, _, files in os.walk(core_res):
    for f in files:
        if not f.endswith(".xml"): continue
        p = os.path.join(root, f)
        for m in re.finditer(r'featureFlag\s*=\s*"!?([A-Za-z0-9_.]+)"', open(p, encoding="utf-8", errors="replace").read()):
            refs.setdefault(m.group(1), set()).add(os.path.relpath(p, core_res))


# 2. release configuration chain and its value sets
def tp_list(text, key):
    return re.findall(r'\b%s\s*:\s*"([^"]+)"' % key, text)


chain, sets, seen, notes = [], [], set(), []
def walk(name):
    if name in seen: return
    seen.add(name)
    p = None
    for cand in (os.path.join(rel_dir, "release_configs", name + ".textproto"),):
        if os.path.exists(cand): p = cand
    if p is None:
        for root, _, files in os.walk(rel_dir):
            if name + ".textproto" in files and "release_config" in root:
                p = os.path.join(root, name + ".textproto"); break
    if p is None:
        notes.append("release config %s: no textproto found" % name); return
    text = open(p, encoding="utf-8").read()
    for parent in tp_list(text, "inherits"): walk(parent)
    chain.append(name)
    vs = tp_list(text, "aconfig_value_sets")
    sets.extend(vs if vs else [name])
    notes.append("release config %s (%s): inherits %s, aconfig_value_sets %s" % (name, os.path.relpath(p, rel_dir), tp_list(text, "inherits"), vs))


walk(config)

def set_dir(s):
    # value sets are named e.g. "aconfig_value_set-platform_build_release-cp1a" and live in aconfig/cp1a/
    # (declared by the Android.bp there); try the name itself, its last "-" part, and the old "_" spelling
    cands = [s, s.rsplit("-", 1)[-1], s.replace("aconfig_value_set_", "")]
    for cand in cands:
        d = os.path.join(rel_dir, "aconfig", cand)
        if os.path.isdir(d): return d
    for root, _, files in os.walk(os.path.join(rel_dir, "aconfig")):
        if "Android.bp" in files and ('"%s"' % s) in open(os.path.join(root, "Android.bp"), encoding="utf-8", errors="replace").read():
            return root
    return None


values = {}  # name -> (state, permission, source)
for s in sets:
    d = set_dir(s)
    if d is None:
        notes.append("value set %s: no directory under aconfig/" % s); continue
    for root, _, files in os.walk(d):
        for f in files:
            if not f.endswith(".textproto"): continue
            t = open(os.path.join(root, f), encoding="utf-8", errors="replace").read()
            for m in re.finditer(r"flag_value\s*\{(.*?)\}", t, re.S):
                b = m.group(1)
                pk = re.search(r'package:\s*"([^"]+)"', b); nm = re.search(r'name:\s*"([^"]+)"', b)
                st = re.search(r"state:\s*(\w+)", b); pm = re.search(r"permission:\s*(\w+)", b)
                if pk and nm:
                    values["%s.%s" % (pk.group(1), nm.group(1))] = (st.group(1) if st else "DISABLED", pm.group(1) if pm else "READ_WRITE",
                                                                    os.path.relpath(os.path.join(root, f), rel_dir))

# 3. declarations (for the default permission of flags without a value)
decls = {}
for dd in decl_dirs:
    for root, _, files in os.walk(dd):
        for f in files:
            if not f.endswith(".aconfig"): continue
            t = open(os.path.join(root, f), encoding="utf-8", errors="replace").read()
            pk = re.search(r'^\s*package:\s*"([^"]+)"', t, re.M)
            if not pk: continue
            for m in re.finditer(r"flag\s*\{(.*?)\n\}", t, re.S):
                nm = re.search(r'name:\s*"([^"]+)"', m.group(1))
                ro = re.search(r"is_fixed_read_only:\s*true", m.group(1))
                if nm: decls["%s.%s" % (pk.group(1), nm.group(1))] = {"fixed_read_only": bool(ro), "file": os.path.relpath(os.path.join(root, f), dd)}

lines, report = [], {"release_config": config, "chain": chain, "value_sets": sets, "notes": notes, "flags": {}}
counts = {"from_release_config": 0, "aconfig_default": 0, "undeclared_default": 0}
for name in sorted(refs):
    if name in values:
        st, pm, src = values[name]; how = "from_release_config"
    elif name in decls:
        st, pm, src = "DISABLED", "READ_ONLY" if decls[name]["fixed_read_only"] else "READ_WRITE", "default (declared in %s)" % decls[name]["file"]
        how = "aconfig_default"
    else:
        st, pm, src = "DISABLED", "READ_WRITE", "not found in release values or declarations"; how = "undeclared_default"
    counts[how] += 1
    lines.append("%s:%s=%s" % (name, pm, "true" if st == "ENABLED" else "false"))
    report["flags"][name] = {"state": st, "permission": pm, "source": src, "used_in": sorted(refs[name])[:5]}
report["counts"] = counts
report["referenced_flags"] = len(refs)
open(out_txt, "w").write("\n".join(lines) + "\n")
json.dump(report, open(out_json, "w"), indent=1)
print(json.dumps({k: report[k] for k in ("release_config", "chain", "value_sets", "notes", "counts", "referenced_flags")}, indent=1))
