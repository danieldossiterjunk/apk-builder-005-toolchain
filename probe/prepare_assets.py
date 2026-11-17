#!/usr/bin/env python3
"""Prepare the input files and desktop reference results of the APK Builder 005 feasibility probe.

  prepare_assets.py --out ASSET_DIR --jni JNI_DIR --kotlin-dist KOTLINC_DIR --b004-assets B004_TOOLCHAIN_ASSETS
                    --closure CLOSURE_FILES_DIR --stubs ANDROID_STUBS_JAR --r8 R8_JAR
                    --aapt2-host AAPT2_LINUX --aapt2-android AAPT2_ANDROID_ARM64 --framework-table TABLE_APK
                    --samples SAMPLES_DIR --work WORK_DIR

Writes into ASSET_DIR (the probe's app/src/main/assets/probe):
  kotlin-compiler-dex.zip, kotlin-stdlib-2.4.0.jar   APK Builder 004's own files, unchanged (SHA-256 checked)
  compose-plugin-dex.jar     the official kotlinc 2.4.0 lib/compose-compiler-plugin.jar converted by D8 to DEX,
                             with its META-INF service and module files (what -Xplugin loads on ART)
  android-stubs.jar          API stubs the probe compiles against
  compile-classpath.zip      the library JARs (AAR classes.jar) of the pinned closure, flat, sorted names
  sample-compose.zip         the Compose sample (AndroidManifest.xml, src/...)
  ref-app-classes.jar        the sample compiled on the desktop by the official kotlinc 2.4.0 (JVM) + plugin
  r8-dex.zip                 R8/D8 9.5.32 converted to DEX by itself (plus its non-class resources)
  lambda-test.jar            the Java 8 desugaring sample compiled by javac --release 8
  libs-dex.zip               the whole library closure converted to DEX on the desktop by the same D8
  res-smoke.zip              the resource test project
  framework-table.apk        the AOSP framework resource table built by CI
  aar-res.zip                the res/ folders of every AAR in the closure, one folder per module
  MANIFEST.json              SHA-256 and size of every file above, and the desktop reference results
and JNI_DIR/arm64-v8a/libprobe_aapt2.so (the Android ARM64 AAPT2 built by CI).

Every reference result is produced here with exactly the arguments, order and inputs the phone uses, so a
byte-identical result on the phone is meaningful. Nothing is downloaded by this script.
"""
import argparse, hashlib, json, os, shutil, subprocess, sys, tempfile, zipfile

FIXED = (1980, 1, 1, 0, 0, 0)
D8_MIN_API = "29"


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""): h.update(b)
    return h.hexdigest()


def run(cmd, **kw):
    print("$ " + " ".join(cmd[:6]) + (" ... (%d args)" % len(cmd) if len(cmd) > 6 else ""), flush=True)
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, **kw)
    out = "\n".join(l for l in p.stdout.splitlines() if not l.startswith("Picked up"))
    if p.returncode != 0:
        print(out); raise SystemExit("command failed (%d): %s" % (p.returncode, cmd[0]))
    return out


def det_zip(out, entries):
    """entries: list of (name, bytes) written in the given order with fixed times; stored when already compressed."""
    with zipfile.ZipFile(out, "w") as z:
        for name, data in entries:
            zi = zipfile.ZipInfo(name, FIXED); zi.external_attr = 0o644 << 16
            zi.compress_type = zipfile.ZIP_STORED if name.endswith((".jar", ".zip", ".apk", ".png")) else zipfile.ZIP_DEFLATED
            z.writestr(zi, data)


def dir_entries(root, prefix=""):
    out = []
    for d, dirs, files in os.walk(root):
        dirs.sort()
        for f in sorted(files):
            p = os.path.join(d, f)
            out.append((prefix + os.path.relpath(p, root).replace(os.sep, "/"), open(p, "rb").read()))
    return out


def outputs(d):
    return {os.path.relpath(os.path.join(r, f), d).replace(os.sep, "/"): sha(os.path.join(r, f))
            for r, _, fs in os.walk(d) for f in fs}


def d8(r8, args):
    return run(["java", "-cp", r8, "com.android.tools.r8.D8"] + args)


def main():
    ap = argparse.ArgumentParser()
    for k in ("out", "jni", "kotlin-dist", "b004-assets", "closure", "stubs", "r8", "aapt2-host", "aapt2-android",
              "framework-table", "samples", "work"):
        ap.add_argument("--" + k, required=True)
    ap.add_argument("--expected-ci", help="JSON with smoke_arsc_sha256 / smoke_rtxt_sha256 from the CI framework job")
    a = ap.parse_args()
    out, work = os.path.abspath(a.out), os.path.abspath(a.work)
    shutil.rmtree(out, ignore_errors=True); os.makedirs(out)
    shutil.rmtree(work, ignore_errors=True); os.makedirs(work)
    files, expected = {}, {"p1": {}, "p2": {}, "p3": {}}
    kd = os.path.join(a.kotlin_dist, "lib")

    def add(name, what, src=None):
        dst = os.path.join(out, name)
        if src: shutil.copyfile(src, dst)
        files[name] = {"sha256": sha(dst), "bytes": os.path.getsize(dst), "what": what}

    # --- APK Builder 004 files, unchanged
    add("kotlin-compiler-dex.zip", "APK Builder 004 Kotlin compiler DEX pack (kotlinc-android 2.4.0), unchanged",
        os.path.join(a.b004_assets, "kotlin-compiler-dex.zip"))
    add("kotlin-stdlib-2.4.0.jar", "APK Builder 004 Kotlin standard library 2.4.0 (identical to the official JAR)",
        os.path.join(a.b004_assets, "kotlin-stdlib-2.4.0.jar"))
    add("android-stubs.jar", "Android API stubs the probe compiles against", a.stubs)
    stubs = os.path.join(out, "android-stubs.jar")
    stdlib = os.path.join(out, "kotlin-stdlib-2.4.0.jar")
    if sha(stdlib) != sha(os.path.join(kd, "kotlin-stdlib.jar")):
        raise SystemExit("004's kotlin-stdlib differs from the official kotlinc 2.4.0 one")

    # --- Compose compiler plugin as DEX (what -Xplugin= loads on the phone)
    plugin = os.path.join(kd, "compose-compiler-plugin.jar")
    pd = os.path.join(work, "plugin-dex"); os.makedirs(pd)
    d8(a.r8, ["--release", "--min-api", D8_MIN_API, "--lib", stubs, "--classpath", os.path.join(kd, "kotlin-compiler.jar"),
              "--classpath", stdlib, "--output", pd, plugin])
    ents = [("classes.dex", open(os.path.join(pd, "classes.dex"), "rb").read())]
    with zipfile.ZipFile(plugin) as z:
        for n in sorted(z.namelist()):
            if n.startswith("META-INF/") and not n.endswith("/") and n != "META-INF/MANIFEST.MF":
                ents.append((n, z.read(n)))
    det_zip(os.path.join(out, "compose-plugin-dex.jar"), ents)
    add("compose-plugin-dex.jar", "official kotlinc 2.4.0 compose-compiler-plugin.jar (sha256 %s) converted to DEX by D8 %s, with its META-INF service files"
        % (sha(plugin), "9.5.32"))

    # --- compile classpath: every library JAR of the closure (AAR classes.jar and libs/*.jar), sorted, flat
    jars = []
    for root, _, names in os.walk(a.closure):
        for n in names:
            rel = os.path.relpath(root, a.closure).split(os.sep)
            if len(rel) < 3: continue
            g, art, v = rel[-3:]
            if g in ("com.android.tools", "org.ow2.asm") or (g == "org.jetbrains.kotlin" and art == "kotlin-stdlib"): continue
            p = os.path.join(root, n); key = "%s__%s__%s" % (g, art, v)
            if n.endswith(".jar") and not n.endswith(("-sources.jar", "-javadoc.jar")):
                jars.append((key + ".jar", open(p, "rb").read()))
            elif n.endswith(".aar"):
                with zipfile.ZipFile(p) as z:
                    for m in sorted(z.namelist()):
                        if m == "classes.jar": jars.append((key + ".jar", z.read(m)))
                        elif m.startswith("libs/") and m.endswith(".jar"): jars.append((key + "__" + os.path.basename(m), z.read(m)))
    jars.sort()
    det_zip(os.path.join(out, "compile-classpath.zip"), jars)
    add("compile-classpath.zip", "%d library JARs of the pinned AndroidX/Compose/Material closure (Kotlin standard library excluded)" % len(jars))
    cpdir = os.path.join(work, "classpath"); os.makedirs(cpdir)
    for n, b in jars: open(os.path.join(cpdir, n), "wb").write(b)
    cp_jars = [os.path.join(cpdir, n) for n, _ in jars]

    # --- Compose sample and the desktop reference compile (official kotlinc 2.4.0 on the JVM, same arguments)
    sample = os.path.join(a.samples, "compose-hello")
    det_zip(os.path.join(out, "sample-compose.zip"), dir_entries(sample))
    add("sample-compose.zip", "Compose + Material 3 sample (MainActivity.kt and its manifest)")
    sdir = os.path.join(work, "sample"); os.makedirs(sdir)
    with zipfile.ZipFile(os.path.join(out, "sample-compose.zip")) as z: z.extractall(sdir)
    kotlinc = os.path.join(a.kotlin_dist, "bin", "kotlinc")
    cp = os.pathsep.join([stubs, stdlib] + cp_jars)
    for key, extra in (("classes", ["-Xplugin=" + plugin]), ("control_classes", [])):
        od = os.path.join(work, "p1-" + key)
        run([kotlinc, "-no-jdk", "-no-reflect", "-no-stdlib", "-jvm-target", "11"] + extra + ["-classpath", cp, "-d", od, os.path.join(sdir, "src")])
        expected["p1"][key] = outputs(od)
    ref = os.path.join(work, "p1-classes")
    det_zip(os.path.join(out, "ref-app-classes.jar"), dir_entries(ref))
    add("ref-app-classes.jar", "the Compose sample compiled on the desktop by the official kotlinc 2.4.0 + Compose plugin (input of P2)")

    # --- D8 itself as DEX
    r8d = os.path.join(work, "r8-dex"); os.makedirs(r8d)
    d8(a.r8, ["--release", "--min-api", D8_MIN_API, "--lib", stubs, "--output", r8d, a.r8])
    ents = [(n, open(os.path.join(r8d, n), "rb").read()) for n in sorted(os.listdir(r8d))]
    with zipfile.ZipFile(a.r8) as z:
        for n in sorted(z.namelist()):
            if not n.endswith((".class", "/")) and n != "META-INF/MANIFEST.MF" and not n.endswith((".SF", ".RSA", ".DSA")):
                ents.append((n, z.read(n)))
    det_zip(os.path.join(out, "r8-dex.zip"), ents)
    add("r8-dex.zip", "R8/D8 9.5.32 (Google Maven, sha256 %s) converted to DEX by itself, with its resources" % sha(a.r8))

    # --- P2 references: same arguments and order as the phone
    p2a = os.path.join(work, "p2-app")
    d8(a.r8, ["--release", "--min-api", D8_MIN_API, "--lib", stubs] + sum((["--classpath", j] for j in [stdlib] + cp_jars), [])
       + ["--output", p2a, os.path.join(out, "ref-app-classes.jar")])
    expected["p2"]["app_dex"] = outputs(p2a)
    lt_src = os.path.join(a.samples, "lambda-test", "src")
    ltc = os.path.join(work, "lambda-classes")
    run(["javac", "--release", "8", "-Xlint:-options", "-d", ltc] + [os.path.join(r, f) for r, _, fs in os.walk(lt_src) for f in fs if f.endswith(".java")])
    det_zip(os.path.join(out, "lambda-test.jar"), dir_entries(ltc))
    add("lambda-test.jar", "Java 8 desugaring sample compiled by javac --release 8")
    expected["p2"]["lambda_result"] = run(["java", "-cp", ltc, "org.apkbuilder.probe.lambda.LambdaTest"]).strip()
    p2b = os.path.join(work, "p2-lambda")
    d8(a.r8, ["--release", "--min-api", D8_MIN_API, "--lib", stubs, "--output", p2b, os.path.join(out, "lambda-test.jar")])
    expected["p2"]["lambda_dex"] = outputs(p2b)
    libdex = os.path.join(work, "libs-dex"); os.makedirs(libdex)
    d8(a.r8, ["--release", "--min-api", D8_MIN_API, "--lib", stubs, "--output", libdex, stdlib] + cp_jars)
    det_zip(os.path.join(out, "libs-dex.zip"), dir_entries(libdex))
    add("libs-dex.zip", "the library closure (Kotlin standard library + %d JARs) converted to DEX on the desktop by D8 9.5.32" % len(cp_jars))
    p2c = os.path.join(work, "p2-merged")
    d8(a.r8, ["--release", "--min-api", D8_MIN_API, "--output", p2c, os.path.join(p2a, "classes.dex")]
       + [os.path.join(libdex, n) for n in sorted(os.listdir(libdex)) if n.endswith(".dex")])
    expected["p2"]["merged"] = outputs(p2c)

    # --- P3: AAPT2, framework table, resource test project, library resources
    os.makedirs(os.path.join(a.jni, "arm64-v8a"), exist_ok=True)
    shutil.copyfile(a.aapt2_android, os.path.join(a.jni, "arm64-v8a", "libprobe_aapt2.so"))
    expected["p3"]["aapt2_sha256"] = sha(a.aapt2_android)
    add("framework-table.apk", "AOSP android-17.0.0_r1 framework resource table built by CI", a.framework_table)
    table = os.path.join(out, "framework-table.apk")
    det_zip(os.path.join(out, "res-smoke.zip"), dir_entries(os.path.join(a.samples, "res-smoke")))
    add("res-smoke.zip", "resource test project (values, styles, layouts, drawables, menus, xml, PNG)")
    if a.expected_ci:
        ci = json.load(open(a.expected_ci))
        expected["p3"]["smoke_arsc_sha256"] = ci["smoke_arsc_sha256"]; expected["p3"]["smoke_rtxt_sha256"] = ci["smoke_rtxt_sha256"]
    # library resources
    aar = []
    for root, _, names in os.walk(a.closure):
        for n in names:
            if not n.endswith(".aar"): continue
            g, art, v = os.path.relpath(root, a.closure).split(os.sep)[-3:]
            with zipfile.ZipFile(os.path.join(root, n)) as z:
                res = sorted(m for m in z.namelist() if m.startswith("res/") and not m.endswith("/"))
                if res:
                    aar += [("%s__%s__%s/%s" % (g, art, v, m), z.read(m)) for m in res]
    aar.sort()
    det_zip(os.path.join(out, "aar-res.zip"), aar)
    add("aar-res.zip", "res/ folders of every AAR of the closure (%d files)" % len(aar))
    libs = os.path.join(work, "p3-libs"); os.makedirs(libs)
    with zipfile.ZipFile(os.path.join(out, "aar-res.zip")) as z: z.extractall(libs)
    os.makedirs(os.path.join(libs, "_sample"))
    with zipfile.ZipFile(os.path.join(out, "sample-compose.zip")) as z: z.extractall(os.path.join(libs, "_sample"))
    names = sorted(n for n in os.listdir(libs) if not n.startswith("_") and os.path.isdir(os.path.join(libs, n, "res")))
    flats = os.path.join(libs, "_flat"); os.makedirs(flats)
    link = [a.aapt2_host, "link", "-o", os.path.join(libs, "_out.apk"), "-I", table, "--manifest", os.path.join(libs, "_sample", "AndroidManifest.xml"),
            "--min-sdk-version", "29", "--target-sdk-version", "36", "--version-code", "1", "--version-name", "1.0",
            "--auto-add-overlay", "--no-version-vectors", "--output-text-symbols", os.path.join(libs, "_R.txt")]
    for n in names:
        z = os.path.join(flats, n + ".zip")
        run([a.aapt2_host, "compile", "--dir", os.path.join(libs, n, "res"), "-o", z])
        link += ["-R", z]
    run(link)
    with zipfile.ZipFile(os.path.join(libs, "_out.apk")) as z:
        expected["p3"]["libs_arsc_sha256"] = hashlib.sha256(z.read("resources.arsc")).hexdigest()
    expected["p3"]["libs_rtxt_sha256"] = sha(os.path.join(libs, "_R.txt"))
    expected["p3"]["libs_modules"] = len(names)

    man = {"probe_version": "0.1.0", "files": dict(sorted(files.items())), "expected": expected,
           "tools": {"kotlinc": open(os.path.join(a.kotlin_dist, "build.txt")).read().strip(), "r8_jar_sha256": sha(a.r8),
                     "aapt2_host_sha256": sha(a.aapt2_host), "d8_min_api": int(D8_MIN_API)}}
    with open(os.path.join(out, "MANIFEST.json"), "w") as f:
        f.write(json.dumps(man, indent=1, sort_keys=False) + "\n")
    print(json.dumps({k: v["bytes"] for k, v in files.items()}, indent=1))
    print("libprobe_aapt2.so", os.path.getsize(os.path.join(a.jni, "arm64-v8a", "libprobe_aapt2.so")))


if __name__ == "__main__":
    main()
