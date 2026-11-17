package org.apkbuilder.probe005;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.zip.ZipEntry;
import java.util.zip.ZipFile;
import java.util.zip.ZipInputStream;

/** File, hash and ZIP helpers. */
final class Files2 {
    private Files2() {}

    static String sha256(File f) throws IOException {
        try (InputStream in = new FileInputStream(f)) { return sha256(in); }
    }

    static String sha256(InputStream in) throws IOException {
        try {
            MessageDigest md = MessageDigest.getInstance("SHA-256");
            byte[] buf = new byte[1 << 16];
            int n;
            while ((n = in.read(buf)) > 0) md.update(buf, 0, n);
            return hex(md.digest());
        } catch (java.security.NoSuchAlgorithmException e) {
            throw new IOException(e);
        }
    }

    static String sha256(byte[] b) {
        try { return hex(MessageDigest.getInstance("SHA-256").digest(b)); }
        catch (java.security.NoSuchAlgorithmException e) { throw new IllegalStateException(e); }
    }

    static String hex(byte[] b) {
        StringBuilder sb = new StringBuilder(b.length * 2);
        for (byte x : b) sb.append(String.format("%02x", x & 0xff));
        return sb.toString();
    }

    static byte[] read(File f) throws IOException {
        try (InputStream in = new FileInputStream(f)) { return readAll(in); }
    }

    static byte[] readAll(InputStream in) throws IOException {
        ByteArrayOutputStream bo = new ByteArrayOutputStream();
        copy(in, bo);
        return bo.toByteArray();
    }

    static void copy(InputStream in, OutputStream out) throws IOException {
        byte[] buf = new byte[1 << 16];
        int n;
        while ((n = in.read(buf)) > 0) out.write(buf, 0, n);
    }

    static void write(File f, byte[] b) throws IOException {
        mkdirs(f.getParentFile());
        try (OutputStream o = new FileOutputStream(f)) { o.write(b); }
    }

    static void mkdirs(File d) throws IOException {
        if (d != null && !d.isDirectory() && !d.mkdirs() && !d.isDirectory()) throw new IOException("cannot create " + d);
    }

    static void deleteTree(File f) {
        if (f == null || !f.exists()) return;
        File[] kids = f.isDirectory() ? f.listFiles() : null;
        if (kids != null) for (File k : kids) deleteTree(k);
        f.setWritable(true);
        f.delete();
    }

    /** Unpacks a ZIP into dir (fresh). Entry names must stay inside dir. Returns the number of files written. */
    static int unzip(File zip, File dir) throws IOException {
        deleteTree(dir);
        mkdirs(dir);
        String root = dir.getCanonicalPath() + File.separator;
        int n = 0;
        try (ZipInputStream zin = new ZipInputStream(new FileInputStream(zip))) {
            ZipEntry e;
            while ((e = zin.getNextEntry()) != null) {
                File t = new File(dir, e.getName());
                if (!t.getCanonicalPath().startsWith(root)) throw new IOException("entry outside target: " + e.getName());
                if (e.isDirectory()) { mkdirs(t); continue; }
                mkdirs(t.getParentFile());
                try (OutputStream o = new FileOutputStream(t)) { copy(zin, o); }
                n++;
            }
        }
        return n;
    }

    /** Bytes of one entry of a ZIP, or null if absent. */
    static byte[] entry(File zip, String name) throws IOException {
        try (ZipFile z = new ZipFile(zip)) {
            ZipEntry e = z.getEntry(name);
            if (e == null) return null;
            try (InputStream in = z.getInputStream(e)) { return readAll(in); }
        }
    }

    /** All regular files under dir, sorted by path. */
    static List<File> listFiles(File dir) {
        List<File> out = new ArrayList<>();
        walk(dir, out);
        Collections.sort(out);
        return out;
    }

    private static void walk(File d, List<File> out) {
        File[] kids = d.listFiles();
        if (kids == null) return;
        for (File k : kids) { if (k.isDirectory()) walk(k, out); else out.add(k); }
    }

    static String rel(File base, File f) {
        String b = base.getAbsolutePath() + File.separator;
        String p = f.getAbsolutePath();
        return p.startsWith(b) ? p.substring(b.length()) : p;
    }
}
