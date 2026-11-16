import static org.objectweb.asm.Opcodes.*;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.HashMap;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import org.objectweb.asm.AnnotationVisitor;
import org.objectweb.asm.ClassWriter;
import org.objectweb.asm.MethodVisitor;

/**
 * Generates compile-time API stub classes (no implementation) from an AOSP API signature file
 * ("// Signature format: 2.0", e.g. frameworks/base api/current.txt of Android 10).
 *
 * The output plays the role that android.jar plays for a compiler: it lets a Java compiler resolve
 * the public platform API. Every method body is {@code throw new RuntimeException("Stub!")}.
 * Nothing from the proprietary Android SDK is used; the only input is the Apache-2.0 signature text.
 *
 * Usage: java StubGen <current.txt> <output-class-dir>
 */
public final class StubGen {
    static final Set<String> MODS = new HashSet<>(Arrays.asList("public", "protected", "private", "static",
            "final", "abstract", "default", "synchronized", "native", "transient", "volatile", "strictfp"));
    static final Map<String, Character> PRIMS = new HashMap<>();
    static {
        PRIMS.put("void", 'V'); PRIMS.put("boolean", 'Z'); PRIMS.put("byte", 'B'); PRIMS.put("char", 'C');
        PRIMS.put("short", 'S'); PRIMS.put("int", 'I'); PRIMS.put("long", 'J'); PRIMS.put("float", 'F');
        PRIMS.put("double", 'D');
    }

    static final class TP { String name; final List<Ty> bounds = new ArrayList<>(); }

    static final class Ty {
        final String desc; final String sig; final Cls cls; final TP var;
        Ty(String desc, String sig, Cls cls, TP var) { this.desc = desc; this.sig = sig; this.cls = cls; this.var = var; }
        String desc() {
            if (var != null) return var.bounds.isEmpty() ? "Ljava/lang/Object;" : var.bounds.get(0).desc();
            return desc;
        }
        String internal() { String d = desc(); return d.substring(1, d.length() - 1); }
    }

    static final class Cls {
        String pkg, dotted, internal, kind, header;
        Cls outer; boolean isStatic; int lineNo;
        final List<String> members = new ArrayList<>();
        final List<Cls> inner = new ArrayList<>();
        // filled by header parse
        int access; boolean deprecated; List<TP> tparams = new ArrayList<>(); final Map<String, TP> scope = new HashMap<>();
        Ty superTy; final List<Ty> ifaces = new ArrayList<>(); final List<String[]> annos = new ArrayList<>();
        boolean headerGeneric; boolean parsed;
        boolean isInterfaceLike() { return kind.equals("interface") || kind.equals("@interface"); }
        String simple() { int i = dotted.lastIndexOf('.'); return i < 0 ? dotted : dotted.substring(i + 1); }
    }

    final Map<String, Cls> classes = new LinkedHashMap<>();
    int unresolved = 0; final Set<String> unresolvedNames = new HashSet<>();

    /** Cursor-based parser over one signature line. */
    final class P {
        final String s; int i; final List<Map<String, TP>> scopes = new ArrayList<>();
        boolean generic, varargs; final List<String[]> annos = new ArrayList<>();
        P(String s) { this.s = s; }
        char peek() { return i < s.length() ? s.charAt(i) : '\0'; }
        void ws() { while (i < s.length() && s.charAt(i) == ' ') i++; }
        boolean at(String t) { return s.startsWith(t, i); }
        boolean accept(char c) { ws(); if (peek() == c) { i++; return true; } return false; }
        void expect(char c) { if (!accept(c)) throw new IllegalStateException("expected '" + c + "' at " + i + " in: " + s); }
        String ident() {
            int st = i;
            while (i < s.length() && (Character.isJavaIdentifierPart(s.charAt(i)))) i++;
            if (st == i) throw new IllegalStateException("identifier expected at " + i + " in: " + s);
            return s.substring(st, i);
        }
        String word() { ws(); int st = i; while (i < s.length() && Character.isJavaIdentifierPart(s.charAt(i))) i++; return s.substring(st, i); }
        String peekWord() { int save = i; String w = word(); i = save; return w; }
        void skipBalanced(char open, char close) {
            int depth = 0;
            while (i < s.length()) {
                char c = s.charAt(i);
                if (c == '"' || c == '\'') { char q = c; i++; while (i < s.length() && s.charAt(i) != q) { if (s.charAt(i) == '\\') i++; i++; } i++; continue; }
                if (c == open) depth++; else if (c == close) { depth--; if (depth == 0) { i++; return; } }
                i++;
            }
            throw new IllegalStateException("unbalanced in: " + s);
        }
        void skipBalancedString() {
            i++;
            while (i < s.length() && s.charAt(i) != '"') { if (s.charAt(i) == '\\') i++; i++; }
            i++;
        }
        void skipAnnos() {
            for (;;) {
                ws();
                if (peek() != '@' || at("@interface")) return;
                i++; int st = i;
                while (i < s.length() && (Character.isJavaIdentifierPart(s.charAt(i)) || s.charAt(i) == '.')) i++;
                String name = s.substring(st, i); String args = "";
                if (peek() == '(') { int a = i; skipBalanced('(', ')'); args = s.substring(a + 1, i - 1); }
                annos.add(new String[] {name, args});
            }
        }
        int mods() {
            int acc = 0;
            for (;;) {
                skipAnnos();
                String w = peekWord();
                if (!MODS.contains(w)) return acc;
                word();
                switch (w) {
                    case "public": acc |= ACC_PUBLIC; break; case "protected": acc |= ACC_PROTECTED; break;
                    case "private": acc |= ACC_PRIVATE; break; case "static": acc |= ACC_STATIC; break;
                    case "final": acc |= ACC_FINAL; break; case "abstract": acc |= ACC_ABSTRACT; break;
                    case "synchronized": acc |= ACC_SYNCHRONIZED; break; case "native": acc |= ACC_NATIVE; break;
                    case "transient": acc |= ACC_TRANSIENT; break; case "volatile": acc |= ACC_VOLATILE; break;
                    case "strictfp": acc |= ACC_STRICT; break; case "default": acc |= 0x10000000; break;
                    default: break;
                }
            }
        }
        TP lookupVar(String n) { for (int k = scopes.size() - 1; k >= 0; k--) { TP t = scopes.get(k).get(n); if (t != null) return t; } return null; }

        List<TP> tparams() {
            List<TP> out = new ArrayList<>(); Map<String, TP> scope = new HashMap<>(); scopes.add(scope);
            ws(); if (peek() != '<') return out;
            int save = i; i++; int depth = 1; boolean expectName = true;
            while (depth > 0) {
                char c = s.charAt(i);
                if (c == '<') depth++; else if (c == '>') depth--; else if (c == ',' && depth == 1) expectName = true;
                else if (expectName && depth == 1 && Character.isJavaIdentifierStart(c)) {
                    TP tp = new TP(); tp.name = ident(); out.add(tp); scope.put(tp.name, tp); expectName = false; continue;
                }
                i++;
            }
            i = save + 1;
            for (TP tp : out) {
                ws(); ident(); ws();
                if (at("extends ")) { i += 8; do { tp.bounds.add(type()); } while (accept('&')); }
                accept(',');
            }
            expect('>'); generic = true;
            return out;
        }

        Ty type() {
            skipAnnos(); ws();
            if (peek() == '?') {
                i++; ws(); generic = true;
                if (at("extends ")) { i += 8; return new Ty(null, "+" + type().sig, null, null); }
                if (at("super ")) { i += 6; return new Ty(null, "-" + type().sig, null, null); }
                return new Ty(null, "*", null, null);
            }
            List<String> names = new ArrayList<>(); List<String> args = new ArrayList<>(); boolean anyArgs = false;
            for (;;) {
                names.add(ident()); String a = null;
                if (peek() == '<') {
                    i++; StringBuilder sb = new StringBuilder("<");
                    do { sb.append(type().sig); } while (accept(','));
                    expect('>'); sb.append('>'); a = sb.toString(); anyArgs = true;
                }
                args.add(a);
                if (peek() == '.' && !at("...")) { i++; continue; }
                break;
            }
            Ty base;
            if (names.size() == 1 && !anyArgs && PRIMS.containsKey(names.get(0))) {
                String d = String.valueOf(PRIMS.get(names.get(0))); base = new Ty(d, d, null, null);
            } else if (names.size() == 1 && !anyArgs && lookupVar(names.get(0)) != null) {
                TP tp = lookupVar(names.get(0)); generic = true; base = new Ty(null, "T" + tp.name + ";", null, tp);
            } else {
                String dotted = String.join(".", names);
                Cls c = classes.get(dotted);
                if (c == null && Character.isUpperCase(names.get(0).charAt(0))) { c = classes.get("java.lang." + dotted); if (c != null) { names.add(0, "lang"); names.add(0, "java"); args.add(0, null); args.add(0, null); } }
                int pkgSegs;
                if (c != null) pkgSegs = names.size() - (c.dotted.split("\\.").length);
                else { pkgSegs = 0; while (pkgSegs < names.size() - 1 && Character.isLowerCase(names.get(pkgSegs).charAt(0))) pkgSegs++; unresolved++; unresolvedNames.add(dotted + "  <- " + s); }
                StringBuilder in = new StringBuilder();
                for (int k = 0; k < pkgSegs; k++) in.append(names.get(k)).append('/');
                String[] prefix = new String[names.size()];
                for (int k = pkgSegs; k < names.size(); k++) { if (k > pkgSegs) in.append('$'); in.append(names.get(k)); prefix[k] = in.toString(); }
                String internal = in.toString(); String sig;
                if (!anyArgs) sig = "L" + internal + ";";
                else {
                    generic = true; int f = pkgSegs; while (args.get(f) == null) f++;
                    StringBuilder sb = new StringBuilder("L").append(prefix[f]).append(args.get(f));
                    for (int k = f + 1; k < names.size(); k++) { sb.append('.').append(names.get(k)); if (args.get(k) != null) sb.append(args.get(k)); }
                    sig = sb.append(';').toString();
                }
                base = new Ty("L" + internal + ";", sig, c, null);
            }
            for (;;) {
                if (at("[]")) { i += 2; base = arr(base); }
                else if (at("...")) { i += 3; base = arr(base); varargs = true; }
                else break;
            }
            return base;
        }
        Ty arr(Ty e) { return new Ty("[" + e.desc(), "[" + e.sig, null, null); }
    }

    static String tpSig(List<TP> tps) {
        if (tps.isEmpty()) return "";
        StringBuilder sb = new StringBuilder("<");
        for (TP tp : tps) {
            sb.append(tp.name).append(':');
            if (tp.bounds.isEmpty()) { sb.append("Ljava/lang/Object;"); continue; }
            Ty first = tp.bounds.get(0);
            if (first.cls != null && first.cls.isInterfaceLike()) sb.append(':');
            sb.append(first.sig);
            for (int k = 1; k < tp.bounds.size(); k++) sb.append(':').append(tp.bounds.get(k).sig);
        }
        return sb.append('>').toString();
    }

    void parseHeader(Cls c) {
        if (c.parsed) return;
        c.parsed = true;
        if (c.outer != null) { parseHeader(c.outer); }
        P p = new P(c.header);
        if (c.outer != null && !c.isStatic) p.scopes.add(c.outer.scope);
        int acc = p.mods();
        p.ws(); if (p.at("@interface")) p.i += 10; else p.word();
        p.ws(); while (p.i < p.s.length() && (Character.isJavaIdentifierPart(p.peek()) || p.peek() == '.')) p.i++;
        c.tparams = p.tparams();
        if (c.outer != null && !c.isStatic) c.scope.putAll(c.outer.scope);
        for (TP tp : c.tparams) c.scope.put(tp.name, tp);
        p.ws();
        if (p.at("extends ")) {
            p.i += 8;
            if (c.kind.equals("interface")) { do { c.ifaces.add(p.type()); p.ws(); } while (p.i < p.s.length() && !p.at("implements ")); }
            else c.superTy = p.type();
        }
        p.ws();
        if (p.at("implements ")) { p.i += 11; do { c.ifaces.add(p.type()); p.ws(); } while (p.i < p.s.length()); }
        c.access = acc; c.annos.addAll(p.annos); c.headerGeneric = p.generic;
        for (String[] a : p.annos) if (a[0].equals("Deprecated") || a[0].equals("java.lang.Deprecated")) c.deprecated = true;
    }

    static Object constant(String desc, String v) {
        v = v.trim();
        switch (desc) {
            case "Z": return v.equals("true") ? 1 : 0;
            case "B": case "S": case "I": return (int) Long.parseLong(v);
            case "C": if (v.startsWith("'")) return (int) unescape(v.substring(1, v.length() - 1)).charAt(0); return (int) Long.parseLong(v);
            case "J": return Long.parseLong(v.endsWith("L") ? v.substring(0, v.length() - 1) : v);
            case "F": {
                String x = v.replace(" ", "");
                if (x.equals("(0.0f/0.0f)")) return Float.NaN; if (x.equals("(1.0f/0.0f)")) return Float.POSITIVE_INFINITY;
                if (x.equals("(-1.0f/0.0f)")) return Float.NEGATIVE_INFINITY; return Float.parseFloat(x);
            }
            case "D": {
                String x = v.replace(" ", "");
                if (x.equals("(0.0/0.0)")) return Double.NaN; if (x.equals("(1.0/0.0)")) return Double.POSITIVE_INFINITY;
                if (x.equals("(-1.0/0.0)")) return Double.NEGATIVE_INFINITY; return Double.parseDouble(x);
            }
            default: return null;
        }
    }

    static String unescape(String s) {
        StringBuilder sb = new StringBuilder();
        for (int i = 0; i < s.length(); i++) {
            char c = s.charAt(i);
            if (c != '\\') { sb.append(c); continue; }
            char n = s.charAt(++i);
            switch (n) {
                case 'n': sb.append('\n'); break; case 't': sb.append('\t'); break; case 'r': sb.append('\r'); break;
                case 'b': sb.append('\b'); break; case 'f': sb.append('\f'); break; case '0': sb.append('\0'); break;
                case 'u': sb.append((char) Integer.parseInt(s.substring(i + 1, i + 5), 16)); i += 4; break;
                default: sb.append(n);
            }
        }
        return sb.toString();
    }

    byte[] generate(Cls c) {
        parseHeader(c);
        boolean iface = c.isInterfaceLike(); boolean isEnum = c.kind.equals("enum"); boolean anno = c.kind.equals("@interface");
        int acc = (c.access & (ACC_FINAL | ACC_ABSTRACT)) | ACC_PUBLIC;
        if (iface) acc |= ACC_INTERFACE | ACC_ABSTRACT; else acc |= ACC_SUPER;
        if (anno) acc |= ACC_ANNOTATION;
        if (isEnum) acc |= ACC_ENUM | ACC_FINAL;
        if (c.deprecated) acc |= ACC_DEPRECATED;
        String superName; String superSig;
        if (c.internal.equals("java/lang/Object")) { superName = null; superSig = ""; }
        else if (isEnum) { superName = "java/lang/Enum"; superSig = "Ljava/lang/Enum<L" + c.internal + ";>;"; }
        else if (c.superTy != null) { superName = c.superTy.internal(); superSig = c.superTy.sig; }
        else { superName = "java/lang/Object"; superSig = "Ljava/lang/Object;"; }
        List<String> ifs = new ArrayList<>(); StringBuilder csig = new StringBuilder(tpSig(c.tparams)).append(superSig);
        if (anno) { ifs.add("java/lang/annotation/Annotation"); csig.append("Ljava/lang/annotation/Annotation;"); }
        for (Ty t : c.ifaces) { ifs.add(t.internal()); csig.append(t.sig); }
        boolean needSig = c.headerGeneric || isEnum;
        ClassWriter cw = new ClassWriter(ClassWriter.COMPUTE_MAXS);
        cw.visit(V1_8, acc, c.internal, needSig && superName != null ? csig.toString() : null, superName, ifs.toArray(new String[0]));
        for (String[] a : c.annos) {
            String n = a[0].startsWith("java.lang.annotation.") ? a[0].substring(21) : a[0];
            if (n.equals("Retention")) {
                AnnotationVisitor av = cw.visitAnnotation("Ljava/lang/annotation/Retention;", true);
                av.visitEnum("value", "Ljava/lang/annotation/RetentionPolicy;", a[1].substring(a[1].lastIndexOf('.') + 1).trim()); av.visitEnd();
            } else if (n.equals("Target")) {
                AnnotationVisitor av = cw.visitAnnotation("Ljava/lang/annotation/Target;", true);
                AnnotationVisitor arr = av.visitArray("value");
                for (String e : a[1].replace("{", "").replace("}", "").split(",")) { e = e.trim(); if (!e.isEmpty()) arr.visitEnum(null, "Ljava/lang/annotation/ElementType;", e.substring(e.lastIndexOf('.') + 1)); }
                arr.visitEnd(); av.visitEnd();
            }
        }
        for (Cls x = c; x.outer != null; x = x.outer) cw.visitInnerClass(x.internal, x.outer.internal, x.simple(), innerFlags(x));
        for (Cls in : c.inner) { parseHeader(in); cw.visitInnerClass(in.internal, c.internal, in.simple(), innerFlags(in)); }

        boolean hasValues = false, hasValueOf = false;
        for (String line : c.members) {
            P p = new P(line); p.scopes.add(c.scope);
            String kindWord = p.word();
            if (kindWord.equals("property")) continue;
            int m = p.mods(); boolean dep = false;
            for (String[] a : p.annos) if (a[0].equals("Deprecated") || a[0].equals("java.lang.Deprecated")) dep = true;
            int flags = (m & 0xFFFF) | (dep ? ACC_DEPRECATED : 0);
            if (kindWord.equals("field") || kindWord.equals("enum_constant")) {
                Ty t = p.type(); p.ws(); String name = p.ident(); p.ws(); Object cv = null;
                if (p.peek() == '=') {
                    p.i++; p.ws();
                    if (p.peek() == '"') { int st = p.i; p.skipBalancedString(); cv = unescape(line.substring(st + 1, p.i - 1)); }
                    else { int st = p.i; while (p.peek() != ';') p.i++; cv = constant(t.desc(), line.substring(st, p.i)); }
                }
                if (kindWord.equals("enum_constant")) flags |= ACC_ENUM | ACC_PUBLIC | ACC_STATIC | ACC_FINAL;
                if (iface) flags |= ACC_PUBLIC | ACC_STATIC | ACC_FINAL;
                if ((flags & (ACC_STATIC | ACC_FINAL)) != (ACC_STATIC | ACC_FINAL)) cv = null;
                cw.visitField(flags, name, t.desc(), p.generic ? t.sig : null, cv).visitEnd();
                continue;
            }
            boolean ctor = kindWord.equals("ctor");
            List<TP> mtp = p.tparams();
            Ty ret = null; String name;
            if (ctor) { p.ws(); while (Character.isJavaIdentifierPart(p.peek()) || p.peek() == '.') p.i++; name = "<init>"; }
            else { ret = p.type(); p.ws(); name = p.ident(); }
            p.expect('(');
            StringBuilder desc = new StringBuilder("("), sig = new StringBuilder(tpSig(mtp)).append('(');
            if (ctor && c.outer != null && !c.isStatic) desc.append('L').append(c.outer.internal).append(';');
            p.ws();
            if (p.peek() != ')') { do { Ty t = p.type(); desc.append(t.desc()); sig.append(t.sig); } while (p.accept(',')); }
            p.expect(')');
            desc.append(')').append(ctor ? "V" : ret.desc()); sig.append(')').append(ctor ? "V" : ret.sig);
            List<String> exc = new ArrayList<>(); boolean excVar = false; StringBuilder excSig = new StringBuilder();
            p.ws();
            if (p.at("throws ")) { p.i += 7; do { Ty t = p.type(); exc.add(t.internal()); excSig.append('^').append(t.sig); if (t.var != null) excVar = true; } while (p.accept(',')); }
            if (excVar) sig.append(excSig);
            boolean isDefault = (m & 0x10000000) != 0;
            if (p.varargs) flags |= ACC_VARARGS;
            if (iface && !ctor) { flags |= ACC_PUBLIC; if (!isDefault && (flags & ACC_STATIC) == 0) flags |= ACC_ABSTRACT; }
            if (name.equals("values") && desc.toString().startsWith("()")) hasValues = true;
            if (name.equals("valueOf") && desc.toString().startsWith("(Ljava/lang/String;)")) hasValueOf = true;
            MethodVisitor mv = cw.visitMethod(flags, name, desc.toString(), p.generic ? sig.toString() : null, exc.isEmpty() ? null : exc.toArray(new String[0]));
            stubBody(mv, flags);
        }
        if (isEnum) {
            if (!hasValues) stubBody(cw.visitMethod(ACC_PUBLIC | ACC_STATIC, "values", "()[L" + c.internal + ";", null, null), 0);
            if (!hasValueOf) stubBody(cw.visitMethod(ACC_PUBLIC | ACC_STATIC, "valueOf", "(Ljava/lang/String;)L" + c.internal + ";", null, null), 0);
        }
        cw.visitEnd();
        return cw.toByteArray();
    }

    static void stubBody(MethodVisitor mv, int flags) {
        if ((flags & (ACC_ABSTRACT | ACC_NATIVE)) == 0) {
            mv.visitCode();
            mv.visitTypeInsn(NEW, "java/lang/RuntimeException"); mv.visitInsn(DUP); mv.visitLdcInsn("Stub!");
            mv.visitMethodInsn(INVOKESPECIAL, "java/lang/RuntimeException", "<init>", "(Ljava/lang/String;)V", false);
            mv.visitInsn(ATHROW); mv.visitMaxs(0, 0);
        }
        mv.visitEnd();
    }

    static int innerFlags(Cls x) {
        int f = x.access & (ACC_PUBLIC | ACC_PROTECTED | ACC_PRIVATE | ACC_FINAL | ACC_ABSTRACT);
        if (x.isStatic) f |= ACC_STATIC;
        if (x.isInterfaceLike()) f |= ACC_INTERFACE | ACC_ABSTRACT | ACC_STATIC;
        if (x.kind.equals("@interface")) f |= ACC_ANNOTATION;
        if (x.kind.equals("enum")) f |= ACC_ENUM | ACC_STATIC | ACC_FINAL;
        return f;
    }

    void run(Path in, Path out) throws IOException {
        List<String> lines = Files.readAllLines(in, StandardCharsets.UTF_8);
        if (!lines.get(0).startsWith("// Signature format: 2.0")) throw new IOException("unsupported signature format: " + lines.get(0));
        String pkg = null; Cls cur = null; int n = 0;
        for (String line : lines) {
            n++;
            if (line.startsWith("package ")) { pkg = line.substring(8, line.indexOf(' ', 8)); continue; }
            if (line.startsWith("    ") && cur != null) { cur.members.add(line.trim()); continue; }
            if (line.startsWith("  }")) { cur = null; continue; }
            if (line.startsWith("  ") && line.endsWith("{")) {
                Cls c = new Cls(); c.pkg = pkg; c.lineNo = n; c.header = line.substring(2, line.length() - 1).trim();
                P p = new P(c.header); int acc = p.mods(); p.ws();
                if (p.at("@interface")) { p.i += 10; c.kind = "@interface"; } else c.kind = p.word();
                if (!Arrays.asList("class", "interface", "enum", "@interface").contains(c.kind)) throw new IOException("line " + n + ": unknown kind in " + line);
                p.ws(); int st = p.i; while (p.i < p.s.length() && (Character.isJavaIdentifierPart(p.peek()) || p.peek() == '.')) p.i++;
                c.dotted = c.header.substring(st, p.i);
                c.internal = pkg.replace('.', '/') + "/" + c.dotted.replace('.', '$');
                c.isStatic = (acc & ACC_STATIC) != 0 || !c.kind.equals("class");
                classes.put(pkg + "." + c.dotted, c); cur = c;
            }
        }
        for (Cls c : classes.values()) {
            int d = c.dotted.lastIndexOf('.');
            if (d > 0) { c.outer = classes.get(c.pkg + "." + c.dotted.substring(0, d)); if (c.outer == null) throw new IOException("missing outer for " + c.dotted); c.outer.inner.add(c); }
        }
        int count = 0;
        for (Cls c : classes.values()) {
            byte[] b;
            try { b = generate(c); } catch (RuntimeException e) { throw new IOException("class " + c.pkg + "." + c.dotted + " (line " + c.lineNo + "): " + e, e); }
            Path f = out.resolve(c.internal + ".class"); Files.createDirectories(f.getParent()); Files.write(f, b); count++;
        }
        System.out.println("classes generated: " + count);
        System.out.println("unresolved type references (heuristic naming used): " + unresolved + " distinct=" + unresolvedNames.size());
        List<String> u = new ArrayList<>(unresolvedNames); java.util.Collections.sort(u);
        for (String s : u) System.out.println("  unresolved: " + s);
    }

    public static void main(String[] a) throws IOException { new StubGen().run(Paths.get(a[0]), Paths.get(a[1])); }
}
