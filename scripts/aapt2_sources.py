#!/usr/bin/env python3
"""Report and package the AOSP sources that AAPT2 is built from.

  aapt2_sources.py report RECIPE_DIR OUT_JSON
      Lists every ${SRC}/... path named in the recipe's CMake files (lib/, build-tools/aapt2.cmake, cmake/) that
      does not exist in RECIPE_DIR/src, grouped by CMake file, and every Android.bp of the AAPT2 dependency set.

  aapt2_sources.py pack RECIPE_DIR OUT_TAR_ZST
      Packs the source subset AAPT2 needs (no .git directories) into one tar.zst archive, with SOURCES.txt
      (repository, commit, URL) at its root. Licence and NOTICE files stay inside each repository directory.
"""
import json, os, re, subprocess, sys

# whole repositories AAPT2 and its libraries are built from (recipe src/<name>)
WHOLE = ["abseil-cpp", "boringssl", "core", "expat", "fmtlib", "googletest", "incremental_delivery", "jsoncpp",
         "libbase", "libpng", "libziparchive", "logging", "pcre", "protobuf", "selinux", "zlib", "brotli", "lz4",
         "zstd", "zopfli", "tinyxml2"]
# repositories of which only some directories are needed
PARTIAL = {
    "base": ["tools/aapt2", "libs/androidfw", "cmds/idmap2", "include", "NOTICE", "MODULE_LICENSE_APACHE2", "Android.bp"],
    "native": ["include", "libs/binder/include", "libs/arect", "libs/math", "NOTICE", "MODULE_LICENSE_APACHE2"],
    "soong": ["cc/libbuildversion", "LICENSE", "NOTICE"],
    "build": ["soong/licenses", "make/core/version_defaults.mk", "release", "LICENSE", "NOTICE"],
    "unwinding": ["libbacktrace/include", "libunwindstack/include", "NOTICE", "MODULE_LICENSE_APACHE2"],
}


def git_info(path):
    def g(*a):
        p = subprocess.run(["git", "-C", path] + list(a), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        return p.stdout.strip() if p.returncode == 0 else "n/a"
    return g("rev-parse", "HEAD"), g("config", "--get", "remote.origin.url")


def report(recipe, out):
    src = os.path.join(recipe, "src")
    files = []
    for d in ("lib", "build-tools", "cmake"):
        for root, _, names in os.walk(os.path.join(recipe, d)):
            files += [os.path.join(root, n) for n in names if n.endswith(".cmake") or n == "CMakeLists.txt"]
    missing = {}; total = 0
    for f in sorted(files):
        rel = os.path.relpath(f, recipe)
        if rel.startswith("build-tools/") and not rel.endswith(("aapt2.cmake", "CMakeLists.txt")):
            continue
        text = open(f, encoding="utf-8", errors="replace").read()
        for m in re.finditer(r"\$\{SRC\}/([A-Za-z0-9_./+-]+)", text):
            p = m.group(1).rstrip("/"); total += 1
            if "*" in p or "$" in p: continue
            if not os.path.exists(os.path.join(src, p)):
                missing.setdefault(rel, []).append(p)
    bps = []
    for repo in WHOLE + list(PARTIAL):
        base = os.path.join(src, repo)
        for root, dirs, names in os.walk(base):
            dirs[:] = [x for x in dirs if x != ".git"]
            if "Android.bp" in names:
                bps.append(os.path.relpath(os.path.join(root, "Android.bp"), src))
    rep = {"paths_checked": total, "missing_by_cmake_file": {k: sorted(set(v)) for k, v in missing.items()},
           "missing_count": sum(len(set(v)) for v in missing.values()), "android_bp_files": len(bps)}
    json.dump(rep, open(out, "w"), indent=1)
    print(json.dumps({k: v for k, v in rep.items() if k != "android_bp_files"}, indent=1))


def pack(recipe, out):
    src = os.path.join(recipe, "src")
    members = []; lines = []
    for repo in sorted(WHOLE + list(PARTIAL)):
        d = os.path.join(src, repo)
        if not os.path.isdir(d):
            lines.append("%s MISSING" % repo); continue
        commit, url = git_info(d)
        lines.append("%s %s %s" % (repo, commit, url))
        if repo in PARTIAL:
            members += ["src/%s/%s" % (repo, p) for p in PARTIAL[repo] if os.path.exists(os.path.join(d, p))]
        else:
            members.append("src/" + repo)
    with open(os.path.join(recipe, "SOURCES.txt"), "w") as fh:
        fh.write("\n".join(lines) + "\n")
    cmd = ["tar", "--zstd", "--exclude=.git", "--exclude=.git/*", "--sort=name", "--owner=0", "--group=0",
           "--numeric-owner", "--mtime=@0", "-cf", os.path.abspath(out), "-C", recipe, "SOURCES.txt"] + members
    subprocess.run(cmd, check=True)
    print("\n".join(lines))
    print("packed %d members into %s (%d bytes)" % (len(members), out, os.path.getsize(out)))


if __name__ == "__main__":
    {"report": report, "pack": pack}[sys.argv[1]](sys.argv[2], sys.argv[3])
