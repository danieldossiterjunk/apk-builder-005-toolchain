package org.apkbuilder.probe005;

import java.util.ArrayList;
import java.util.Iterator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/** Minimal JSON: writes Map/List/String/Number/Boolean/null with stable key order, and parses the same subset. */
final class Json {
    private Json() {}

    static Map<String, Object> map(Object... kv) {
        Map<String, Object> m = new LinkedHashMap<>();
        for (int i = 0; i + 1 < kv.length; i += 2) m.put((String) kv[i], kv[i + 1]);
        return m;
    }

    static String write(Object o) {
        StringBuilder sb = new StringBuilder();
        write(sb, o, 0);
        return sb.append('\n').toString();
    }

    @SuppressWarnings("unchecked")
    private static void write(StringBuilder sb, Object o, int ind) {
        if (o == null) { sb.append("null"); return; }
        if (o instanceof String) { quote(sb, (String) o); return; }
        if (o instanceof Boolean || o instanceof Integer || o instanceof Long) { sb.append(o); return; }
        if (o instanceof Number) {
            double d = ((Number) o).doubleValue();
            sb.append(Double.isNaN(d) || Double.isInfinite(d) ? "null" : String.valueOf(d));
            return;
        }
        if (o instanceof Map) {
            Map<String, Object> m = (Map<String, Object>) o;
            if (m.isEmpty()) { sb.append("{}"); return; }
            sb.append("{\n");
            Iterator<Map.Entry<String, Object>> it = m.entrySet().iterator();
            while (it.hasNext()) {
                Map.Entry<String, Object> e = it.next();
                pad(sb, ind + 1); quote(sb, e.getKey()); sb.append(": ");
                write(sb, e.getValue(), ind + 1);
                if (it.hasNext()) sb.append(',');
                sb.append('\n');
            }
            pad(sb, ind); sb.append('}');
            return;
        }
        if (o instanceof List) {
            List<Object> l = (List<Object>) o;
            if (l.isEmpty()) { sb.append("[]"); return; }
            boolean simple = true;
            for (Object x : l) if (x instanceof Map || x instanceof List) { simple = false; break; }
            if (simple && l.size() <= 8) {
                sb.append('[');
                for (int i = 0; i < l.size(); i++) { if (i > 0) sb.append(", "); write(sb, l.get(i), ind + 1); }
                sb.append(']');
                return;
            }
            sb.append("[\n");
            for (int i = 0; i < l.size(); i++) {
                pad(sb, ind + 1); write(sb, l.get(i), ind + 1);
                if (i + 1 < l.size()) sb.append(',');
                sb.append('\n');
            }
            pad(sb, ind); sb.append(']');
            return;
        }
        quote(sb, String.valueOf(o));
    }

    private static void pad(StringBuilder sb, int n) { for (int i = 0; i < n; i++) sb.append("  "); }

    private static void quote(StringBuilder sb, String s) {
        sb.append('"');
        for (int i = 0; i < s.length(); i++) {
            char c = s.charAt(i);
            switch (c) {
                case '"': sb.append("\\\""); break;
                case '\\': sb.append("\\\\"); break;
                case '\n': sb.append("\\n"); break;
                case '\r': sb.append("\\r"); break;
                case '\t': sb.append("\\t"); break;
                default:
                    if (c < 0x20) sb.append(String.format("\\u%04x", (int) c));
                    else sb.append(c);
            }
        }
        sb.append('"');
    }

    // ------------------------------------------------------------------------------------------ parser

    static Object parse(String s) {
        Json.Parser p = new Json.Parser(s);
        Object v = p.value();
        p.ws();
        if (p.i != s.length()) throw new IllegalArgumentException("trailing data at " + p.i);
        return v;
    }

    private static final class Parser {
        final String s; int i;
        Parser(String s) { this.s = s; }

        void ws() { while (i < s.length() && Character.isWhitespace(s.charAt(i))) i++; }

        Object value() {
            ws();
            if (i >= s.length()) throw new IllegalArgumentException("unexpected end");
            char c = s.charAt(i);
            if (c == '{') {
                i++; Map<String, Object> m = new LinkedHashMap<>(); ws();
                if (s.charAt(i) == '}') { i++; return m; }
                while (true) {
                    ws(); String k = str(); ws(); expect(':');
                    m.put(k, value()); ws();
                    if (s.charAt(i) == ',') { i++; continue; }
                    expect('}'); return m;
                }
            }
            if (c == '[') {
                i++; List<Object> l = new ArrayList<>(); ws();
                if (s.charAt(i) == ']') { i++; return l; }
                while (true) {
                    l.add(value()); ws();
                    if (s.charAt(i) == ',') { i++; continue; }
                    expect(']'); return l;
                }
            }
            if (c == '"') return str();
            if (s.startsWith("true", i)) { i += 4; return Boolean.TRUE; }
            if (s.startsWith("false", i)) { i += 5; return Boolean.FALSE; }
            if (s.startsWith("null", i)) { i += 4; return null; }
            int st = i;
            while (i < s.length() && "+-0123456789.eE".indexOf(s.charAt(i)) >= 0) i++;
            String n = s.substring(st, i);
            if (n.isEmpty()) throw new IllegalArgumentException("bad value at " + st);
            if (n.contains(".") || n.contains("e") || n.contains("E")) return Double.parseDouble(n);
            return Long.parseLong(n);
        }

        void expect(char c) {
            if (i >= s.length() || s.charAt(i) != c) throw new IllegalArgumentException("expected '" + c + "' at " + i);
            i++;
        }

        String str() {
            expect('"');
            StringBuilder sb = new StringBuilder();
            while (true) {
                char c = s.charAt(i++);
                if (c == '"') return sb.toString();
                if (c == '\\') {
                    char e = s.charAt(i++);
                    switch (e) {
                        case 'n': sb.append('\n'); break;
                        case 'r': sb.append('\r'); break;
                        case 't': sb.append('\t'); break;
                        case 'b': sb.append('\b'); break;
                        case 'f': sb.append('\f'); break;
                        case 'u': sb.append((char) Integer.parseInt(s.substring(i, i + 4), 16)); i += 4; break;
                        default: sb.append(e);
                    }
                } else sb.append(c);
            }
        }
    }
}
