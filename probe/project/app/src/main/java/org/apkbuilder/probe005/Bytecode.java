package org.apkbuilder.probe005;

import java.io.IOException;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;

/** Reads method lists from Java class files and class names from DEX files (just enough for the probe's checks). */
final class Bytecode {
    private Bytecode() {}

    /** "name descriptor" of every method of a class file, plus "major=<n>" as the first element. */
    static List<String> classMethods(byte[] b) throws IOException {
        ByteBuffer bb = ByteBuffer.wrap(b).order(ByteOrder.BIG_ENDIAN);
        if (bb.getInt(0) != 0xCAFEBABE) throw new IOException("not a class file");
        int major = bb.getShort(6) & 0xffff;
        int n = bb.getShort(8) & 0xffff;
        String[] utf = new String[n];
        int p = 10;
        for (int i = 1; i < n; i++) {
            int t = b[p] & 0xff;
            switch (t) {
                case 1: {
                    int l = bb.getShort(p + 1) & 0xffff;
                    utf[i] = new String(b, p + 3, l, StandardCharsets.UTF_8);
                    p += 3 + l;
                    break;
                }
                case 3: case 4: p += 5; break;
                case 5: case 6: p += 9; i++; break;
                case 7: case 8: case 16: case 19: case 20: p += 3; break;
                case 9: case 10: case 11: case 12: case 17: case 18: p += 5; break;
                case 15: p += 4; break;
                default: throw new IOException("constant pool tag " + t);
            }
        }
        p += 6;
        int ni = bb.getShort(p) & 0xffff;
        p += 2 + 2 * ni;
        List<String> out = new ArrayList<>();
        out.add("major=" + major);
        for (int kind = 0; kind < 2; kind++) {
            int cnt = bb.getShort(p) & 0xffff;
            p += 2;
            for (int k = 0; k < cnt; k++) {
                int name = bb.getShort(p + 2) & 0xffff, desc = bb.getShort(p + 4) & 0xffff, ac = bb.getShort(p + 6) & 0xffff;
                p += 8;
                if (kind == 1) out.add(utf[name] + " " + utf[desc]);
                for (int a = 0; a < ac; a++) p += 6 + bb.getInt(p + 2);
            }
        }
        return out;
    }

    /** Binary names (a.b.C$D) of all classes defined in a DEX file. */
    static List<String> dexClasses(byte[] d) throws IOException {
        ByteBuffer bb = ByteBuffer.wrap(d).order(ByteOrder.LITTLE_ENDIAN);
        if (d.length < 0x70 || d[0] != 'd' || d[1] != 'e' || d[2] != 'x') throw new IOException("not a DEX file");
        int stringIdsOff = bb.getInt(0x3C), typeIdsOff = bb.getInt(0x44);
        int classDefsSize = bb.getInt(0x60), classDefsOff = bb.getInt(0x64);
        List<String> out = new ArrayList<>(classDefsSize);
        for (int i = 0; i < classDefsSize; i++) {
            int typeIdx = bb.getInt(classDefsOff + i * 32);
            int strIdx = bb.getInt(typeIdsOff + typeIdx * 4);
            int off = bb.getInt(stringIdsOff + strIdx * 4);
            // uleb128 length, then MUTF-8 bytes (class descriptors are ASCII in practice)
            int p = off;
            while ((d[p] & 0x80) != 0) p++;
            p++;
            int e = p;
            while (d[e] != 0) e++;
            String desc = new String(d, p, e - p, StandardCharsets.UTF_8);
            if (desc.startsWith("L") && desc.endsWith(";")) out.add(desc.substring(1, desc.length() - 1).replace('/', '.'));
        }
        return out;
    }
}
