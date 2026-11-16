#!/usr/bin/env python3
"""Minimal Android.bp reader: prints the srcs of a module for given targets.
usage: bpsrcs.py ANDROID_BP MODULE [target ...]   (targets: android host linux linux_glibc linux_bionic not_windows)"""
import re, sys, json

TOK = re.compile(r'(//[^\n]*|/\*.*?\*/|\s+)|("(?:\\.|[^"\\])*"|`[^`]*`|[A-Za-z_][A-Za-z0-9_.]*|-?\d+|\+=|[{}\[\]():,=+])', re.S)

def tokenize(s):
    out = []; pos = 0
    while pos < len(s):
        m = TOK.match(s, pos)
        if not m: raise ValueError("cannot tokenize at %r" % s[pos:pos + 40])
        if m.group(2): out.append(m.group(2))
        pos = m.end()
    return out

class P:
    def __init__(self, toks): self.t = toks; self.i = 0; self.vars = {}; self.mods = []
    def peek(self): return self.t[self.i] if self.i < len(self.t) else None
    def nx(self): v = self.t[self.i]; self.i += 1; return v
    def value(self):
        v = self.atom()
        while self.peek() == "+":
            self.nx(); w = self.atom()
            if isinstance(v, list) and isinstance(w, list): v = v + w
            elif isinstance(v, str) and isinstance(w, str): v = v + w
            elif isinstance(v, dict) and isinstance(w, dict): v = {**v, **w}
            else: v = None
        return v
    def atom(self):
        t = self.nx()
        if t.startswith('"'): return json.loads(t)
        if t == "[":
            out = []
            while self.peek() != "]":
                out.append(self.value())
                if self.peek() == ",": self.nx()
            self.nx(); return out
        if t == "{": return self.body("}")
        if t in ("true", "false"): return t == "true"
        if re.fullmatch(r"-?\d+", t): return int(t)
        if t == "select" and self.peek() == "(":
            depth = 0
            while True:
                x = self.nx()
                if x == "(": depth += 1
                elif x == ")":
                    depth -= 1
                    if depth == 0: break
            return None
        return self.vars.get(t)
    def body(self, end):
        d = {}
        while self.peek() != end:
            k = self.nx()
            if k.startswith('"'): k = json.loads(k)
            sep = self.nx()
            if sep not in (":", "="): raise ValueError("bad token %r after %r" % (sep, k))
            d[k] = self.value()
            if self.peek() == ",": self.nx()
        self.nx(); return d
    def run(self):
        while self.peek() is not None:
            name = self.nx(); op = self.nx()
            if op == "=": self.vars[name] = self.value()
            elif op == "+=": self.vars[name] = (self.vars.get(name) or []) + (self.value() or [])
            elif op == "{": self.mods.append((name, self.body("}")))
            else: raise ValueError("unexpected %r %r" % (name, op))
        return self

def modules(path):
    return P(tokenize(open(path, encoding="utf-8").read())).run()

def srcs(mod, targets, key="srcs"):
    out = list(mod.get(key) or [])
    t = mod.get("target") or {}
    for name in targets:
        out += list((t.get(name) or {}).get(key) or [])
    excl = set(mod.get("exclude_srcs") or [])
    for name in targets: excl |= set((t.get(name) or {}).get("exclude_srcs") or [])
    return [x for x in out if x not in excl]

if __name__ == "__main__":
    p = modules(sys.argv[1])
    for kind, m in p.mods:
        if m.get("name") == sys.argv[2]:
            d = {"kind": kind, "srcs": srcs(m, sys.argv[3:]), "defaults": m.get("defaults"),
                 "static_libs": m.get("static_libs"), "whole_static_libs": m.get("whole_static_libs"),
                 "export_include_dirs": m.get("export_include_dirs"), "local_include_dirs": m.get("local_include_dirs"),
                 "cflags": m.get("cflags"), "target_keys": sorted((m.get("target") or {}).keys())}
            print(json.dumps(d, indent=1))


def find(mods, name):
    for kind, m in mods:
        if m.get("name") == name: return kind, m
    return None, None


def resolved(mods_by_file, name, targets, key="srcs", seen=None):
    """srcs (or another list property) of module `name` including its defaults chain, for the given targets.
    mods_by_file: list of parsed module lists to search (defaults may live in other files)."""
    seen = seen or set()
    if name in seen: return []
    seen.add(name)
    mod = None
    for mods in mods_by_file:
        k, mod = find(mods, name)
        if mod is not None: break
    if mod is None: raise KeyError(name)
    out = []
    for d in mod.get("defaults") or []:
        try: out += resolved(mods_by_file, d, targets, key, seen)
        except KeyError: pass
    out += srcs(mod, targets, key)
    return out
