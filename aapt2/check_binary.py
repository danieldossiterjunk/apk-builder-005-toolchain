#!/usr/bin/env python3
"""Check a built AAPT2 executable and summarise its link map.

  check_binary.py EXECUTABLE [LINK_MAP]

Prints JSON: ELF class/machine, whether it is fully static (no PT_INTERP, no PT_DYNAMIC NEEDED entries),
the alignment of every PT_LOAD segment (16 KiB page support needs >= 0x4000), its size and SHA-256, and,
from the lld link map, how many object files each static archive contributed. Archives whose licences need
attention (SELinux, libsepol, PCRE, OpenSSL/BoringSSL) are listed under "flagged_archives".
"""
import hashlib, json, os, re, struct, sys

path = sys.argv[1]
data = open(path, "rb").read()
rep = {"file": os.path.basename(path), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
assert data[:4] == b"\x7fELF", "not ELF"
rep["class"] = {1: "ELF32", 2: "ELF64"}[data[4]]
e_machine, = struct.unpack_from("<H", data, 18)
rep["machine"] = {183: "AArch64", 62: "x86-64"}.get(e_machine, e_machine)
phoff, = struct.unpack_from("<Q", data, 0x20)
phentsize, phnum = struct.unpack_from("<HH", data, 0x36)
loads = []; interp = False; dynamic = None
for i in range(phnum):
    p_type, p_flags, p_offset, p_vaddr, p_paddr, p_filesz, p_memsz, p_align = struct.unpack_from("<IIQQQQQQ", data, phoff + i * phentsize)
    if p_type == 1: loads.append(p_align)
    elif p_type == 3: interp = True
    elif p_type == 2: dynamic = (p_offset, p_filesz)
needed = 0
if dynamic:
    off, size = dynamic
    for k in range(size // 16):
        tag, val = struct.unpack_from("<qQ", data, off + k * 16)
        if tag == 1: needed += 1
        if tag == 0: break
rep["pt_interp"] = interp; rep["dt_needed_count"] = needed
rep["static"] = (not interp) and needed == 0
rep["load_alignments"] = ["0x%x" % a for a in loads]
rep["supports_16k_pages"] = all(a >= 0x4000 for a in loads)
if len(sys.argv) > 2 and os.path.exists(sys.argv[2]):
    counts = {}
    for line in open(sys.argv[2], encoding="utf-8", errors="replace"):
        m = re.search(r"([^\s/()]+\.a)\(([^)]+)\)", line)
        if m: counts.setdefault(m.group(1), set()).add(m.group(2))
    rep["archives"] = {k: len(v) for k, v in sorted(counts.items())}
    rep["flagged_archives"] = sorted(k for k in counts if re.search(r"selinux|sepol|pcre|crypto|ssl", k))
print(json.dumps(rep, indent=1))
