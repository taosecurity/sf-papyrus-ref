# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Richard Bejtlich
"""Read Papyrus source (.psc) text: the declarations (for build-local) and the calls (for check).

This is a light reader, not a compiler. It removes comments and strings, joins continued lines, and then reads
one logical line at a time. It understands Scriptname, Function, Event, Struct, State, Property and variable
declarations, While loops, and calls written as Name(...), Object.Name(...), (x as Type).Name(...) and
array[i].Name(...).
Standard library only.
"""
import re

KEYWORDS = {"if", "elseif", "else", "endif", "while", "endwhile", "return", "function", "endfunction", "event",
            "endevent", "state", "endstate", "auto", "property", "endproperty", "struct", "endstruct", "new", "as",
            "is", "self", "parent", "none", "true", "false", "scriptname", "extends", "import", "native", "global",
            "length", "customevent", "group", "endgroup", "guard", "endguard", "trylockguard", "lockguard",
            "endlockguard", "endtrylockguard", "var"}
IDENT = r"[A-Za-z_][A-Za-z0-9_]*"
TYPE = rf"(?:{IDENT}:)*{IDENT}(?:\[\])?"
SCRIPTNAME_RE = re.compile(rf"(?i)^\s*scriptname\s+(?P<name>(?:{IDENT}:)*{IDENT})(?:\s+extends\s+(?P<ext>(?:{IDENT}:)*{IDENT}))?(?P<flags>[\w\s]*)$")
DECL_RE = re.compile(rf"(?i)^\s*(?:(?P<ret>{TYPE})\s+)?(?P<kind>function|event)\s+(?P<name>(?:{IDENT}\.)?{IDENT})\s*\(")
STRUCT_RE = re.compile(rf"(?i)^\s*struct\s+(?P<name>{IDENT})\s*$")
PROP_RE = re.compile(rf"(?i)^\s*(?P<type>{TYPE})\s+property\s+(?P<name>{IDENT})")
VAR_RE = re.compile(rf"(?i)^\s*(?P<type>{TYPE})\s+(?P<name>{IDENT})\s*(?:=|$|\b(?:const|hidden|conditional)\b)")
MEMBER_FLAGS = ("native", "global", "debugonly", "betaonly")


def clean(text, keep_strings=False):
    """Source with comments (and, unless keep_strings, string contents) removed and continued lines joined.
    Returns [(line_number, text)] with the line number of each logical line's first physical line."""
    out, i, n = [], 0, len(text)
    buf = []
    while i < n:
        c = text[i]
        if c == ";" and text.startswith(";/", i):
            j = text.find("/;", i + 2)
            j = n if j < 0 else j + 2
            buf.append("\n" * text.count("\n", i, j))
            i = j
        elif c == ";":
            j = text.find("\n", i)
            i = n if j < 0 else j
        elif c == "{":
            j = text.find("}", i + 1)
            j = n if j < 0 else j + 1
            buf.append("\n" * text.count("\n", i, j))
            i = j
        elif c == '"':
            j = i + 1
            while j < n and text[j] != '"' and text[j] != "\n":
                j += 2 if text[j] == "\\" else 1
            buf.append(text[i:j + 1] if keep_strings else '""')
            i = min(j + 1, n)
        else:
            buf.append(c)
            i += 1
    phys = "".join(buf).replace("\r\n", "\n").replace("\r", "\n").split("\n")
    line, start = "", None
    for num, raw in enumerate(phys, 1):
        if start is None:
            start = num
        s = raw.rstrip()
        if s.endswith("\\"):
            line += s[:-1] + " "
            continue
        line += s
        if line.strip():
            out.append((start, line))
        line, start = "", None
    if line.strip():
        out.append((start, line))
    return out


def split_params(s):
    """The text inside the declaration's parentheses, and what follows the closing one."""
    depth, quoted = 0, False
    for j, c in enumerate(s):
        if c == '"':
            quoted = not quoted
        if quoted:
            continue
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return s[s.index("(") + 1:j], s[j + 1:]
    return s[s.index("(") + 1:], ""


def read_declarations(text):
    """{'name', 'extends', 'flags', 'members': [{'name', 'kind', 'sig', 'flags'}]} for one script's source.
    Members inside a State block are kept only when the empty state lacks them (Papyrus states override)."""
    info = {"name": "", "extends": "", "flags": [], "members": []}
    seen = set()
    in_state = in_struct = False
    for _, line in clean(text, keep_strings=True):
        low = line.strip().lower()
        m = SCRIPTNAME_RE.match(line)
        if m and not info["name"]:
            info["name"], info["extends"] = m.group("name"), m.group("ext") or ""
            info["flags"] = sorted({f.lower() for f in m.group("flags").split()})
            continue
        if re.match(r"(?i)^(auto\s+)?state\b", low):
            in_state = True
            continue
        if low.startswith("endstate"):
            in_state = False
            continue
        if in_struct:
            if low.startswith("endstruct"):
                in_struct = False
            continue
        m = STRUCT_RE.match(line)
        if m:
            in_struct = True
            if m.group("name").lower() not in seen:
                seen.add(m.group("name").lower())
                info["members"].append({"name": m.group("name"), "kind": "struct", "sig": f"Struct {m.group('name')}",
                                        "flags": []})
            continue
        m = DECL_RE.match(line)
        if m:
            name = m.group("name")
            if name.lower() in seen:
                continue
            if in_state and m.group("kind").lower() == "function":
                pass  # a function first seen inside a state still exists on the script
            params, tail = split_params(line[m.start("name"):])
            words = {w.lower() for w in re.findall(IDENT, tail)}
            ret = m.group("ret") or ""
            kind = m.group("kind").capitalize()
            sig = " ".join(x for x in (ret, kind, f"{name}({' '.join(params.split())})", " ".join(tail.split())) if x)
            seen.add(name.lower())
            info["members"].append({"name": name, "kind": kind.lower(), "sig": sig,
                                    "flags": [f for f in MEMBER_FLAGS if f in words]})
    return info


CALL_RE = re.compile(rf"(?:(?P<pre>(?:\bas\s+(?P<cast>{TYPE})\s*\)|(?<!\w)(?P<obj>{IDENT})\s*(?P<idx>\[[^\]]*\])?|\))"
                     rf"\s*\.\s*)|(?<![\w.]))(?P<name>{IDENT})\s*\(")


def read_calls(text):
    """The script's name, parent and every call it makes:
    {'name', 'extends', 'own': {lowercase names declared here}, 'calls': [call]}.
    Each call: {'line', 'name', 'target': ('static'|'var'|'cast'|'self'|'parent'|'unknown', text), 'loop': bool,
    'types': {variable -> type} in scope}."""
    info = {"name": "", "extends": "", "own": set(), "calls": []}
    script_vars, fn_vars = {}, {}
    depth = 0
    lines = clean(text)
    for _, line in lines:
        m = SCRIPTNAME_RE.match(line)
        if m and not info["name"]:
            info["name"], info["extends"] = m.group("name"), m.group("ext") or ""
        m = DECL_RE.match(line)
        if m:
            info["own"].add(m.group("name").lower())
    in_fn = False
    for num, line in lines:
        low = line.strip().lower()
        if SCRIPTNAME_RE.match(line):
            continue
        m = DECL_RE.match(line)
        if m:
            in_fn = not re.search(r"(?i)\bnative\b", split_params(line[m.start("name"):])[1])
            fn_vars = {}
            depth = 0
            params, _ = split_params(line[m.start("name"):])
            for p in params.split(","):
                pm = re.match(rf"\s*(?P<type>{TYPE})\s+(?P<name>{IDENT})", p)
                if pm:
                    fn_vars[pm.group("name").lower()] = pm.group("type")
            continue
        if re.match(r"(?i)^(endfunction|endevent)\b", low):
            in_fn, fn_vars, depth = False, {}, 0
            continue
        m = PROP_RE.match(line)
        if m:
            script_vars[m.group("name").lower()] = m.group("type")
            continue
        m = VAR_RE.match(line)
        if m and m.group("type").lower().rstrip("[]") not in KEYWORDS and m.group("name").lower() not in KEYWORDS:
            (fn_vars if in_fn else script_vars)[m.group("name").lower()] = m.group("type")
        if not in_fn:
            continue
        if re.match(r"(?i)^while\b", low):
            depth += 1
        for cm in CALL_RE.finditer(line):
            name = cm.group("name")
            if name.lower() in KEYWORDS and not cm.group("pre"):
                continue
            if cm.group("cast"):
                target = ("cast", cm.group("cast"))
            elif cm.group("obj"):
                obj = cm.group("obj")
                if cm.start("obj") > 0 and line[:cm.start("obj")].rstrip().endswith("."):
                    target = ("unknown", "")  # a.b.Name(): the type of a.b is not known here
                elif obj.lower() == "self":
                    target = ("self", "")
                elif obj.lower() == "parent":
                    target = ("parent", "")
                elif cm.group("idx"):
                    target = ("var", obj + "[]")
                else:
                    target = ("var", obj)
            elif cm.group("pre"):
                target = ("unknown", "")
            else:
                target = ("self", "")
            info["calls"].append({"line": num, "name": name, "target": target, "loop": depth > 0,
                                  "types": {**script_vars, **fn_vars}})
        if re.match(r"(?i)^endwhile\b", low):
            depth = max(0, depth - 1)
    return info
