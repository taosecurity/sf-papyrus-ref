# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Richard Bejtlich
"""Replace the build details a compiled .pex carries (source path, user name, machine name) with neutral text.

  python -I tests/scrub_pex.py <file.pex>

The Papyrus compiler writes where and by whom a script was built into its header. Test fixtures in a public repo
should not carry that, so run this after compiling a fixture. It rewrites the file in place and changes nothing
else (and sets the compile time to zero).
"""
import struct
import sys


def scrub(data, source_name):
    if struct.unpack_from("<I", data, 0)[0] != 0xFA57C0DE:
        raise SystemExit("not a little-endian .pex file")
    p = 4 + 2 + 2
    head = bytearray(data[:p]) + struct.pack("<Q", 0)
    p += 8
    for _ in range(3):
        n = struct.unpack_from("<H", data, p)[0]
        p += 2 + n
    for s in (source_name, "user", "machine"):
        b = s.encode("utf-8")
        head += struct.pack("<H", len(b)) + b
    return bytes(head) + data[p:]


def main():
    path = sys.argv[1]
    with open(path, "rb") as f:
        data = f.read()
    name = path.replace("\\", "/").rsplit("/", 1)[-1][:-4] + ".psc"
    with open(path, "wb") as f:
        f.write(scrub(data, name))
    print(f"Scrubbed {path}")


if __name__ == "__main__":
    main()
