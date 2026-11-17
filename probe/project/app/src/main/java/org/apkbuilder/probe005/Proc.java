package org.apkbuilder.probe005;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.concurrent.TimeUnit;

/** Runs one native program (AAPT2) with a time limit and collects its output. */
final class Proc {
    final List<String> cmd;
    int exit = -1;
    boolean timedOut;
    long ms;
    String output = "";

    private Proc(List<String> cmd) { this.cmd = cmd; }

    static Proc run(File cwd, long timeoutSec, String... args) throws IOException, InterruptedException {
        Proc p = new Proc(new ArrayList<>(Arrays.asList(args)));
        ProcessBuilder pb = new ProcessBuilder(p.cmd).directory(cwd).redirectErrorStream(true);
        long t0 = System.nanoTime();
        final Process pr = pb.start();
        final ByteArrayOutputStream buf = new ByteArrayOutputStream();
        Thread reader = new Thread(new Runnable() {
            @Override public void run() {
                try (InputStream in = pr.getInputStream()) {
                    byte[] b = new byte[8192];
                    int n;
                    while ((n = in.read(b)) > 0) synchronized (buf) { if (buf.size() < (4 << 20)) buf.write(b, 0, n); }
                } catch (IOException ignored) {
                    // process ended
                }
            }
        }, "proc-output");
        reader.start();
        if (!pr.waitFor(timeoutSec, TimeUnit.SECONDS)) {
            p.timedOut = true;
            pr.destroyForcibly();
            pr.waitFor(10, TimeUnit.SECONDS);
        }
        reader.join(5000);
        p.ms = (System.nanoTime() - t0) / 1_000_000;
        p.exit = p.timedOut ? -1 : pr.exitValue();
        synchronized (buf) { p.output = new String(buf.toByteArray(), StandardCharsets.UTF_8); }
        return p;
    }

    /**
     * Like run(), but standard output goes straight to a file (for large outputs such as a framework table dump);
     * the output field then holds the file size and whatever the program wrote to standard error.
     */
    static Proc runToFile(File cwd, long timeoutSec, File stdout, String... args) throws IOException, InterruptedException {
        Proc p = new Proc(new ArrayList<>(Arrays.asList(args)));
        File err = new File(stdout.getPath() + ".stderr");
        ProcessBuilder pb = new ProcessBuilder(p.cmd).directory(cwd);
        pb.redirectOutput(stdout);
        pb.redirectError(err);
        long t0 = System.nanoTime();
        Process pr = pb.start();
        if (!pr.waitFor(timeoutSec, TimeUnit.SECONDS)) {
            p.timedOut = true;
            pr.destroyForcibly();
            pr.waitFor(10, TimeUnit.SECONDS);
        }
        p.ms = (System.nanoTime() - t0) / 1_000_000;
        p.exit = p.timedOut ? -1 : pr.exitValue();
        String e = err.isFile() ? new String(Files2.read(err), StandardCharsets.UTF_8).trim() : "";
        err.delete();
        p.output = "standard output: " + stdout.length() + " bytes written to a file" + (e.isEmpty() ? "" : "\nstandard error:\n" + e);
        return p;
    }

    /** Output trimmed for the report (first and last lines kept). */
    String brief(int maxLines) {
        String[] l = output.split("\n");
        if (l.length <= maxLines) return output.trim();
        StringBuilder sb = new StringBuilder();
        for (int i = 0; i < maxLines / 2; i++) sb.append(l[i]).append('\n');
        sb.append("[... ").append(l.length - maxLines).append(" lines ...]\n");
        for (int i = l.length - maxLines / 2; i < l.length; i++) sb.append(l[i]).append('\n');
        return sb.toString().trim();
    }
}
