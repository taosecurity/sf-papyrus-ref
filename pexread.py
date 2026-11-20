# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Richard Bejtlich
"""Read a compiled Papyrus script (.pex, Fallout 4 3.9 or Starfield 3.12) into plain Python data.

Adapted from pex_compare.py in sf-pex-tools (same author, MIT), which describes the format in full. This copy
keeps only what sf-papyrus-ref's `check` needs: each object's name and parent, its variable and property types,
and each function's parameters, locals, instructions and source line numbers.
Standard library only. It reads bytes; it never writes anything.
"""
import struct

OPCODES = {
    0x00: ("nop", 0, False), 0x01: ("iadd", 3, False), 0x02: ("fadd", 3, False), 0x03: ("isub", 3, False),
    0x04: ("fsub", 3, False), 0x05: ("imul", 3, False), 0x06: ("fmul", 3, False), 0x07: ("idiv", 3, False),
    0x08: ("fdiv", 3, False), 0x09: ("imod", 3, False), 0x0A: ("not", 2, False), 0x0B: ("ineg", 2, False),
    0x0C: ("fneg", 2, False), 0x0D: ("assign", 2, False), 0x0E: ("cast", 2, False), 0x0F: ("cmp_eq", 3, False),
    0x10: ("cmp_lt", 3, False), 0x11: ("cmp_le", 3, False), 0x12: ("cmp_gt", 3, False), 0x13: ("cmp_ge", 3, False),
    0x14: ("jmp", 1, False), 0x15: ("jmpt", 2, False), 0x16: ("jmpf", 2, False), 0x17: ("callmethod", 3, True),
    0x18: ("callparent", 2, True), 0x19: ("callstatic", 3, True), 0x1A: ("return", 1, False),
    0x1B: ("strcat", 3, False), 0x1C: ("propget", 3, False), 0x1D: ("propset", 3, False),
    0x1E: ("array_create", 2, False), 0x1F: ("array_length", 2, False), 0x20: ("array_getelement", 3, False),
    0x21: ("array_setelement", 3, False), 0x22: ("array_findelement", 4, False),
    0x23: ("array_rfindelement", 4, False), 0x24: ("is", 3, False), 0x25: ("struct_create", 1, False),
    0x26: ("struct_get", 3, False), 0x27: ("struct_set", 3, False), 0x28: ("array_findstruct", 5, False),
    0x29: ("array_rfindstruct", 5, False), 0x2A: ("array_add", 3, False), 0x2B: ("array_insert", 3, False),
    0x2C: ("array_removelast", 1, False), 0x2D: ("array_remove", 3, False), 0x2E: ("array_clear", 1, False),
    0x2F: ("array_getallmatchingstructs", 6, False), 0x30: ("lock_guards", 0, True),
    0x31: ("unlock_guards", 0, True), 0x32: ("try_lock_guards", 1, True),
}


class PexError(Exception):
    pass


class Reader:
    def __init__(self, data, name):
        self.b, self.p, self.name = data, 0, name
        self.strings = []

    def need(self, n):
        if self.p + n > len(self.b):
            raise PexError(f"{self.name}: the file ends early at byte {self.p} (damaged or cut off)")

    def unpack(self, fmt, n):
        self.need(n)
        v = struct.unpack_from(fmt, self.b, self.p)[0]
        self.p += n
        return v

    def u8(self):
        return self.unpack("<B", 1)

    def u16(self):
        return self.unpack("<H", 2)

    def u32(self):
        return self.unpack("<I", 4)

    def s32(self):
        return self.unpack("<i", 4)

    def u64(self):
        return self.unpack("<Q", 8)

    def f32(self):
        return self.unpack("<f", 4)

    def wstr(self):
        n = self.u16()
        self.need(n)
        s = self.b[self.p:self.p + n].decode("utf-8", "replace")
        self.p += n
        return s

    def sref(self):
        i = self.u16()
        if i >= len(self.strings):
            raise PexError(f"{self.name}: string number {i} is past the end of the string table (damaged)")
        return self.strings[i]

    def value(self):
        """(kind, value): kind is none, ident, str, int, float or bool."""
        t = self.u8()
        if t == 0:
            return ("none", None)
        if t == 1:
            return ("ident", self.sref())
        if t == 2:
            return ("str", self.sref())
        if t == 3:
            return ("int", self.s32())
        if t == 4:
            return ("float", self.f32())
        if t == 5:
            return ("bool", bool(self.u8()))
        raise PexError(f"{self.name}: unknown value type {t} at byte {self.p - 1}")


def read_function(r):
    fn = {"returns": r.sref(), "doc": r.sref(), "userflags": r.u32(), "flags": r.u8()}
    fn["params"] = [(r.sref(), r.sref()) for _ in range(r.u16())]
    fn["locals"] = [(r.sref(), r.sref()) for _ in range(r.u16())]
    code = []
    for _ in range(r.u16()):
        op = r.u8()
        if op not in OPCODES:
            raise PexError(f"{r.name}: unknown opcode {op:#x} at byte {r.p - 1}")
        name, fixed, variadic = OPCODES[op]
        args = [r.value() for _ in range(fixed)]
        if variadic:
            kind, n = r.value()
            if kind != "int" or n < 0:
                raise PexError(f"{r.name}: bad argument count at byte {r.p} (damaged)")
            args += [r.value() for _ in range(n)]
        code.append((name, args))
    fn["code"] = code
    return fn


def read_pex(data, name):
    """{'objects': [...], 'lines': {(object, state, function, type): [line per instruction]}} for one script.
    Each object's 'functions' include property Get and Set handlers, named '<Property>.get' and '<Property>.set';
    fn['debug'] = (name, type) is the key part used in 'lines'."""
    r = Reader(data, name)
    magic = r.u32()
    if magic == 0xDEC057FA:
        raise PexError(f"{name}: a Skyrim (big-endian) script, which isn't supported (Fallout 4 and Starfield only)")
    if magic != 0xFA57C0DE:
        raise PexError(f"{name}: not a compiled Papyrus script (it doesn't start with the PEX signature)")
    major, minor = r.u8(), r.u8()
    r.u16()
    if (major, minor) not in ((3, 9), (3, 12)):
        raise PexError(f"{name}: PEX version {major}.{minor} isn't supported (3.9 Fallout 4, 3.12 Starfield)")
    starfield = (major, minor) >= (3, 12)
    r.u64()
    source = r.wstr()
    r.wstr()
    r.wstr()
    r.strings = [r.wstr() for _ in range(r.u16())]
    lines = {}
    if r.u8():
        r.u64()
        for _ in range(r.u16()):
            obj, state, fn, ftype = r.sref(), r.sref(), r.sref(), r.u8()
            ls = [r.u16() for _ in range(r.u16())]
            # type 0 = a function, 1 = a property's Get, 2 = its Set (fn is then the property's name)
            lines[(obj.lower(), state.lower(), fn.lower(), ftype)] = ls
        for _ in range(r.u16()):
            r.sref(), r.sref(), r.sref(), r.u32()
            for _ in range(r.u16()):
                r.sref()
        for _ in range(r.u16()):
            r.sref(), r.sref()
            for _ in range(r.u16()):
                r.sref()
    for _ in range(r.u16()):
        r.sref(), r.u8()
    objects = []
    for _ in range(r.u16()):
        obj = {"name": r.sref()}
        size = r.u32()
        start = r.p
        obj["extends"] = r.sref()
        r.sref(), r.u8(), r.u32(), r.sref()
        for _ in range(r.u16()):
            r.sref()
            for _ in range(r.u16()):
                r.sref(), r.sref(), r.u32(), r.value(), r.u8(), r.sref()
        obj["variables"] = {}
        for _ in range(r.u16()):
            vname, vtype = r.sref(), r.sref()
            r.u32(), r.value(), r.u8()
            obj["variables"][vname.lower()] = vtype
        if starfield:
            for _ in range(r.u16()):
                r.sref()
        obj["properties"] = {}
        obj["functions"] = []
        for _ in range(r.u16()):
            pname, ptype = r.sref(), r.sref()
            r.sref(), r.u32()
            pfl = r.u8()
            obj["properties"][pname.lower()] = ptype
            if pfl & 4:
                r.sref()
            else:
                for bit, kind, ftype in ((1, "get", 1), (2, "set", 2)):
                    if pfl & bit:
                        fn = read_function(r)
                        fn["name"], fn["state"], fn["debug"] = f"{pname}.{kind}", "", (pname, ftype)
                        obj["functions"].append(fn)
        for _ in range(r.u16()):
            state = r.sref()
            for _ in range(r.u16()):
                fname = r.sref()
                fn = read_function(r)
                fn["name"], fn["state"], fn["debug"] = fname, state, (fname, 0)
                obj["functions"].append(fn)
        if r.p - start not in (size - 4, size):
            raise PexError(f"{name}: object {obj['name']} read {r.p - start} bytes but its size field says {size}")
        objects.append(obj)
    return {"source": source, "objects": objects, "lines": lines}
