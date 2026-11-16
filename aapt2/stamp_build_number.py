#!/usr/bin/env python3
"""Write a build identifier into an unstripped AAPT2 executable, as Soong does after linking.

  stamp_build_number.py EXECUTABLE BUILD_ID

libbuildversion defines `char soong_build_number[128]` holding a placeholder; AAPT2's version line shows that
array's text when it differs from the placeholder (on Android it would otherwise show the phone's own
ro.build.version.incremental). The symbol is found in the ELF symbol table (so the binary must not be
stripped yet), its file offset computed from its section, and BUILD_ID (at most 127 bytes) written there.
"""
import struct, sys

PLACEHOLDER = b"SOONG BUILD NUMBER PLACEHOLDER"


def main(path, build_id):
    data = bytearray(open(path, "rb").read())
    if data[:4] != b"\x7fELF" or data[4] != 2 or data[5] != 1:
        raise SystemExit("not a 64-bit little-endian ELF file")
    shoff, = struct.unpack_from("<Q", data, 0x28)
    shentsize, shnum = struct.unpack_from("<HH", data, 0x3A)
    secs = []
    for i in range(shnum):
        name, typ, flags, addr, off, size, link, info, align, entsize = struct.unpack_from("<IIQQQQIIQQ", data, shoff + i * shentsize)
        secs.append(dict(type=typ, addr=addr, off=off, size=size, link=link, entsize=entsize))
    symtab = next((s for s in secs if s["type"] == 2), None)  # SHT_SYMTAB
    if symtab is None:
        raise SystemExit("no symbol table (stamp before stripping)")
    strtab = secs[symtab["link"]]
    found = None
    for k in range(symtab["size"] // 24):
        st_name, st_info, st_other, st_shndx, st_value, st_size = struct.unpack_from("<IBBHQQ", data, symtab["off"] + k * 24)
        end = data.index(b"\0", strtab["off"] + st_name)
        if bytes(data[strtab["off"] + st_name:end]) == b"soong_build_number":
            found = (st_shndx, st_value, st_size); break
    if found is None:
        raise SystemExit("symbol soong_build_number not found")
    shndx, value, size = found
    sec = secs[shndx]
    off = value - sec["addr"] + sec["off"]
    if bytes(data[off:off + len(PLACEHOLDER)]) != PLACEHOLDER:
        raise SystemExit("placeholder not found at the symbol's offset 0x%x" % off)
    raw = build_id.encode("ascii")
    if len(raw) >= size:
        raise SystemExit("build id longer than %d bytes" % (size - 1))
    data[off:off + size] = raw + b"\0" * (size - len(raw))
    open(path, "wb").write(bytes(data))
    print("stamped %s at file offset 0x%x (%d bytes): %s" % (path, off, size, build_id))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
