#!/usr/bin/env python3
"""Resolve, download and census a pinned set of Maven artifacts for APK Builder 005 Stage 0.

Runs in GitHub Actions (it needs Google Maven and Maven Central). Python standard library only.

  maven_closure.py ROOTS_FILE OUT_DIR

ROOTS_FILE lines: "group:artifact:version" (# comments allowed). A line "force group:artifact:version"
forces that exact module to that version wherever it is requested (used for kotlin-stdlib).
A line "tool group:artifact:version" downloads that artifact alone (no transitive closure), e.g. R8 and ASM;
the version "latest-stable-9" picks the highest 9.x release from maven-metadata.xml.

Resolution follows Gradle closely enough for a pinned catalogue:
  * Gradle module metadata (.module) is preferred; the variant for an Android app's runtime classpath is
    chosen (androidJvm > jvm, release build type, android environment); "available-at" is followed.
  * Without a .module file the POM is used (compile and runtime scopes, no optional dependencies).
  * Conflicts: the highest requested version wins; dependency constraints raise versions of modules that
    are in the graph; "platform" dependencies contribute constraints only.
Every downloaded file is checked against the SHA-256 published in the .module file, or against the
repository's .sha1 file when there is no .module file. Nothing is executed from any download.
"""
import hashlib, io, json, os, re, sys, time, urllib.error, urllib.request, zipfile
import xml.etree.ElementTree as ET

REPOS = ["https://dl.google.com/dl/android/maven2/", "https://repo1.maven.org/maven2/"]
UA = {"User-Agent": "apk-builder-005-stage0/1.0"}
CACHE = {}


def fetch(url, binary=True, optional=False):
    if url in CACHE: return CACHE[url]
    last = None
    for attempt in range(4):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=120) as r:
                data = r.read()
            CACHE[url] = data if binary else data.decode("utf-8")
            return CACHE[url]
        except urllib.error.HTTPError as e:
            if e.code == 404:
                if optional: CACHE[url] = None; return None
                raise
            last = e
        except Exception as e:  # network hiccup
            last = e
        time.sleep(2 * (attempt + 1))
    if optional: return None
    raise RuntimeError("fetch failed: %s (%s)" % (url, last))


def base(g, a, v):
    return "%s/%s/%s/" % (g.replace(".", "/"), a, v)


def find_repo(g, a, v):
    for r in REPOS:
        if fetch(r + base(g, a, v) + "%s-%s.pom" % (a, v), optional=True) is not None:
            return r
    return None


def vkey(v):
    """Version ordering close to Gradle's: numeric parts numerically; dev < alpha < beta < rc < release."""
    parts = re.split(r"[.\-+_]", v)
    qual = {"dev": -5, "snapshot": -4, "alpha": -3, "a": -3, "beta": -2, "b": -2, "rc": -1, "cr": -1, "m": -3}
    out = []
    for p in parts:
        m = re.match(r"^(\d+)(.*)$", p)
        if m:
            out.append((2, int(m.group(1)), 0))
            if m.group(2):
                q = re.sub(r"\d+", "", m.group(2)).lower(); n = re.sub(r"\D", "", m.group(2))
                out.append((1, qual.get(q, 0), int(n) if n else 0))
        else:
            q = re.sub(r"\d+", "", p).lower(); n = re.sub(r"\D", "", p)
            out.append((1, qual.get(q, 0), int(n) if n else 0))
    out.append((3, 0, 0))  # release sorts after any qualifier
    return out


def pick_version(spec):
    if not spec: return None
    for k in ("strictly", "requires", "prefer"):
        if spec.get(k): return spec[k]
    return None


def variant_score(attrs):
    usage = attrs.get("org.gradle.usage")
    cat = attrs.get("org.gradle.category", "library")
    if cat != "library" or usage not in ("java-runtime", "kotlin-runtime"): return None
    if "org.gradle.docstype" in attrs: return None
    s = 0
    pt = attrs.get("org.jetbrains.kotlin.platform.type")
    if pt == "androidJvm": s += 20
    elif pt == "jvm": s += 10
    elif pt in ("common", "js", "wasm", "native"): return None
    if attrs.get("org.gradle.jvm.environment") == "android": s += 5
    elif attrs.get("org.gradle.jvm.environment") == "standard-jvm": s += 1
    bt = attrs.get("com.android.build.api.attributes.BuildTypeAttr")
    if bt == "release": s += 3
    elif bt is not None: s -= 10
    if attrs.get("org.gradle.libraryelements") in ("aar", "jar"): s += 1
    return s


def parse_pom(text):
    text = re.sub(r'\sxmlns="[^"]+"', "", text, count=1)
    root = ET.fromstring(text)
    def t(el, path):
        x = el.find(path); return x.text.strip() if x is not None and x.text else None
    props = {}
    pe = root.find("properties")
    if pe is not None:
        for c in pe: props[c.tag] = (c.text or "").strip()
    parent = None
    p = root.find("parent")
    if p is not None: parent = (t(p, "groupId"), t(p, "artifactId"), t(p, "version"))
    deps = []
    for d in root.findall("dependencies/dependency"):
        deps.append({"g": t(d, "groupId"), "a": t(d, "artifactId"), "v": t(d, "version"), "scope": t(d, "scope") or "compile",
                     "optional": (t(d, "optional") or "false") == "true", "type": t(d, "type") or "jar"})
    dm = {}
    for d in root.findall("dependencyManagement/dependencies/dependency"):
        dm[(t(d, "groupId"), t(d, "artifactId"))] = t(d, "version")
    lic = [(t(l, "name"), t(l, "url")) for l in root.findall("licenses/license")]
    return {"packaging": t(root, "packaging") or "jar", "props": props, "parent": parent, "deps": deps, "dm": dm,
            "licenses": lic, "name": t(root, "name"), "url": t(root, "url"),
            "g": t(root, "groupId"), "v": t(root, "version")}


def pom_info(g, a, v, depth=0):
    r = find_repo(g, a, v)
    if r is None: raise RuntimeError("no repository has %s:%s:%s" % (g, a, v))
    pom = parse_pom(fetch(r + base(g, a, v) + "%s-%s.pom" % (a, v), binary=False))
    props = {"project.version": v, "project.groupId": g, "version": v, "pom.version": v}
    dm = {}; lic = list(pom["licenses"])
    if pom["parent"] and depth < 6:
        pg, pa, pv = pom["parent"]
        try:
            par = pom_info(pg, pa, pv, depth + 1)
            props.update(par["props"]); dm.update(par["dm"])
            if not lic: lic = par["licenses"]
            props["project.parent.version"] = pv
        except Exception:
            pass
    props.update(pom["props"])
    def sub(s):
        if s is None: return None
        for _ in range(5):
            s2 = re.sub(r"\$\{([^}]+)\}", lambda m: props.get(m.group(1), m.group(0)), s)
            if s2 == s: break
            s = s2
        return s
    for k, val in pom["dm"].items(): dm[(sub(k[0]), sub(k[1]))] = sub(val)
    deps = []
    for d in pom["deps"]:
        dg, da = sub(d["g"]), sub(d["a"]); dv = sub(d["v"]) or dm.get((dg, da))
        deps.append(dict(d, g=dg, a=da, v=dv))
    return {"repo": r, "packaging": pom["packaging"], "props": props, "dm": dm, "deps": deps, "licenses": lic,
            "name": pom["name"], "url": pom["url"]}


class Resolver:
    def __init__(self):
        self.selected = {}       # (g,a) -> version
        self.requested = {}      # (g,a) -> {version: set(requesters)}
        self.constraints = {}    # (g,a) -> version (highest)
        self.forced = []         # (g, prefix, version)
        self.info = {}           # (g,a,v) -> resolved info
        self.platforms = set()

    def force_for(self, g, a):
        for fg, pre, fv in self.forced:
            if g == fg and a == pre: return fv
        return None

    def module_info(self, g, a, v):
        key = (g, a, v)
        if key in self.info: return self.info[key]
        repo = find_repo(g, a, v)
        if repo is None: raise RuntimeError("not found: %s:%s:%s" % key)
        pom = pom_info(g, a, v)
        mod_text = fetch(repo + base(g, a, v) + "%s-%s.module" % (a, v), binary=False, optional=True)
        info = {"g": g, "a": a, "v": v, "repo": repo, "licenses": pom["licenses"], "name": pom["name"], "url": pom["url"],
                "source": None, "deps": [], "constraints": [], "files": [], "variant": None, "redirect": None}
        if mod_text:
            mod = json.loads(mod_text)
            best = None
            for var in mod.get("variants", []):
                sc = variant_score(var.get("attributes", {}))
                if sc is not None and (best is None or sc > best[0]): best = (sc, var)
            if best is None:
                info["source"] = "module(no runtime variant)"
            else:
                var = best[1]; info["variant"] = var.get("name"); info["source"] = "module"
                if "available-at" in var:
                    at = var["available-at"]; info["redirect"] = (at["group"], at["module"], at["version"])
                for d in var.get("dependencies", []):
                    cat = (d.get("attributes") or {}).get("org.gradle.category")
                    info["deps"].append({"g": d["group"], "a": d["module"], "v": pick_version(d.get("version")),
                                         "platform": cat in ("platform", "enforced-platform")})
                for c in var.get("dependencyConstraints", []):
                    cv = pick_version(c.get("version"))
                    if cv: info["constraints"].append({"g": c["group"], "a": c["module"], "v": cv})
                for f in var.get("files", []):
                    info["files"].append({"name": f["name"], "url": repo + base(g, a, v) + f["url"], "sha256": f.get("sha256"), "size": f.get("size")})
        if info["source"] in (None, "module(no runtime variant)"):
            info["source"] = "pom"
            for d in pom["deps"]:
                if d["optional"] or d["scope"] not in ("compile", "runtime"): continue
                if d["type"] == "pom" or d["scope"] == "import": continue
                info["deps"].append({"g": d["g"], "a": d["a"], "v": d["v"], "platform": False})
            ext = "aar" if pom["packaging"] == "aar" else "jar"
            if pom["packaging"] != "pom":
                name = "%s-%s.%s" % (a, v, ext)
                info["files"].append({"name": name, "url": repo + base(g, a, v) + name, "sha256": None, "size": None, "sha1_url": repo + base(g, a, v) + name + ".sha1"})
        self.info[key] = info
        return info

    def request(self, g, a, v, by):
        fv = self.force_for(g, a)
        if fv: v = fv
        if v is None: v = self.constraints.get((g, a))
        if v is None: raise RuntimeError("no version for %s:%s (requested by %s)" % (g, a, by))
        self.requested.setdefault((g, a), {}).setdefault(v, set()).add(by)

    def resolve(self, roots):
        for _round in range(60):
            before = dict(self.selected)
            # choose the highest requested version (or a forced one), raised by constraints
            for (g, a), vers in self.requested.items():
                fv = self.force_for(g, a)
                best = fv or max(vers, key=vkey)
                c = self.constraints.get((g, a))
                if c and not fv and vkey(c) > vkey(best): best = c
                self.selected[(g, a)] = best
            # walk the graph from the roots with the current selection
            seen = set(); stack = [(g, a) for g, a, _ in roots]
            while stack:
                ga = stack.pop()
                if ga in seen: continue
                seen.add(ga)
                v = self.selected[ga]
                info = self.module_info(ga[0], ga[1], v)
                if info["redirect"]:
                    rg, ra, rv = info["redirect"]
                    self.request(rg, ra, rv, "%s:%s:%s (available-at)" % (ga[0], ga[1], v))
                    if (rg, ra) in self.selected: stack.append((rg, ra))
                for c in info["constraints"]:
                    k = (c["g"], c["a"])
                    if k not in self.constraints or vkey(c["v"]) > vkey(self.constraints[k]): self.constraints[k] = c["v"]
                for d in info["deps"]:
                    by = "%s:%s:%s" % (ga[0], ga[1], v)
                    if d["platform"]:
                        pv = d["v"]
                        if pv:
                            self.platforms.add((d["g"], d["a"], pv))
                            pinfo = self.module_info(d["g"], d["a"], pv)
                            for c in pinfo["constraints"] + [{"g": x["g"], "a": x["a"], "v": x["v"]} for x in pinfo["deps"] if x["v"]]:
                                k = (c["g"], c["a"])
                                if k not in self.constraints or vkey(c["v"]) > vkey(self.constraints[k]): self.constraints[k] = c["v"]
                        continue
                    self.request(d["g"], d["a"], d["v"], by)
                    if (d["g"], d["a"]) in self.selected: stack.append((d["g"], d["a"]))
            self.reachable = seen
            for (g, a), vers in self.requested.items():
                if (g, a) not in self.selected:
                    fv = self.force_for(g, a)
                    self.selected[(g, a)] = fv or max(vers, key=vkey)
            if self.selected == before: return
        raise RuntimeError("resolution did not converge")


def sha256(b): return hashlib.sha256(b).hexdigest()


def class_census(jar_bytes):
    out = {"classes": 0, "versions": {}, "indy": 0, "kotlin_metadata_max": None, "kotlin_modules": 0}
    try:
        z = zipfile.ZipFile(io.BytesIO(jar_bytes))
    except zipfile.BadZipFile:
        out["error"] = "not a zip"; return out
    mvmax = None
    for n in z.namelist():
        if n.endswith(".kotlin_module"): out["kotlin_modules"] += 1
        if not n.endswith(".class") or n.startswith("META-INF/versions/"): continue
        b = z.read(n)
        if len(b) < 10 or b[:4] != b"\xca\xfe\xba\xbe": continue
        out["classes"] += 1
        ver = b[7] | (b[6] << 8)
        out["versions"][str(ver)] = out["versions"].get(str(ver), 0) + 1
        # Exact count of CONSTANT_InvokeDynamic entries (lambdas, string concatenation, records ...).
        try:
            cnt = (b[8] << 8) | b[9]; p = 10; i = 1; indy = 0
            while i < cnt:
                t = b[p]
                if t == 1: p += 3 + ((b[p + 1] << 8) | b[p + 2])
                elif t in (3, 4): p += 5
                elif t in (5, 6): p += 9; i += 1
                elif t in (7, 8, 16, 19, 20): p += 3
                elif t in (9, 10, 11, 12, 17): p += 5
                elif t == 18: p += 5; indy += 1
                elif t == 15: p += 4
                else: raise ValueError("tag %d" % t)
                i += 1
            out["indy"] += indy
        except Exception:
            out.setdefault("unparsed", 0); out["unparsed"] += 1
    for n in z.namelist():
        if n.endswith(".kotlin_module"):
            b = z.read(n)
            if len(b) >= 4:
                cnt = int.from_bytes(b[0:4], "big")
                if 0 < cnt < 8 and len(b) >= 4 + 4 * cnt:
                    mv = tuple(int.from_bytes(b[4 + 4 * k:8 + 4 * k], "big") for k in range(cnt))
                    if mvmax is None or mv > mvmax: mvmax = mv
    out["kotlin_metadata_max"] = ".".join(map(str, mvmax)) if mvmax else None
    return out


def aar_census(b):
    out = {"type": "aar"}
    z = zipfile.ZipFile(io.BytesIO(b))
    names = z.namelist()
    meta = "META-INF/com/android/build/gradle/aar-metadata.properties"
    if meta in names:
        props = {}
        for line in z.read(meta).decode("utf-8", "replace").splitlines():
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1); props[k.strip()] = v.strip()
        out["aar_metadata"] = props
    if "AndroidManifest.xml" in names:
        mf = z.read("AndroidManifest.xml").decode("utf-8", "replace")
        m = re.search(r'android:minSdkVersion="([^"]+)"', mf); out["minSdk"] = m.group(1) if m else None
        out["manifest_components"] = sorted(set(re.findall(r"<(activity|service|receiver|provider)\b", mf)))
        out["manifest_permissions"] = sorted(set(re.findall(r'<uses-permission[^>]*android:name="([^"]+)"', mf)))
    out["res_files"] = len([n for n in names if n.startswith("res/") and not n.endswith("/")])
    out["has_R_txt"] = "R.txt" in names
    out["has_public_txt"] = "public.txt" in names
    out["jni"] = sorted(set(n.split("/")[1] for n in names if n.startswith("jni/") and n.count("/") >= 2))
    out["assets"] = len([n for n in names if n.startswith("assets/") and not n.endswith("/")])
    out["consumer_proguard"] = "proguard.txt" in names
    out["has_lint"] = "lint.jar" in names
    jars = [n for n in names if n == "classes.jar" or (n.startswith("libs/") and n.endswith(".jar"))]
    out["jars"] = {}
    for j in jars: out["jars"][j] = class_census(z.read(j))
    return out


def main():
    roots_file, out_dir = sys.argv[1], sys.argv[2]
    os.makedirs(out_dir, exist_ok=True)
    files_dir = os.path.join(out_dir, "files"); os.makedirs(files_dir, exist_ok=True)
    roots, tools = [], []
    res = Resolver()
    for raw in open(roots_file, encoding="utf-8"):
        line = raw.split("#", 1)[0].strip()
        if not line: continue
        if line.startswith("force "):
            g, pre, v = line[6:].strip().split(":"); res.forced.append((g, pre, v)); continue
        if line.startswith("tool "):
            tools.append(tuple(line[5:].strip().split(":"))); continue
        if line.startswith("bom "):
            continue
        g, a, v = line.split(":"); roots.append((g, a, v))
    for g, a, v in roots: res.request(g, a, v, "ROOT")
    res.resolve(roots)
    report = {"roots": [":".join(r) for r in roots], "forced": [":".join(f) for f in res.forced], "modules": [], "tools": [], "boms": []}
    sums = []
    for (g, a) in sorted(res.reachable):
        v = res.selected[(g, a)]
        info = res.module_info(g, a, v)
        entry = {"coordinate": "%s:%s:%s" % (g, a, v), "requested": {k: sorted(s) for k, s in res.requested.get((g, a), {}).items()},
                 "source": info["source"], "variant": info["variant"], "redirect": ":".join(info["redirect"]) if info["redirect"] else None,
                 "licenses": info["licenses"], "name": info["name"], "url": info["url"], "repo": info["repo"], "files": []}
        for f in info["files"]:
            data = fetch(f["url"])
            got = sha256(data)
            if f.get("sha256"):
                if got != f["sha256"]: raise RuntimeError("SHA-256 mismatch for %s" % f["url"])
                check = "sha256 from .module"
            else:
                s1 = fetch(f["sha1_url"], binary=False, optional=True)
                if s1:
                    if hashlib.sha1(data).hexdigest() != s1.strip().split()[0]: raise RuntimeError("SHA-1 mismatch for %s" % f["url"])
                    check = "sha1 from repository"
                else:
                    check = "UNVERIFIED (no checksum published)"
            rel = os.path.join(g, a, v, f["name"])
            path = os.path.join(files_dir, rel); os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as fh: fh.write(data)
            sums.append("%s  files/%s" % (got, rel))
            census = aar_census(data) if f["name"].endswith(".aar") else dict(class_census(data), type="jar") if f["name"].endswith(".jar") else {"type": "other"}
            entry["files"].append({"name": f["name"], "url": f["url"], "sha256": got, "size": len(data), "checked": check, "census": census})
        report["modules"].append(entry)
    for g, a, v in tools:
        repo = None
        if v.startswith("latest-stable-"):
            major = v.split("-")[-1]
            for r in REPOS:
                md = fetch(r + "%s/%s/maven-metadata.xml" % (g.replace(".", "/"), a), binary=False, optional=True)
                if not md: continue
                vers = re.findall(r"<version>([^<]+)</version>", md)
                stable = [x for x in vers if re.match(r"^%s\.\d+\.\d+$" % re.escape(major), x)]
                if stable:
                    v = max(stable, key=vkey); repo = r
                    report.setdefault("tool_versions_seen", {})["%s:%s" % (g, a)] = sorted(vers, key=vkey)[-25:]
                    break
        info = res.module_info(g, a, v)
        entry = {"coordinate": "%s:%s:%s" % (g, a, v), "licenses": info["licenses"], "repo": info["repo"], "files": []}
        for f in info["files"]:
            if not f["name"].endswith(".jar"): continue
            data = fetch(f["url"]); got = sha256(data)
            if f.get("sha256") and got != f["sha256"]: raise RuntimeError("SHA-256 mismatch for %s" % f["url"])
            rel = os.path.join(g, a, v, f["name"]); path = os.path.join(files_dir, rel); os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as fh: fh.write(data)
            sums.append("%s  files/%s" % (got, rel))
            entry["files"].append({"name": f["name"], "sha256": got, "size": len(data), "census": class_census(data)})
        report["tools"].append(entry)
    # BOM cross-check
    for raw in open(roots_file, encoding="utf-8"):
        line = raw.split("#", 1)[0].strip()
        if line.startswith("bom "):
            g, a, v = line[4:].strip().split(":")
            p = pom_info(g, a, v)
            diffs = []
            for (dg, da), dv in sorted(p["dm"].items()):
                sel = res.selected.get((dg, da))
                if sel and sel != dv: diffs.append({"module": "%s:%s" % (dg, da), "bom": dv, "selected": sel})
            report["boms"].append({"bom": "%s:%s:%s" % (g, a, v), "entries": len(p["dm"]), "differences_with_selection": diffs})
    with open(os.path.join(out_dir, "closure.json"), "w") as fh: json.dump(report, fh, indent=1, sort_keys=True)
    with open(os.path.join(out_dir, "SHA256SUMS.txt"), "w") as fh: fh.write("\n".join(sorted(sums, key=lambda s: s[66:])) + "\n")
    # human summary
    lines = ["# Maven closure", "", "| Module | Licence | File | Size | Classes | Class versions | minCompileSdk | minSdk |", "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    maxver = 0; mcs = []
    for m in report["modules"]:
        for f in m["files"]:
            c = f["census"]; lic = "; ".join(n or "?" for n, _ in m["licenses"]) or "?"
            if c.get("type") == "aar":
                cls = sum(j.get("classes", 0) for j in c["jars"].values()); vers = {}
                for j in c["jars"].values():
                    for k, n in j.get("versions", {}).items(): vers[k] = vers.get(k, 0) + n
                mc = c.get("aar_metadata", {}).get("minCompileSdk"); ms = c.get("minSdk")
                if mc: mcs.append(int(mc))
            else:
                cls = c.get("classes", 0); vers = c.get("versions", {}); mc = ms = ""
            if vers: maxver = max(maxver, max(int(k) for k in vers))
            lines.append("| %s | %s | %s | %d | %d | %s | %s | %s |" % (m["coordinate"], lic, f["name"], f["size"], cls, ",".join("%s:%d" % kv for kv in sorted(vers.items())), mc or "", ms or ""))
    lines += ["", "Highest class-file major version in the closure: %d (Java %d)" % (maxver, maxver - 44 if maxver else 0),
              "Highest minCompileSdk: %s" % (max(mcs) if mcs else "none declared"), ""]
    for t in report["tools"]: lines.append("Tool: %s (%s)" % (t["coordinate"], "; ".join(n or "?" for n, _ in t["licenses"])))
    for b in report["boms"]: lines.append("BOM %s: %d entries, %d differ from the selection" % (b["bom"], b["entries"], len(b["differences_with_selection"])))
    with open(os.path.join(out_dir, "SUMMARY.md"), "w") as fh: fh.write("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
