#!/usr/bin/env python3
"""Build the Android framework resource table (package 0x01) from AOSP source with a host AAPT2,
verify it, and test it by linking the resource smoke-test project against it.

  framework_table.py --aapt2 HOST_AAPT2 --core-res frameworks/base/core/res --tag TAG
                     --sample samples/res-smoke --out OUT [--compare-jar SDK_ANDROID_JAR]

Outputs in OUT:
  framework-res.apk                 the full linked framework package (Apache-2.0 sources)
  android-framework-table.apk       only AndroidManifest.xml + resources.arsc: what `aapt2 link -I` needs
  public-check.json                 every <public> entry of public-final.xml / public-staging.xml checked
                                    against the linked table (same id, same name, marked PUBLIC)
  smoke/                            the smoke-test project linked against the full and the stripped table
  compare-sdk.json                  (only with --compare-jar) public resources of the table against the SDK's
                                    android.jar; used for comparison only, nothing of the SDK is kept
  log-*.txt                         every command and its output
The script never executes anything from the inputs except the given AAPT2 binary.
"""
import argparse, hashlib, json, os, re, subprocess, sys, zipfile
import xml.etree.ElementTree as ET


def run(cmd, log, check=True):
    with open(log, "a", encoding="utf-8") as fh:
        fh.write("+ " + " ".join(cmd) + "\n")
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        fh.write(p.stdout + "\n[exit %d]\n" % p.returncode)
    if check and p.returncode != 0:
        tail = "\n".join(p.stdout.splitlines()[-60:])
        raise RuntimeError("command failed (%d): %s\n%s" % (p.returncode, " ".join(cmd), tail))
    return p


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""): h.update(b)
    return h.hexdigest()


def public_entries(values_dir):
    """All <public> declarations: explicit ids (public-final.xml) and staged groups (public-staging.xml)."""
    out = []
    for name in sorted(os.listdir(values_dir)):
        if not (name.startswith("public") and name.endswith(".xml")): continue
        root = ET.parse(os.path.join(values_dir, name)).getroot()
        for el in root:
            if el.tag == "public" and el.get("id"):
                out.append({"file": name, "type": el.get("type"), "name": el.get("name"), "id": int(el.get("id"), 16)})
            elif el.tag in ("staging-public-group", "staging-public-group-final", "public-group"):
                t = el.get("type"); nxt = int(el.get("first-id"), 16)
                for p in el:
                    if p.tag != "public": continue
                    if p.get("id"): nxt = int(p.get("id"), 16)
                    out.append({"file": name, "type": p.get("type") or t, "name": p.get("name"), "id": nxt, "group": el.tag})
                    nxt += 1
    return out


DUMP_RE = re.compile(r"^\s*resource (0x[0-9a-fA-F]{8}) ([A-Za-z0-9_-]+)/(\S+)(.*)$")


def dump_table(aapt2, apk, log):
    p = run([aapt2, "dump", "resources", apk], log, check=True)
    res = {}
    for line in p.stdout.splitlines():
        m = DUMP_RE.match(line)
        if m:
            rid = int(m.group(1), 16)
            res[rid] = {"type": m.group(2), "name": m.group(3), "flags": m.group(4).strip()}
    return res


def strip_table(full_apk, out_apk):
    with zipfile.ZipFile(full_apk) as zin, zipfile.ZipFile(out_apk, "w") as zout:
        for name in ("AndroidManifest.xml", "resources.arsc"):
            info = zipfile.ZipInfo(name, date_time=(2009, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_STORED if name == "resources.arsc" else zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            zout.writestr(info, zin.read(name))


def link_smoke(aapt2, sample, include, outdir, log, min_sdk="26", target_sdk="36"):
    os.makedirs(outdir, exist_ok=True)
    flat = os.path.join(outdir, "compiled.zip")
    run([aapt2, "compile", "--dir", os.path.join(sample, "res"), "-o", flat], log)
    apk = os.path.join(outdir, "smoke.apk")
    run([aapt2, "link", "-o", apk, "-I", include, "--manifest", os.path.join(sample, "AndroidManifest.xml"),
         "--min-sdk-version", min_sdk, "--target-sdk-version", target_sdk, "--version-code", "1", "--version-name", "1.0",
         "--java", os.path.join(outdir, "java"), "--output-text-symbols", os.path.join(outdir, "R.txt"), "--no-version-vectors",
         flat], log)
    with zipfile.ZipFile(apk) as z:
        arsc = z.read("resources.arsc"); names = sorted(z.namelist())
    return {"apk_sha256": sha256(apk), "resources_arsc_sha256": hashlib.sha256(arsc).hexdigest(), "entries": names,
            "r_txt_sha256": sha256(os.path.join(outdir, "R.txt"))}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--aapt2", required=True); ap.add_argument("--core-res", required=True); ap.add_argument("--tag", required=True)
    ap.add_argument("--sample", required=True); ap.add_argument("--out", required=True); ap.add_argument("--compare-jar")
    ap.add_argument("--api-level", default="37"); ap.add_argument("--version-name", default="17")
    ap.add_argument("--feature-flags-file", help="one name:PERMISSION=value per line (scripts/feature_flags.py)")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    log = os.path.join(a.out, "log-framework.txt")
    report = {"tag": a.tag, "aapt2": a.aapt2, "aapt2_sha256": sha256(a.aapt2)}
    report["aapt2_version"] = run([a.aapt2, "version"], log).stdout.strip()
    run([a.aapt2, "compile", "--help"], log, check=False); run([a.aapt2, "link", "--help"], log, check=False)
    ff = []
    if a.feature_flags_file:
        flags = [l.strip() for l in open(a.feature_flags_file) if l.strip()]
        ff = ["--feature-flags", ",".join(flags)]
        report["feature_flags"] = len(flags)
    compiled = os.path.join(a.out, "framework-compiled.zip")
    run([a.aapt2, "compile", "--dir", os.path.join(a.core_res, "res"), "-o", compiled] + ff, log)
    full = os.path.join(a.out, "framework-res.apk")
    base = [a.aapt2, "link", "-o", full, "--manifest", os.path.join(a.core_res, "AndroidManifest.xml"), "-x",
            "--private-symbols", "com.android.internal", "--no-auto-version", "--auto-add-overlay",
            "--min-sdk-version", a.api_level, "--target-sdk-version", a.api_level,
            "--version-code", a.api_level, "--version-name", a.version_name,
            "--emit-ids", os.path.join(a.out, "framework-ids.txt")] + ff
    attempts = [base + ["--enable-sparse-encoding", compiled], base + [compiled]]
    linked = None
    for i, cmd in enumerate(attempts):
        p = run(cmd, log, check=False)
        if p.returncode == 0: linked = i; break
    if linked is None: raise RuntimeError("framework link failed in every attempt; see log-framework.txt")
    report["link_attempt_used"] = linked
    report["link_command"] = " ".join(attempts[linked][1:]).replace(a.out + "/", "")
    report["framework_res_sha256"] = sha256(full)
    table = os.path.join(a.out, "android-framework-table.apk")
    strip_table(full, table)
    report["framework_table_sha256"] = sha256(table); report["framework_table_bytes"] = os.path.getsize(table)
    dumped = dump_table(a.aapt2, full, os.path.join(a.out, "log-dump.txt"))
    report["resources_in_table"] = len(dumped)
    report["public_in_table"] = sum(1 for r in dumped.values() if "PUBLIC" in r["flags"])
    # public-final / public-staging against the linked table
    pubs = public_entries(os.path.join(a.core_res, "res", "values"))
    bad = []; bad_final_alias = []
    for e in pubs:
        got = dumped.get(e["id"])
        if got is None or got["type"] != e["type"] or got["name"] != e["name"] or "PUBLIC" not in got["flags"]:
            # staging-public-group-final entries keep old staged ids as aliases of finalized resources;
            # they are reported separately and do not count as table errors
            (bad_final_alias if e.get("group") == "staging-public-group-final" else bad).append(dict(e, id="0x%08x" % e["id"], found=got))
    report["public_declared"] = len(pubs); report["public_mismatches"] = len(bad)
    report["public_staged_final_alias_unmatched"] = len(bad_final_alias)
    by_file = {}
    for e in pubs: by_file[e["file"] + ":" + e.get("group", "public")] = by_file.get(e["file"] + ":" + e.get("group", "public"), 0) + 1
    report["public_declared_by_source"] = by_file
    with open(os.path.join(a.out, "public-check.json"), "w") as fh:
        json.dump({"declared": len(pubs), "mismatches": bad[:500], "staged_final_alias_unmatched": bad_final_alias[:200]}, fh, indent=1)
    # smoke-test link against the full and the stripped table: the outputs must be identical
    r_full = link_smoke(a.aapt2, a.sample, full, os.path.join(a.out, "smoke", "full"), os.path.join(a.out, "log-smoke.txt"))
    r_strip = link_smoke(a.aapt2, a.sample, table, os.path.join(a.out, "smoke", "stripped"), os.path.join(a.out, "log-smoke.txt"))
    report["smoke_full"] = r_full; report["smoke_stripped"] = r_strip
    report["smoke_identical"] = r_full["resources_arsc_sha256"] == r_strip["resources_arsc_sha256"] and r_full["r_txt_sha256"] == r_strip["r_txt_sha256"]
    if a.compare_jar and os.path.exists(a.compare_jar):
        sdk = dump_table(a.aapt2, a.compare_jar, os.path.join(a.out, "log-dump-sdk.txt"))
        mine_pub = {(r["type"], r["name"]): rid for rid, r in dumped.items() if "PUBLIC" in r["flags"]}
        sdk_pub = {(r["type"], r["name"]): rid for rid, r in sdk.items() if "PUBLIC" in r["flags"]}
        only_mine = sorted("%s/%s" % k for k in set(mine_pub) - set(sdk_pub))
        only_sdk = sorted("%s/%s" % k for k in set(sdk_pub) - set(mine_pub))
        id_diff = sorted("%s/%s 0x%08x vs 0x%08x" % (k[0], k[1], mine_pub[k], sdk_pub[k]) for k in set(mine_pub) & set(sdk_pub) if mine_pub[k] != sdk_pub[k])
        r_sdk = link_smoke(a.aapt2, a.sample, a.compare_jar, os.path.join(a.out, "smoke", "sdk"), os.path.join(a.out, "log-smoke.txt"))
        cmp = {"sdk_public": len(sdk_pub), "table_public": len(mine_pub), "only_in_table": only_mine[:300], "only_in_sdk": only_sdk[:300],
               "only_in_table_count": len(only_mine), "only_in_sdk_count": len(only_sdk), "same_name_different_id": id_diff[:300],
               "same_name_different_id_count": len(id_diff),
               "smoke_r_txt_identical_to_sdk_link": r_sdk["r_txt_sha256"] == r_full["r_txt_sha256"],
               "smoke_arsc_identical_to_sdk_link": r_sdk["resources_arsc_sha256"] == r_full["resources_arsc_sha256"]}
        report["compare_sdk"] = {k: v for k, v in cmp.items() if not isinstance(v, list)}
        with open(os.path.join(a.out, "compare-sdk.json"), "w") as fh: json.dump(cmp, fh, indent=1)
        # nothing derived from the SDK file is kept apart from these comparison results
        for f in ("log-dump-sdk.txt",):
            try: os.remove(os.path.join(a.out, f))
            except OSError: pass
        import shutil; shutil.rmtree(os.path.join(a.out, "smoke", "sdk"), ignore_errors=True)
    with open(os.path.join(a.out, "framework-report.json"), "w") as fh: json.dump(report, fh, indent=1, sort_keys=True)
    print(json.dumps(report, indent=1, sort_keys=True))
    ok = report["public_mismatches"] == 0 and report["smoke_identical"]
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
