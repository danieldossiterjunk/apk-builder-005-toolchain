package org.apkbuilder.probe005;

import android.app.ActivityManager;
import android.content.Context;
import android.os.Build;
import android.os.Debug;
import android.system.Os;
import android.system.OsConstants;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.io.PrintStream;
import java.lang.reflect.InvocationTargetException;
import java.lang.reflect.Method;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.TreeMap;

import dalvik.system.DexClassLoader;

/**
 * The three APK Builder 005 feasibility tests, run on the phone:
 *
 *   P1  Kotlin compiler (APK Builder 004's bundled DEX pack, unchanged) with the Compose compiler plugin 2.4.0,
 *       compiling a small Compose + Material 3 screen; a second run without the plugin is the control.
 *   P2  D8 (R8 9.5.32, converted to DEX) running on ART: dex the desktop reference classes, desugar Java 8
 *       language features and run the result, merge with the pre-converted library DEX, then load every class.
 *   P3  AAPT2 (built from AOSP android-17.0.0_r1 for ARM64) run from this app's native library directory:
 *       version, compile and link a resource test project against the AOSP framework table, compare the
 *       table with this phone's own framework resources (comparison only), and link real AndroidX/Material
 *       library resources.
 *
 * Every input is a file inside this APK (assets/probe, listed with its SHA-256 in assets/probe/MANIFEST.json)
 * and is checked before use. Results are facts and checks; the owner decides PASS or FAIL.
 */
final class Probe {
    interface Log { void line(String s); }

    static final String VERSION = "0.1.0";
    private static final String ASSETS = "probe/";

    private final Context app;
    private final Log log;
    private final File base, inputs, work;
    private Map<String, Object> manifest;
    private ClassLoader kotlinLoader, r8Loader;

    Probe(Context app, Log log) {
        this.app = app;
        this.log = log;
        this.base = new File(app.getNoBackupFilesDir(), "probe");
        this.inputs = new File(base, "inputs");
        this.work = new File(base, "work");
    }

    // ------------------------------------------------------------------------------------------ inputs

    @SuppressWarnings("unchecked")
    private Map<String, Object> manifest() throws IOException {
        if (manifest == null) {
            try (InputStream in = app.getAssets().open(ASSETS + "MANIFEST.json")) {
                manifest = (Map<String, Object>) Json.parse(new String(Files2.readAll(in), StandardCharsets.UTF_8));
            }
        }
        return manifest;
    }

    @SuppressWarnings("unchecked")
    private Map<String, Object> expected(String test) throws IOException {
        Object e = ((Map<String, Object>) manifest().get("expected")).get(test);
        return e == null ? new LinkedHashMap<String, Object>() : (Map<String, Object>) e;
    }

    /** One input file, copied out of the APK on first use and checked against MANIFEST.json every time. Read-only. */
    @SuppressWarnings("unchecked")
    File input(String name) throws IOException {
        Map<String, Object> files = (Map<String, Object>) manifest().get("files");
        Map<String, Object> m = (Map<String, Object>) files.get(name);
        if (m == null) throw new IOException("input not listed in MANIFEST.json: " + name);
        String want = (String) m.get("sha256");
        File f = new File(inputs, name);
        if (f.isFile() && f.length() == ((Number) m.get("bytes")).longValue() && want.equals(Files2.sha256(f))) return f;
        Files2.mkdirs(inputs);
        f.setWritable(true);
        f.delete();
        File tmp = new File(inputs, name + ".tmp");
        try (InputStream in = app.getAssets().open(ASSETS + name); OutputStream out = new java.io.FileOutputStream(tmp)) {
            Files2.copy(in, out);
        }
        String got = Files2.sha256(tmp);
        if (!want.equals(got)) { tmp.delete(); throw new IOException(name + ": SHA-256 " + got + " differs from MANIFEST.json " + want); }
        if (!tmp.renameTo(f)) throw new IOException("cannot install " + name);
        // Android refuses to load code from writable files (targetSdk 34+), and inputs must not change anyway
        f.setWritable(false, false);
        return f;
    }

    /** Checks every listed input (copies it out if needed). */
    @SuppressWarnings("unchecked")
    Map<String, Object> checkInputs() throws IOException {
        Map<String, Object> files = (Map<String, Object>) manifest().get("files");
        List<Object> bad = new ArrayList<>();
        long t0 = System.nanoTime();
        for (String n : files.keySet()) {
            try { input(n); } catch (IOException e) { bad.add(n + ": " + e.getMessage()); }
        }
        return Json.map("listed", (long) files.size(), "problems", bad, "ms", ms(t0),
                "manifest_probe_version", manifest().get("probe_version"));
    }

    private File fresh(String name) throws IOException {
        File d = new File(work, name);
        Files2.deleteTree(d);
        Files2.mkdirs(d);
        return d;
    }

    private static long ms(long t0) { return (System.nanoTime() - t0) / 1_000_000; }

    private static Map<String, Object> check(String id, String what, boolean ok, Object detail) {
        return Json.map("id", id, "what", what, "result", ok ? "CHECK OK" : "CHECK FAILED", "detail", detail);
    }

    private static String trace(Throwable t) {
        java.io.StringWriter sw = new java.io.StringWriter();
        t.printStackTrace(new java.io.PrintWriter(sw));
        String s = sw.toString();
        return s.length() > 6000 ? s.substring(0, 6000) + "\n[truncated]" : s;
    }

    private Map<String, Object> memory() {
        Runtime r = Runtime.getRuntime();
        Debug.MemoryInfo mi = new Debug.MemoryInfo();
        Debug.getMemoryInfo(mi);
        return Json.map("java_heap_used_mb", (r.totalMemory() - r.freeMemory()) >> 20, "java_heap_max_mb", r.maxMemory() >> 20,
                "native_heap_allocated_mb", Debug.getNativeHeapAllocatedSize() >> 20, "total_pss_mb", (long) (mi.getTotalPss() >> 10));
    }

    // ------------------------------------------------------------------------------------------ environment

    Map<String, Object> environment() {
        Map<String, Object> e = new LinkedHashMap<>();
        e.put("manufacturer", Build.MANUFACTURER);
        e.put("model", Build.MODEL);
        e.put("device", Build.DEVICE);
        e.put("android_release", Build.VERSION.RELEASE);
        e.put("sdk_int", (long) Build.VERSION.SDK_INT);
        e.put("security_patch", Build.VERSION.SECURITY_PATCH);
        e.put("build_fingerprint", Build.FINGERPRINT);
        e.put("supported_abis", Arrays.<Object>asList((Object[]) Build.SUPPORTED_ABIS));
        e.put("kernel", System.getProperty("os.version"));
        e.put("java_vm_version", System.getProperty("java.vm.version"));
        try { e.put("page_size_bytes", Os.sysconf(OsConstants._SC_PAGESIZE)); } catch (Throwable t) { e.put("page_size_bytes", "unknown: " + t); }
        e.put("cpu_count", (long) Runtime.getRuntime().availableProcessors());
        ActivityManager am = (ActivityManager) app.getSystemService(Context.ACTIVITY_SERVICE);
        if (am != null) {
            ActivityManager.MemoryInfo mi = new ActivityManager.MemoryInfo();
            am.getMemoryInfo(mi);
            e.put("memory_class_mb", (long) am.getMemoryClass());
            e.put("large_memory_class_mb", (long) am.getLargeMemoryClass());
            e.put("device_total_ram_mb", mi.totalMem >> 20);
            e.put("device_available_ram_mb", mi.availMem >> 20);
        }
        e.put("java_heap_max_mb", Runtime.getRuntime().maxMemory() >> 20);
        e.put("free_private_storage_mb", app.getFilesDir().getUsableSpace() >> 20);
        e.put("native_library_dir", app.getApplicationInfo().nativeLibraryDir);
        e.put("probe_version", VERSION);
        return e;
    }

    // ------------------------------------------------------------------------------------------ P1 Kotlin + Compose

    private ClassLoader kotlin() throws IOException {
        if (kotlinLoader == null) {
            File dex = input("kotlin-compiler-dex.zip");
            // as APK Builder 004: parent is the boot class loader, so the compiler sees only its own pack
            kotlinLoader = new DexClassLoader(dex.getPath(), null, null, ClassLoader.getSystemClassLoader().getParent());
        }
        return kotlinLoader;
    }

    /** Runs K2JVMCompiler.exec(PrintStream, MessageRenderer.PLAIN_FULL_PATHS, args); returns [exitCode, messages]. */
    private String[] kotlinc(List<String> args) throws Exception {
        ClassLoader cl = kotlin();
        Class<?> k2 = Class.forName("org.jetbrains.kotlin.cli.jvm.K2JVMCompiler", true, cl);
        Class<?> renderer = Class.forName("org.jetbrains.kotlin.cli.common.messages.MessageRenderer", true, cl);
        Object plain = renderer.getField("PLAIN_FULL_PATHS").get(null);
        Method exec = k2.getMethod("exec", PrintStream.class, renderer, String[].class);
        ByteArrayOutputStream buf = new ByteArrayOutputStream();
        Object code;
        try (PrintStream ps = new PrintStream(buf, true, "UTF-8")) {
            code = exec.invoke(k2.getConstructor().newInstance(), ps, plain, (Object) args.toArray(new String[0]));
        } catch (InvocationTargetException e) {
            Throwable c = e.getCause() != null ? e.getCause() : e;
            if (c instanceof Exception) throw (Exception) c;
            throw new RuntimeException(c);
        }
        return new String[]{String.valueOf(code), new String(buf.toByteArray(), StandardCharsets.UTF_8)};
    }

    /** The compile classpath: Android API stubs, Kotlin standard library, then the library JARs in name order. */
    private List<File> compileClasspath() throws IOException {
        List<File> cp = new ArrayList<>();
        cp.add(input("android-stubs.jar"));
        cp.add(input("kotlin-stdlib-2.4.0.jar"));
        File dir = new File(work, "classpath");
        File stamp = new File(dir, ".sha256");
        String want = Files2.sha256(input("compile-classpath.zip"));
        if (!stamp.isFile() || !want.equals(new String(Files2.read(stamp), StandardCharsets.UTF_8))) {
            Files2.unzip(input("compile-classpath.zip"), dir);
            for (File f : Files2.listFiles(dir)) f.setWritable(false, false);
            Files2.write(stamp, want.getBytes(StandardCharsets.UTF_8));
        }
        for (File f : Files2.listFiles(dir)) if (f.getName().endsWith(".jar")) cp.add(f);
        return cp;
    }

    private static String joinPaths(List<File> fs) {
        StringBuilder sb = new StringBuilder();
        for (File f : fs) { if (sb.length() > 0) sb.append(File.pathSeparator); sb.append(f.getPath()); }
        return sb.toString();
    }

    /** SHA-256 of every output file, by path relative to dir. */
    private static Map<String, Object> outputs(File dir) throws IOException {
        Map<String, Object> m = new TreeMap<>();
        for (File f : Files2.listFiles(dir)) m.put(Files2.rel(dir, f).replace(File.separatorChar, '/'), Files2.sha256(f));
        return m;
    }

    @SuppressWarnings("unchecked")
    Map<String, Object> p1() {
        Map<String, Object> r = new LinkedHashMap<>();
        List<Object> checks = new ArrayList<>();
        r.put("test", "P1 Kotlin compiler (004 pack) + Compose compiler plugin 2.4.0");
        r.put("checks", checks);
        try {
            Map<String, Object> exp = expected("p1");
            File sample = fresh("p1-sample");
            Files2.unzip(input("sample-compose.zip"), sample);
            List<File> cp = compileClasspath();
            File plugin = input("compose-plugin-dex.jar");
            r.put("classpath_entries", (long) cp.size());

            // 1: the Compose sample with the plugin; 2 and 3: the control file with and without the plugin
            String[][] passes = {{"with_plugin", "src", "classes"}, {"control_with_plugin", "control", "control_with_plugin"},
                    {"control_without_plugin", "control", "control_without_plugin"}};
            for (String[] pass : passes) {
                String key = pass[0];
                boolean withPlugin = !key.endsWith("without_plugin");
                File out = fresh("p1-" + key);
                List<String> args = new ArrayList<>(Arrays.asList("-no-jdk", "-no-reflect", "-no-stdlib", "-jvm-target", "11"));
                if (withPlugin) args.add("-Xplugin=" + plugin.getPath());
                args.addAll(Arrays.asList("-classpath", joinPaths(cp), "-d", out.getPath(), new File(sample, pass[1]).getPath()));
                log.line("P1: compiling " + pass[1] + " " + (withPlugin ? "with" : "without") + " the Compose plugin ...");
                long t0 = System.nanoTime();
                String[] res = kotlinc(args);
                long took = ms(t0);
                Map<String, Object> run = new LinkedHashMap<>();
                run.put("exit", res[0]);
                run.put("ms", took);
                run.put("memory_after", memory());
                run.put("messages", res[1].length() > 8000 ? res[1].substring(0, 8000) + "\n[truncated]" : res[1]);
                Map<String, Object> outs = outputs(out);
                run.put("outputs", outs);
                Map<String, Object> ref = (Map<String, Object>) exp.get(pass[2]);
                run.put("same_as_desktop", ref != null && ref.equals(outs));
                if (ref != null && !ref.equals(outs)) run.put("difference_from_desktop", diff(ref, outs));
                log.line("P1: " + key + " exit " + res[0] + " in " + took + " ms");
                String cls = "src".equals(pass[1]) ? "org/apkbuilder/probe/compose/MainActivityKt.class" : "org/apkbuilder/probe/compose/control/ControlKt.class";
                File cf = new File(out, cls);
                List<String> methods = cf.isFile() ? Bytecode.classMethods(Files2.read(cf)) : new ArrayList<String>();
                run.put("methods_of_" + cf.getName(), new ArrayList<Object>(methods));
                r.put(key, run);
                if ("with_plugin".equals(key)) {
                    checks.add(check("P1.1", "kotlinc exits OK compiling the Compose sample with -Xplugin=compose-plugin-dex.jar", "OK".equals(res[0]), res[0]));
                    checks.add(check("P1.2", "Counter() was transformed by the Compose plugin: Counter(Landroidx/compose/runtime/Composer;I)V",
                            methods.contains("Counter (Landroidx/compose/runtime/Composer;I)V"), methods));
                    checks.add(check("P1.3", "output files identical to the official kotlinc 2.4.0 on the desktop JVM (information: a difference is not by itself a failure)",
                            ref != null && ref.equals(outs), diff(ref, outs)));
                } else if (withPlugin) {
                    checks.add(check("P1.4", "control with the plugin: label(String) gains the Composer parameters",
                            "OK".equals(res[0]) && methods.contains("label (Ljava/lang/String;Landroidx/compose/runtime/Composer;I)Ljava/lang/String;"), methods));
                } else {
                    checks.add(check("P1.5", "control without the plugin: label(String) keeps its plain signature (so P1.2 and P1.4 come from the plugin)",
                            "OK".equals(res[0]) && methods.contains("label (Ljava/lang/String;)Ljava/lang/String;"), methods));
                }
            }
            r.put("status", "COMPLETED");
        } catch (Throwable t) {
            r.put("status", "ERROR");
            r.put("error", trace(t));
            log.line("P1: ERROR " + t);
        }
        return r;
    }

    private static Object diff(Map<String, Object> ref, Map<String, Object> got) {
        if (ref == null) return "no reference in MANIFEST.json";
        if (ref.equals(got)) return "identical (" + ref.size() + " files)";
        Map<String, Object> d = new TreeMap<>();
        for (String k : ref.keySet()) if (!ref.get(k).equals(got.get(k))) d.put(k, Json.map("desktop", ref.get(k), "phone", got.get(k)));
        for (String k : got.keySet()) if (!ref.containsKey(k)) d.put(k, Json.map("desktop", null, "phone", got.get(k)));
        return d;
    }

    // ------------------------------------------------------------------------------------------ P2 D8

    private ClassLoader r8() throws IOException {
        if (r8Loader == null) {
            File dex = input("r8-dex.zip");
            r8Loader = new DexClassLoader(dex.getPath(), null, null, ClassLoader.getSystemClassLoader().getParent());
        }
        return r8Loader;
    }

    /** D8Command.parse(args, Origin.root()).build() then D8.run(command); diagnostics captured from System.out/err. */
    private Map<String, Object> d8(List<String> args) throws Exception {
        ClassLoader cl = r8();
        Class<?> cmdC = Class.forName("com.android.tools.r8.D8Command", true, cl);
        Class<?> originC = Class.forName("com.android.tools.r8.origin.Origin", true, cl);
        Object root = originC.getMethod("root").invoke(null);
        PrintStream oldOut = System.out, oldErr = System.err;
        ByteArrayOutputStream buf = new ByteArrayOutputStream();
        PrintStream cap = new PrintStream(buf, true, "UTF-8");
        long t0 = System.nanoTime();
        String error = null;
        System.setOut(cap);
        System.setErr(cap);
        try {
            Object builder = cmdC.getMethod("parse", String[].class, originC).invoke(null, args.toArray(new String[0]), root);
            Object cmd = builder.getClass().getMethod("build").invoke(builder);
            Class.forName("com.android.tools.r8.D8", true, cl).getMethod("run", cmdC).invoke(null, cmd);
        } catch (InvocationTargetException e) {
            Throwable c = e.getCause() != null ? e.getCause() : e;
            error = trace(c);
        } finally {
            System.setOut(oldOut);
            System.setErr(oldErr);
        }
        String msgs = new String(buf.toByteArray(), StandardCharsets.UTF_8);
        return Json.map("ok", error == null, "ms", ms(t0), "messages", msgs.length() > 6000 ? msgs.substring(0, 6000) + "\n[truncated]" : msgs,
                "error", error, "memory_after", memory());
    }

    private static List<String> d8Base(File stubs, List<File> classpath, File out) {
        List<String> a = new ArrayList<>(Arrays.asList("--release", "--min-api", "29", "--lib", stubs.getPath()));
        for (File f : classpath) { a.add("--classpath"); a.add(f.getPath()); }
        a.add("--output");
        a.add(out.getPath());
        return a;
    }

    @SuppressWarnings("unchecked")
    Map<String, Object> p2() {
        Map<String, Object> r = new LinkedHashMap<>();
        List<Object> checks = new ArrayList<>();
        r.put("test", "P2 D8 (R8 9.5.32) on ART");
        r.put("checks", checks);
        try {
            Map<String, Object> exp = expected("p2");
            File stubs = input("android-stubs.jar");
            List<File> cp = compileClasspath();
            List<File> d8cp = new ArrayList<>(cp.subList(1, cp.size()));   // Kotlin standard library + library JARs

            // P2a: the desktop reference classes of the Compose sample -> classes.dex
            File outA = fresh("p2-app");
            List<String> a = d8Base(stubs, d8cp, outA);
            a.add(input("ref-app-classes.jar").getPath());
            log.line("P2: D8 on the Compose sample classes ...");
            Map<String, Object> runA = d8(a);
            runA.put("outputs", outputs(outA));
            r.put("dex_app", runA);
            checks.add(check("P2.1", "D8 converts the Compose sample classes (no error)", Boolean.TRUE.equals(runA.get("ok")), runA.get("error")));
            checks.add(check("P2.2", "the DEX is byte-identical to D8 9.5.32 on the desktop JVM with the same inputs",
                    exp.get("app_dex") != null && exp.get("app_dex").equals(runA.get("outputs")), diff((Map<String, Object>) exp.get("app_dex"), (Map<String, Object>) runA.get("outputs"))));

            // P2b: Java 8 language features (lambdas, default/static interface methods, try-with-resources), then run them
            File outB = fresh("p2-lambda");
            List<String> b = d8Base(stubs, new ArrayList<File>(), outB);
            b.add(input("lambda-test.jar").getPath());
            log.line("P2: D8 desugaring test ...");
            Map<String, Object> runB = d8(b);
            runB.put("outputs", outputs(outB));
            r.put("desugar", runB);
            checks.add(check("P2.3", "D8 desugars the Java 8 test class (no error)", Boolean.TRUE.equals(runB.get("ok")), runB.get("error")));
            checks.add(check("P2.4", "desugared DEX byte-identical to the desktop result",
                    exp.get("lambda_dex") != null && exp.get("lambda_dex").equals(runB.get("outputs")), diff((Map<String, Object>) exp.get("lambda_dex"), (Map<String, Object>) runB.get("outputs"))));
            String result;
            try {
                File dex = new File(outB, "classes.dex");
                dex.setWritable(false, false);
                ClassLoader l = new DexClassLoader(dex.getPath(), null, null, ClassLoader.getSystemClassLoader().getParent());
                result = String.valueOf(Class.forName("org.apkbuilder.probe.lambda.LambdaTest", true, l).getMethod("run").invoke(null));
            } catch (Throwable t) {
                result = "ERROR " + trace(t instanceof InvocationTargetException && t.getCause() != null ? t.getCause() : t);
            }
            r.put("desugar_run_result", result);
            checks.add(check("P2.5", "the desugared code runs on ART and returns the same text as on the desktop JVM",
                    result.equals(exp.get("lambda_result")), Json.map("phone", result, "desktop", exp.get("lambda_result"))));

            // P2c: merge the app DEX with the pre-converted library DEX (Compose, Material 3, AndroidX, Kotlin)
            File libs = fresh("p2-libdex");
            Files2.unzip(input("libs-dex.zip"), libs);
            File outC = fresh("p2-merged");
            List<String> c = new ArrayList<>(Arrays.asList("--release", "--min-api", "29", "--output", outC.getPath(), new File(outA, "classes.dex").getPath()));
            for (File f : Files2.listFiles(libs)) if (f.getName().endsWith(".dex")) c.add(f.getPath());
            log.line("P2: D8 merging app and library DEX ...");
            Map<String, Object> runC = d8(c);
            runC.put("outputs", outputs(outC));
            r.put("merge", runC);
            checks.add(check("P2.6", "D8 merges app and library DEX (no error)", Boolean.TRUE.equals(runC.get("ok")), runC.get("error")));
            checks.add(check("P2.7", "merged DEX files byte-identical to the desktop merge",
                    exp.get("merged") != null && exp.get("merged").equals(runC.get("outputs")), diff((Map<String, Object>) exp.get("merged"), (Map<String, Object>) runC.get("outputs"))));

            // P2d: load every class of the merged DEX in ART (linking), then initialise the sample's own classes
            log.line("P2: loading every class of the merged DEX ...");
            List<File> merged = new ArrayList<>();
            for (File f : Files2.listFiles(outC)) if (f.getName().endsWith(".dex")) { f.setWritable(false, false); merged.add(f); }
            r.put("load", loadAll(merged));
            Map<String, Object> load = (Map<String, Object>) r.get("load");
            checks.add(check("P2.8", "every class of the merged DEX loads in ART without VerifyError (information: other link errors are listed)",
                    ((Number) load.get("verify_errors")).longValue() == 0 && ((Number) load.get("classes")).longValue() > 0, load.get("errors_by_type")));
            checks.add(check("P2.9", "the sample's own classes initialise (MainActivityKt, ComposableSingletons)",
                    Boolean.TRUE.equals(load.get("sample_classes_initialised")), load.get("sample_init")));
            r.put("status", "COMPLETED");
        } catch (Throwable t) {
            r.put("status", "ERROR");
            r.put("error", trace(t));
            log.line("P2: ERROR " + t);
        }
        return r;
    }

    private Map<String, Object> loadAll(List<File> dexFiles) throws IOException {
        List<String> names = new ArrayList<>();
        for (File f : dexFiles) names.addAll(Bytecode.dexClasses(Files2.read(f)));
        ClassLoader l = new DexClassLoader(joinPaths(dexFiles), null, null, ClassLoader.getSystemClassLoader().getParent());
        long t0 = System.nanoTime();
        Map<String, Object> byType = new TreeMap<>();
        Map<String, List<Object>> samples = new TreeMap<>();
        long verify = 0, ok = 0;
        for (String n : names) {
            try { Class.forName(n, false, l); ok++; }
            catch (Throwable t) {
                String k = t.getClass().getName();
                if (t instanceof VerifyError) verify++;
                byType.put(k, ((Number) (byType.containsKey(k) ? byType.get(k) : 0L)).longValue() + 1);
                List<Object> s = samples.get(k);
                if (s == null) { s = new ArrayList<>(); samples.put(k, s); }
                if (s.size() < 15) s.add(n + ": " + t.getMessage());
            }
        }
        long loadMs = ms(t0);
        Map<String, Object> init = new LinkedHashMap<>();
        boolean allInit = true;
        for (String n : new String[]{"org.apkbuilder.probe.compose.MainActivityKt", "org.apkbuilder.probe.compose.ComposableSingletons$MainActivityKt",
                "org.apkbuilder.probe.compose.MainActivity", "androidx.compose.runtime.ComposerKt"}) {
            try { Class.forName(n, true, l); init.put(n, "initialised"); }
            catch (Throwable t) { allInit = false; init.put(n, t.getClass().getName() + ": " + t.getMessage()); }
        }
        return Json.map("dex_files", (long) dexFiles.size(), "classes", (long) names.size(), "loaded", ok, "verify_errors", verify,
                "errors_by_type", byType, "error_samples", samples, "ms", loadMs, "sample_init", init, "sample_classes_initialised", allInit,
                "memory_after", memory());
    }

    // ------------------------------------------------------------------------------------------ P3 AAPT2

    private File aapt2() throws IOException {
        File f = new File(app.getApplicationInfo().nativeLibraryDir, "libprobe_aapt2.so");
        if (!f.isFile()) throw new IOException("AAPT2 is not installed in the native library directory: " + f);
        return f;
    }

    private Map<String, Object> procInfo(Proc p) {
        return Json.map("cmd", p.cmd.subList(1, p.cmd.size()).toString(), "exit", (long) p.exit, "timed_out", p.timedOut, "ms", p.ms, "output", p.brief(60));
    }

    @SuppressWarnings("unchecked")
    Map<String, Object> p3() {
        Map<String, Object> r = new LinkedHashMap<>();
        List<Object> checks = new ArrayList<>();
        r.put("test", "P3 AAPT2 (AOSP android-17.0.0_r1, ARM64, static) from the native library directory");
        r.put("checks", checks);
        try {
            Map<String, Object> exp = expected("p3");
            Files2.mkdirs(work);
            File aapt2 = aapt2();
            String a = aapt2.getPath();
            r.put("aapt2", Json.map("path", a, "bytes", aapt2.length(), "sha256", Files2.sha256(aapt2)));
            checks.add(check("P3.0", "installed AAPT2 is the binary built by CI", Files2.sha256(aapt2).equals(exp.get("aapt2_sha256")),
                    Json.map("phone", Files2.sha256(aapt2), "ci", exp.get("aapt2_sha256"))));

            Proc v = Proc.run(work, 60, a, "version");
            r.put("version", procInfo(v));
            checks.add(check("P3.1", "aapt2 version runs (exit 0)", v.exit == 0, v.output.trim()));

            // P3b: resource test project linked against the AOSP framework table
            File table = input("framework-table.apk");
            File smoke = fresh("p3-smoke");
            Files2.unzip(input("res-smoke.zip"), smoke);
            File flat = new File(smoke, "compiled.zip"), apk = new File(smoke, "smoke.apk"), rtxt = new File(smoke, "R.txt");
            log.line("P3: compile and link the resource test project ...");
            Proc c = Proc.run(smoke, 300, a, "compile", "--dir", new File(smoke, "res").getPath(), "-o", flat.getPath());
            Proc l = Proc.run(smoke, 300, a, "link", "-o", apk.getPath(), "-I", table.getPath(), "--manifest", new File(smoke, "AndroidManifest.xml").getPath(),
                    "--min-sdk-version", "26", "--target-sdk-version", "36", "--version-code", "1", "--version-name", "1.0",
                    "--java", new File(smoke, "java").getPath(), "--output-text-symbols", rtxt.getPath(), "--no-version-vectors", flat.getPath());
            Map<String, Object> sm = Json.map("compile", procInfo(c), "link", procInfo(l));
            String arsc = null, rt = null;
            if (l.exit == 0) {
                arsc = Files2.sha256(Files2.entry(apk, "resources.arsc"));
                rt = Files2.sha256(rtxt);
                sm.put("resources_arsc_sha256", arsc);
                sm.put("r_txt_sha256", rt);
                sm.put("apk_sha256", Files2.sha256(apk));
            }
            r.put("smoke", sm);
            checks.add(check("P3.2", "compile and link of the resource test project succeed", c.exit == 0 && l.exit == 0, null));
            checks.add(check("P3.3", "resources.arsc and R.txt byte-identical to the desktop and ARM64-runner builds of the same AAPT2",
                    arsc != null && arsc.equals(exp.get("smoke_arsc_sha256")) && rt.equals(exp.get("smoke_rtxt_sha256")),
                    Json.map("phone_arsc", arsc, "ci_arsc", exp.get("smoke_arsc_sha256"), "phone_rtxt", rt, "ci_rtxt", exp.get("smoke_rtxt_sha256"))));

            // P3c: this phone's framework resources, for comparison only (public resource IDs)
            File phoneFw = new File("/system/framework/framework-res.apk");
            log.line("P3: comparing the framework table with this phone's framework resources ...");
            Map<String, Object> cmp = new LinkedHashMap<>();
            if (phoneFw.canRead()) {
                File d1 = new File(work, "dump-table.txt"), d2 = new File(work, "dump-phone.txt");
                Proc p1 = dump(a, table, d1), p2 = dump(a, phoneFw, d2);
                cmp.put("dump_table", procInfo(p1));
                cmp.put("dump_phone", procInfo(p2));
                if (p1.exit == 0 && p2.exit == 0) {
                    Map<String, String> ours = publicIds(d1), phone = publicIds(d2);
                    List<Object> onlyOurs = new ArrayList<>(), onlyPhone = new ArrayList<>(), differ = new ArrayList<>();
                    long same = 0, onlyOursN = 0, onlyPhoneN = 0, differN = 0;
                    for (Map.Entry<String, String> e : ours.entrySet()) {
                        String p = phone.get(e.getKey());
                        if (p == null) { onlyOursN++; if (onlyOurs.size() < 40) onlyOurs.add(e.getKey() + " " + e.getValue()); }
                        else if (!p.equals(e.getValue())) { differN++; if (differ.size() < 40) differ.add(e.getKey() + " table " + e.getValue() + " phone " + p); }
                        else same++;
                    }
                    for (Map.Entry<String, String> e : phone.entrySet()) if (!ours.containsKey(e.getKey())) { onlyPhoneN++; if (onlyPhone.size() < 40) onlyPhone.add(e.getKey() + " " + e.getValue()); }
                    cmp.putAll(Json.map("public_in_table", (long) ours.size(), "public_on_phone", (long) phone.size(), "same_id", same,
                            "different_id", differN, "only_in_table", onlyOursN, "only_on_phone", onlyPhoneN,
                            "different_id_sample", differ, "only_in_table_sample", onlyOurs, "only_on_phone_sample", onlyPhone));
                    checks.add(check("P3.4", "every public resource present in both has the same ID (comparison only; the phone's resources are not used)",
                            differN == 0 && same > 0, Json.map("same", same, "different", differN, "only_in_table", onlyOursN, "only_on_phone", onlyPhoneN)));
                }
                d1.delete();
                d2.delete();
            } else {
                cmp.put("note", "cannot read " + phoneFw);
            }
            r.put("phone_framework_comparison", cmp);

            // P3d: real library resources (AndroidX, Material, Compose) compiled and linked with the Compose sample manifest
            log.line("P3: compile and link AndroidX / Material library resources ...");
            File libs = fresh("p3-libs");
            Files2.unzip(input("aar-res.zip"), libs);
            Files2.unzip(input("sample-compose.zip"), new File(libs, "_sample"));
            File[] mods = libs.listFiles();
            List<String> names = new ArrayList<>();
            if (mods != null) for (File m : mods) if (m.isDirectory() && !m.getName().startsWith("_") && new File(m, "res").isDirectory()) names.add(m.getName());
            java.util.Collections.sort(names);
            File flats = new File(libs, "_flat");
            Files2.mkdirs(flats);
            long compileMs = 0;
            int compileFail = 0;
            List<String> link = new ArrayList<>(Arrays.asList(a, "link", "-o", new File(libs, "_out.apk").getPath(), "-I", table.getPath(),
                    "--manifest", new File(libs, "_sample/AndroidManifest.xml").getPath(), "--min-sdk-version", "29", "--target-sdk-version", "36",
                    "--version-code", "1", "--version-name", "1.0", "--auto-add-overlay", "--no-version-vectors",
                    "--output-text-symbols", new File(libs, "_R.txt").getPath()));
            List<Object> failures = new ArrayList<>();
            for (String n : names) {
                File z = new File(flats, n + ".zip");
                Proc pc = Proc.run(libs, 300, a, "compile", "--dir", new File(new File(libs, n), "res").getPath(), "-o", z.getPath());
                compileMs += pc.ms;
                if (pc.exit != 0) { compileFail++; failures.add(Json.map("module", n, "result", procInfo(pc))); }
                link.add("-R");
                link.add(z.getPath());
            }
            Proc pl = Proc.run(libs, 600, link.toArray(new String[0]));
            Map<String, Object> lr = Json.map("modules", (long) names.size(), "compile_ms_total", compileMs, "compile_failures", failures, "link", procInfo(pl));
            String libArsc = null;
            if (pl.exit == 0) {
                libArsc = Files2.sha256(Files2.entry(new File(libs, "_out.apk"), "resources.arsc"));
                lr.put("resources_arsc_sha256", libArsc);
                lr.put("r_txt_sha256", Files2.sha256(new File(libs, "_R.txt")));
            }
            r.put("library_resources", lr);
            checks.add(check("P3.5", "all library resource folders compile and link with the framework table", compileFail == 0 && pl.exit == 0 && !names.isEmpty(),
                    Json.map("modules", (long) names.size(), "compile_failures", (long) compileFail, "link_exit", (long) pl.exit)));
            checks.add(check("P3.6", "library resources.arsc byte-identical to the desktop build with the same AAPT2 source",
                    libArsc != null && libArsc.equals(exp.get("libs_arsc_sha256")), Json.map("phone", libArsc, "desktop", exp.get("libs_arsc_sha256"))));
            r.put("status", "COMPLETED");
        } catch (Throwable t) {
            r.put("status", "ERROR");
            r.put("error", trace(t));
            log.line("P3: ERROR " + t);
        }
        return r;
    }

    private Proc dump(String aapt2, File apk, File to) throws IOException, InterruptedException {
        return Proc.runToFile(work, 600, to, aapt2, "dump", "resources", apk.getPath());
    }

    /** type/name -> 0xID for every resource whose dump line says PUBLIC. */
    private static Map<String, String> publicIds(File dump) throws IOException {
        Map<String, String> m = new TreeMap<>();
        for (String line : new String(Files2.read(dump), StandardCharsets.UTF_8).split("\n")) {
            String t = line.trim();
            if (!t.startsWith("resource 0x")) continue;
            String[] p = t.split("\\s+");
            if (p.length >= 4 && t.contains("PUBLIC")) m.put(p[2], p[1]);
        }
        return m;
    }

    // ------------------------------------------------------------------------------------------ all

    Map<String, Object> runAll(boolean p1, boolean p2, boolean p3) {
        Map<String, Object> rep = new LinkedHashMap<>();
        rep.put("report", "APK Builder 005 Stage 1 feasibility probe");
        rep.put("note", "Automated checks only. CHECK OK / CHECK FAILED are the probe's own comparisons; PASS or FAIL is the owner's decision after the physical test.");
        long t0 = System.nanoTime();
        rep.put("started_epoch_ms", System.currentTimeMillis());
        rep.put("environment", environment());
        try {
            log.line("Checking inputs ...");
            rep.put("inputs", checkInputs());
        } catch (Throwable t) {
            rep.put("inputs", Json.map("error", trace(t)));
        }
        Map<String, Object> tests = new LinkedHashMap<>();
        if (p1) tests.put("P1", p1());
        if (p2) tests.put("P2", p2());
        if (p3) tests.put("P3", p3());
        rep.put("tests", tests);
        rep.put("total_ms", ms(t0));
        return rep;
    }
}
