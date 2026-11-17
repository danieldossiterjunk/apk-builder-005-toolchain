#!/usr/bin/env python3
"""Collect the public Android API signature files of one AOSP release, merge them, generate compile-time
stubs with APK Builder's StubGen, and compare the result with the SDK's android.jar (comparison only).

  api_stubs.py collect --tag TAG --out DIR [--compare-jar SDK_ANDROID_JAR]
  api_stubs.py compare --stubs STUBS.jar --compare-jar SDK_ANDROID_JAR --out REPORT.json

`collect` clones the AOSP platform manifest at TAG, then every candidate project (frameworks/base, libcore,
external/icu, external/conscrypt and every packages/modules/* project) as a partial, blob-less clone, and
checks out only the files named api/current.txt (the public SDK surface; system, module-lib and test API
files have other names). With --compare-jar, a file is used only when most of its classes are in the SDK's
android.jar; every decision is written to DIR/selection.json. The merged file is DIR/android-api-current.txt and
every collected file is kept under DIR/signature-files/<project path>/.
Nothing from the SDK is copied into the outputs.
"""
import argparse, hashlib, json, os, re, subprocess, sys, zipfile, struct
import xml.etree.ElementTree as ET

AOSP = "https://android.googlesource.com/"


def sh(cmd, cwd=None, check=True):
    p = subprocess.run(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if check and p.returncode != 0:
        raise RuntimeError("failed: %s\n%s" % (" ".join(cmd), p.stdout[-4000:]))
    return p


def sig_classes(text):
    pkg = None; out = set(); fmt = None
    for line in text.splitlines():
        if line.startswith("// Signature format:"): fmt = line.split(":", 1)[1].strip()
        if line.startswith("package "): pkg = line[8:line.index(" ", 8)]
        elif line.startswith("  ") and not line.startswith("    ") and line.rstrip().endswith("{") and pkg:
            m = re.search(r"\b(class|interface|enum|@interface)\s+([A-Za-z0-9_.$]+)", line)
            if m: out.add(pkg.replace(".", "/") + "/" + m.group(2).replace(".", "$"))
    return out, fmt


def jar_classes(path):
    with zipfile.ZipFile(path) as z:
        return set(n[:-6] for n in z.namelist() if n.endswith(".class") and not n.startswith("META-INF/"))


def collect(a):
    os.makedirs(a.out, exist_ok=True)
    work = os.path.join(a.out, "_src"); os.makedirs(work, exist_ok=True)
    man = os.path.join(work, "manifest")
    if not os.path.isdir(man):
        sh(["git", "clone", "-q", "--depth", "1", "--branch", a.tag, AOSP + "platform/manifest", man])
    root = ET.parse(os.path.join(man, "default.xml")).getroot()
    projects = []
    for p in root.findall("project"):
        name, path = p.get("name"), p.get("path") or p.get("name")
        if path in ("frameworks/base", "libcore", "external/icu", "external/conscrypt") or path.startswith(("packages/modules/", "packages/providers/")):
            projects.append((name, path))
    # projects whose path mentions pdf, for the record (android.graphics.pdf lives in a module)
    pdf_like = sorted(p.get("path") or p.get("name") for p in root.findall("project") if "pdf" in (p.get("path") or p.get("name") or "").lower())
    sdk = jar_classes(a.compare_jar) if a.compare_jar and os.path.exists(a.compare_jar) else None
    files = []; provenance = []
    for name, path in sorted(projects, key=lambda x: x[1]):
        d = os.path.join(work, path.replace("/", "__"))
        if not os.path.isdir(d):
            p = sh(["git", "clone", "-q", "--depth", "1", "--filter=blob:none", "--no-checkout", "--branch", a.tag, AOSP + name, d], check=False)
            if p.returncode != 0:
                provenance.append({"project": name, "path": path, "error": p.stdout[-400:]}); continue
        commit = sh(["git", "-C", d, "rev-parse", "HEAD"]).stdout.strip()
        tree = sh(["git", "-C", d, "ls-tree", "-r", "--name-only", "HEAD"]).stdout.splitlines()
        # public API files: api/current.txt, or api/public/current.txt (ICU) and api/platform/current.txt (Conscrypt)
        api = [t for t in tree if re.search(r"(^|/)api/((public|platform)/)?current\.txt$", t) and not re.search(r"(^|/)(tests?|testing|samples?)(/|$)", t)]
        if api:
            sh(["git", "-C", d, "checkout", "-q", "HEAD", "--"] + api)
        provenance.append({"project": name, "path": path, "commit": commit, "api_files": api})
        for f in api:
            full = os.path.join(d, f)
            text = open(full, encoding="utf-8").read()
            cls, fmt = sig_classes(text)
            files.append({"project": name, "path": path + "/" + f, "commit": commit, "format": fmt, "classes": len(cls),
                          "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(), "_text": text, "_cls": cls})
    selected = []; decisions = []
    for f in files:
        reason = None
        if f["format"] not in ("2.0", "6.0"): reason = "signature format %s (not handled)" % f["format"]
        elif f["classes"] == 0: reason = "no classes"
        elif sdk is not None:
            frac = len(f["_cls"] & sdk) / float(f["classes"])
            f["in_sdk_fraction"] = round(frac, 4)
            # a public module API whose classes are mostly in the SDK is used whole (its few extra classes are
            # flagged APIs newer than the SDK build); files with almost none in the SDK are test/system libraries
            if frac < 0.5: reason = "only %.0f%% of its classes are in the SDK android.jar" % (100 * frac)
        decisions.append({k: v for k, v in f.items() if not k.startswith("_")} | {"used": reason is None, "reason": reason})
        if reason is None: selected.append(f)
    # keep a copy of every collected signature file (AOSP, Apache-2.0) so the result can be reproduced offline
    raw = os.path.join(a.out, "signature-files")
    for f in files:
        dst = os.path.join(raw, f["path"])
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with open(dst, "w", encoding="utf-8", newline="\n") as fh: fh.write(f["_text"])
    formats = sorted(set(f["format"] for f in selected))
    merged = ["// Signature format: %s" % (formats[0] if len(formats) == 1 else "MIXED " + ",".join(formats))]
    # format 6.0 files carry "// - key=value" property lines after the format line; keep the first file's set
    for f in selected[:1]:
        merged += [l for l in f["_text"].splitlines()[1:] if l.startswith("// - ")]
    union = set()
    for f in selected:
        body = [l for l in f["_text"].splitlines() if not l.startswith("// Signature format:") and not l.startswith("// - ")]
        merged += body; union |= f["_cls"]
    out_txt = os.path.join(a.out, "android-api-current.txt")
    with open(out_txt, "w", encoding="utf-8", newline="\n") as fh: fh.write("\n".join(merged) + "\n")
    rep = {"tag": a.tag, "pdf_like_projects_in_manifest": pdf_like, "projects": provenance, "files": decisions, "merged_sha256": hashlib.sha256(open(out_txt, "rb").read()).hexdigest(),
           "merged_classes": len(union)}
    if sdk is not None:
        rep["sdk_classes"] = len(sdk)
        rep["sdk_classes_missing_from_merged"] = len(sdk - union)
        rep["sdk_classes_missing_sample"] = sorted(sdk - union)[:400]
        rep["merged_classes_not_in_sdk"] = len(union - sdk)
        rep["merged_classes_not_in_sdk_sample"] = sorted(union - sdk)[:200]
    with open(os.path.join(a.out, "selection.json"), "w") as fh: json.dump(rep, fh, indent=1)
    print(json.dumps({k: v for k, v in rep.items() if k not in ("projects", "files", "sdk_classes_missing_sample", "merged_classes_not_in_sdk_sample")}, indent=1))


def read_cp(b):
    n = struct.unpack_from(">H", b, 8)[0]; cp = [None] * n; p = 10; i = 1
    while i < n:
        t = b[p]
        if t == 1:
            l = struct.unpack_from(">H", b, p + 1)[0]; cp[i] = (1, b[p + 3:p + 3 + l].decode("utf-8", "replace")); p += 3 + l
        elif t in (3, 4): p += 5
        elif t in (5, 6): p += 9; i += 1
        elif t in (7, 8, 16, 19, 20): cp[i] = (t, struct.unpack_from(">H", b, p + 1)[0]); p += 3
        elif t in (9, 10, 11, 12, 17, 18): p += 5
        elif t == 15: p += 4
        else: raise ValueError("tag %d" % t)
        i += 1
    return cp, p


def supers(b):
    """Superclass and interfaces (internal names) of a class file."""
    cp, p = read_cp(b)
    acc, this, sup, ni = struct.unpack_from(">HHHH", b, p)
    names = []
    if sup: names.append(cp[cp[sup][1]][1])
    for k in range(ni):
        names.append(cp[cp[struct.unpack_from(">H", b, p + 8 + 2 * k)[0]][1]][1])
    return names


def members(b):
    cp, p = read_cp(b)
    acc, this, sup, ni = struct.unpack_from(">HHHH", b, p); p += 8 + 2 * ni
    res = set()
    for kind in ("F", "M"):
        cnt = struct.unpack_from(">H", b, p)[0]; p += 2
        for _ in range(cnt):
            a, n, d, ac = struct.unpack_from(">HHHH", b, p); p += 8
            if a & 0x0005:  # public or protected
                res.add("%s %s%s" % (kind, cp[n][1], cp[d][1]))
            for _ in range(ac):
                l = struct.unpack_from(">I", b, p + 2)[0]; p += 6 + l
    return acc, res


def compare(a):
    rep = {}
    with zipfile.ZipFile(a.stubs) as zs, zipfile.ZipFile(a.compare_jar) as zj:
        mine = {n[:-6]: n for n in zs.namelist() if n.endswith(".class")}
        sdk = {n[:-6]: n for n in zj.namelist() if n.endswith(".class") and not n.startswith("META-INF/")}
        common = sorted(set(mine) & set(sdk))
        miss_members = 0; extra_members = 0; sample = []
        sdk_public = 0
        # members a class does not declare itself may still be reachable through its superclasses and interfaces in
        # the stubs (signature files leave out most overrides, e.g. toString()); only the rest are real gaps
        cache = {}
        def decl(c):
            if c not in cache:
                cache[c] = (members(zs.read(mine[c]))[1], supers(zs.read(mine[c]))) if c in mine else (set(), [])
            return cache[c]
        def reachable(c, m, seen):
            if c in seen: return False
            seen.add(c); own, up = decl(c)
            return m in own or any(reachable(x, m, seen) for x in up)
        gaps = 0; gap_ctor = 0; gap_sample = []
        for c in common:
            acc_s, ms = members(zj.read(sdk[c])); acc_m, mm = members(zs.read(mine[c]))
            if not acc_s & 0x0001: continue
            sdk_public += 1
            d = ms - mm
            miss_members += len(d); extra_members += len(mm - ms)
            if d and len(sample) < 300: sample.append({"class": c, "missing": sorted(d)[:8]})
            real = sorted(m for m in d if " <init>" in m or not any(reachable(x, m, set()) for x in decl(c)[1]))
            gaps += len(real); gap_ctor += sum(1 for m in real if " <init>" in m)
            if real and len(gap_sample) < 400: gap_sample.append({"class": c, "missing": real[:10]})
        rep = {"stubs_classes": len(mine), "sdk_classes": len(sdk), "common": len(common), "sdk_public_common": sdk_public,
               "sdk_only_classes": len(set(sdk) - set(mine)), "stubs_only_classes": len(set(mine) - set(sdk)),
               "sdk_only_sample": sorted(set(sdk) - set(mine))[:300], "stubs_only_sample": sorted(set(mine) - set(sdk))[:100],
               "public_or_protected_members_missing_in_stubs": miss_members, "members_only_in_stubs": extra_members,
               "missing_members_sample": sample,
               "missing_members_not_inherited": gaps, "missing_constructors": gap_ctor,
               "missing_members_not_inherited_sample": gap_sample}
    with open(a.out, "w") as fh: json.dump(rep, fh, indent=1)
    print(json.dumps({k: v for k, v in rep.items() if not k.endswith("sample")}, indent=1))


def main():
    ap = argparse.ArgumentParser(); sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("collect"); c.add_argument("--tag", required=True); c.add_argument("--out", required=True); c.add_argument("--compare-jar")
    k = sub.add_parser("compare"); k.add_argument("--stubs", required=True); k.add_argument("--compare-jar", required=True); k.add_argument("--out", required=True)
    a = ap.parse_args()
    collect(a) if a.cmd == "collect" else compare(a)


if __name__ == "__main__":
    main()
