# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Richard Bejtlich
"""Build a browsable offline website from YOUR OWN Creation Kit script sources (the `html` command).

The site has a home page, an A-Z list, an inheritance tree and one page per script with its functions, events,
structs, properties and states, the official flags and wiki links, the places other scripts call each function
from, and the highlighted source. Search works from the box at the top of every page.

The pages hold Bethesda's script source text from your own Creation Kit install, so they are for you alone:
open them from your disk or serve them on your home network, and never publish them. Every page carries a
robots "noindex" tag and a note that says so.

The site needs no server and no internet: plain HTML, one stylesheet and two scripts, with no inline scripts
(it works under a strict Content-Security-Policy such as script-src 'self'). Standard library only.
"""
import hashlib
import html
import json
import os
import re
import shutil
import struct

IDENT = r"[A-Za-z_][A-Za-z0-9_]*"
KEYWORDS = {"as", "auto", "autoreadonly", "betaonly", "bool", "collapsed", "collapsedonbase", "collapsedonref",
            "conditional", "const", "customevent", "debugonly", "else", "elseif", "endevent", "endfunction",
            "endgroup", "endguard", "endif", "endlockguard", "endproperty", "endstate", "endstruct",
            "endtrylockguard", "endwhile", "event", "extends", "false", "float", "function", "global", "group",
            "guard", "hidden", "if", "import", "int", "is", "length", "lockguard", "mandatory", "native", "new",
            "none", "parent", "property", "requiresguard", "return", "scriptname", "self", "state", "string",
            "struct", "true", "trylockguard", "var", "while"}
TOKEN_RE = re.compile(r"(?P<bc>;/.*?(?:/;|\Z))|(?P<doc>\{[^}]*(?:\}|\Z))|(?P<lc>;[^\n]*)"
                      r"|(?P<str>\"(?:\\.|[^\"\\\n])*\"?)|(?P<num>\b(?:0x[0-9A-Fa-f]+|\d+(?:\.\d+)?)\b)"
                      rf"|(?P<id>{IDENT}(?::{IDENT})*)", re.S)
PROP_FLAGS = {"auto": "Auto", "autoreadonly": "AutoReadOnly", "const": "Const", "mandatory": "Mandatory",
              "hidden": "Hidden", "conditional": "Conditional"}
STATE_RE = re.compile(rf"(?i)^\s*(?P<auto>auto\s+)?state\s+(?P<name>{IDENT})\s*$")
CUSTOMEVENT_RE = re.compile(rf"(?i)^\s*customevent\s+(?P<name>{IDENT})\s*$")
FLAG_LABELS = {"latent": "Latent", "nondelayed": "Non-delayed", "debugonly": "DebugOnly", "betaonly": "BetaOnly",
               "invsafe": "Inventory-safe", "native": "Native", "global": "Global"}
MAX_CALLERS = 300  # per function, on its page (the count is always exact)
NOTE = ("These pages were built from your own Creation Kit's script sources. They hold Bethesda's script text, so "
        "keep them on your PC or your home network, and never publish or share them.")
MANIFEST = ".sf-papyrus-ref-manifest.json"
REPO = "https://github.com/taosecurity/sf-papyrus-ref"
# Filled in by build() from the command line tool: version, the command that ran, and its options.
TOOL = {"version": "", "command": "sf-papyrus-ref html"}
WARNING = ("These pages are built from the owner's own Starfield game files and contain Bethesda's proprietary "
           "content. They are for the owner's personal use only. Do not share, publish or distribute them.")
IP_WARNING = [
    "sf-papyrus-ref does not exist to share Bethesda's proprietary intellectual property.",
    "This site is intended solely for the use of the person who owns the game and built it from their own "
    "Creation Kit. It is a representation of game content for personal, educational purposes.",
    "It must not be published, distributed or shared with others.",
]


def esc(s):
    return html.escape(str(s), quote=True)


def page_name(script):
    """File name of a script's page: namespaces (Name:Space) become dots, anything odd becomes _."""
    return re.sub(r"[^A-Za-z0-9_.-]", "_", script.replace(":", ".")) + ".html"


# ------------------------------------------------------------------ reading the sources

def read_script(pscread, rel, text):
    """One script's declarations with line numbers: functions, events, structs, properties, states."""
    d = pscread.read_declarations(text)
    if not d["name"]:
        return None
    lines = {}
    props, states, custom = [], [], []
    state = ""
    in_struct = in_fn = False
    for num, line in pscread.clean(text, keep_strings=True):
        low = line.strip().lower()
        m = STATE_RE.match(line)
        if m:
            state = m.group("name")
            states.append({"name": state, "auto": bool(m.group("auto")), "line": num})
            continue
        if low.startswith("endstate"):
            state = ""
            continue
        if in_struct:
            in_struct = not low.startswith("endstruct")
            continue
        m = pscread.STRUCT_RE.match(line)
        if m:
            lines.setdefault(m.group("name").lower(), (num, state))
            in_struct = True
            continue
        m = pscread.DECL_RE.match(line)
        if m:
            lines.setdefault(m.group("name").lower(), (num, state))
            tail = pscread.split_params(line[m.start("name"):])[1]
            in_fn = not re.search(r"(?i)\bnative\b", tail)
            continue
        if re.match(r"(?i)^(endfunction|endevent)\b", low):
            in_fn = False
            continue
        if in_fn:
            continue
        m = CUSTOMEVENT_RE.match(line)
        if m:
            custom.append({"name": m.group("name"), "line": num})
            continue
        m = pscread.PROP_RE.match(line)
        if m:
            # Drop a default value (= True, = None, = "text") first, so it never shows as a flag.
            tail = re.sub(r'^\s*=\s*(?:"(?:\\.|[^"\\])*"|\S+)', "", line[m.end("name"):])
            words = [w for w in re.findall(IDENT, tail) if w.lower() in PROP_FLAGS]
            props.append({"name": m.group("name"), "type": m.group("type"), "line": num,
                          "flags": " ".join(PROP_FLAGS[w.lower()] for w in words)})
    for mem in d["members"]:
        mem["line"], mem["state"] = lines.get(mem["name"].lower(), (0, ""))
    return {"name": d["name"], "extends": d["extends"], "flags": d["flags"], "members": d["members"],
            "props": props, "states": states, "custom": custom, "file": rel.replace("\\", "/"), "text": text}


def collect(pscread, sources, log):
    scripts = {}
    for rel, text in sources:
        s = read_script(pscread, rel, text)
        if not s:
            log.debug("Skipped %s: no Scriptname line", rel)
            continue
        key = s["name"].lower()
        if key in scripts:
            log.debug("Skipped %s: %s was already read from %s", rel, s["name"], scripts[key]["file"])
            continue
        scripts[key] = s
    return scripts


def chain(scripts, name):
    out, seen = [], set()
    while name and name.lower() in scripts and name.lower() not in seen:
        seen.add(name.lower())
        out.append(scripts[name.lower()])
        name = scripts[name.lower()]["extends"]
    return out


def resolve(scripts, script, member):
    """The script on script's parent chain that declares member, or None."""
    for s in chain(scripts, script):
        for m in s["members"]:
            if m["name"].lower() == member.lower():
                return s["name"].lower(), m["name"].lower()
    return None


def call_index(pscread, scripts, log):
    """{(declaring script, member): [(caller script, line)]} for calls whose target can be worked out:
    calls on self or parent, on a variable or property of a known script type, on a cast, or on a script
    by name (global functions). Calls on a chain such as a.b.Name() are left out."""
    callers = {}
    unknown = 0
    for key, s in scripts.items():
        try:
            info = pscread.read_calls(s["text"])
        except Exception as e:  # a reader bug must not stop the whole site
            log.warning("Could not read the calls in %s (%s); its callers are left out.", s["file"], e)
            continue
        imports = [i for i in info["imports"] if i.lower() in scripts]
        for c in info["calls"]:
            kind, text = c["target"]
            hit = None
            if kind == "self":
                hit = resolve(scripts, s["name"], c["name"])
                for imp in imports:
                    hit = hit or resolve(scripts, imp, c["name"])
            elif kind == "parent":
                hit = resolve(scripts, s["extends"], c["name"])
            elif kind in ("var", "cast"):
                obj = text.rstrip("[]")
                typ = obj if kind == "cast" else c["types"].get(obj.lower(), "")
                if not typ and obj.lower() in scripts:
                    typ = obj  # Debug.Trace(): a call on a script by name
                typ = typ.rstrip("[]")
                if typ:
                    hit = resolve(scripts, typ, c["name"])
            if hit:
                callers.setdefault(hit, []).append((s["name"], c["line"]))
            else:
                unknown += 1
    log.info("Linked %d calls to the function they reach; %d calls could not be placed (unknown type, chain or "
             "a name no script declares)", sum(len(v) for v in callers.values()), unknown)
    return callers


# ------------------------------------------------------------------ writing the pages

def highlight(text, known, prefix):
    """The source as HTML lines (one string per line), with syntax colors and links to known scripts."""
    out = []
    pos = 0
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    for m in TOKEN_RE.finditer(text):
        if m.start() > pos:
            out.append(esc(text[pos:m.start()]))
        tok = m.group(0)
        kind = m.lastgroup
        if kind == "id":
            low = tok.lower()
            if low in KEYWORDS:
                out.append(f'<span class="k">{esc(tok)}</span>')
            elif low in known:
                out.append(f'<a class="t" href="{prefix}{page_name(known[low])}">{esc(tok)}</a>')
            elif ":" in low and low.rsplit(":", 1)[0] in known:
                head, tail = tok.rsplit(":", 1)  # Script:Struct links to the struct on its script's page
                out.append(f'<a class="t" href="{prefix}{page_name(known[head.lower()])}#m-{esc(tail.lower())}">{esc(tok)}</a>')
            else:
                out.append(esc(tok))
        else:
            cls = {"bc": "c", "doc": "d", "lc": "c", "str": "s", "num": "n"}[kind]
            # A span never crosses a line break, so each line stands on its own.
            out.append("\n".join(f'<span class="{cls}">{esc(part)}</span>' if part else ""
                                 for part in tok.split("\n")))
        pos = m.end()
    out.append(esc(text[pos:]))
    return "".join(out).split("\n")


def link_types(sig, known, prefix):
    """A signature with every known script name linked."""
    parts, pos = [], 0
    for m in re.finditer(rf"{IDENT}(?::{IDENT})*", sig):
        parts.append(esc(sig[pos:m.start()]))
        word = m.group(0)
        low = word.lower()
        if low in known and low not in KEYWORDS:
            parts.append(f'<a href="{prefix}{page_name(known[low])}">{esc(word)}</a>')
        elif ":" in low and low.rsplit(":", 1)[0] in known:
            head, tail = word.rsplit(":", 1)
            parts.append(f'<a href="{prefix}{page_name(known[head.lower()])}#m-{esc(tail.lower())}">{esc(word)}</a>')
        else:
            parts.append(esc(word))
        pos = m.end()
    parts.append(esc(sig[pos:]))
    return "".join(parts)


def badges(flags):
    return "".join(f'<span class="b b-{esc(f)}">{esc(FLAG_LABELS.get(f, f.capitalize()))}</span>' for f in flags)


def frame(title, root, body, menu, stamp):
    nav = "".join(f'<a href="#{esc(i)}">{esc(t)}</a>' for i, t in menu)
    return f"""<!doctype html>
<html lang="en" data-root="{root}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>{esc(title)}</title>
<link rel="stylesheet" href="{root}assets/site.css">
<script src="{root}assets/site.js" defer></script>
</head>
<body>
<header id="top">
  <a class="brand" href="{root}index.html">Papyrus Source</a>
  <nav class="links"><a href="{root}index.html">Home</a><a href="{root}az.html">A-Z</a><a href="{root}tree.html">Tree</a></nav>
  <div class="search"><input id="q" type="search" placeholder="Search scripts, functions, events, properties" autocomplete="off" aria-label="Search"><div id="sugg" role="listbox"></div></div>
  <button id="theme" type="button" title="Switch between light and dark">Theme</button>
  <p class="warnbar">{esc(WARNING)}</p>
</header>
<aside class="menu"><a href="#top" class="on">Top</a>{nav}</aside>
<main>
{body}
<footer><p>{esc(NOTE)}</p><p>This site was built on {esc(stamp)} by <a href="{REPO}" rel="noreferrer">sf-papyrus-ref</a>{(" " + esc(TOOL["version"])) if TOOL["version"] else ""}, a free, open-source tool (MIT license).</p></footer>
</main>
</body>
</html>
"""


def script_page(s, scripts, known, children, callers, official, stamp):
    p = ""  # script pages live in s/, next to each other
    root = "../"
    key = s["name"].lower()
    parents = chain(scripts, s["name"])[1:]
    ext = s["extends"]
    name = esc(s["name"])
    head = [f'<h1>{name}</h1>']
    line = '<p class="sub">'
    line += f'{name} extends {link_types(ext, known, p)}. ' if ext else f'{name} extends no other script. '
    line += f'Its source file is <code>{esc(s["file"])}</code>.'
    if s["flags"]:
        words = [FLAG_LABELS.get(f, f.capitalize()) for f in s["flags"]]
        listed = words[0] if len(words) == 1 else ", ".join(words[:-1]) + " and " + words[-1]
        line += f' Its script flag{"s are" if len(words) != 1 else " is"} {esc(listed)}.'
    head.append(line + "</p>")
    if parents or ext:
        names = [s["name"]] + [x["name"] for x in parents]
        last = (parents[-1] if parents else s)["extends"]
        if last and last.lower() not in scripts:
            names.append(last)  # the first ancestor that is not in these sources, shown unlinked
        head.append('<p class="chain">Its parent chain runs '
                    + " &rarr; ".join(link_types(n, known, p) if i else f"<b>{esc(n)}</b>"
                                      for i, n in enumerate(names)) + ".</p>")
    kids = sorted(children.get(key, []), key=str.lower)
    if kids:
        verb = "scripts extend" if len(kids) != 1 else "script extends"
        head.append(f'<p class="kids">{len(kids)} {verb} {name}: '
                    + ", ".join(link_types(k, known, p) for k in kids[:60])
                    + (f", and {len(kids) - 60} more are on the Tree page" if len(kids) > 60 else "") + ".</p>")
    body = ["\n".join(head)]
    menu = []

    rows = []
    for m in s["members"]:
        off = official.get((key, m["name"].lower()))
        flags = list(off["flags"]) if off else []
        flags += [f for f in m["flags"] if f not in flags]
        who = callers.get((key, m["name"].lower()), [])
        where = f'<a href="#L{m["line"]}">line {m["line"]}</a>' if m["line"] else ""
        if m["state"]:
            where += f' (state {esc(m["state"])})'
        wiki = f' <a class="wiki" href="{esc(off["wiki"])}" rel="noreferrer">official page</a>' if off and off.get("wiki") else ""
        calls = ""
        if who:
            items = "".join(f'<li><a href="{page_name(known[c.lower()])}#L{n}">{esc(c)}</a> line {n}</li>'
                            for c, n in who[:MAX_CALLERS])
            extra_n = len(who) - MAX_CALLERS
            more = (f"<li>{extra_n} more place{'s call' if extra_n != 1 else ' calls'} it.</li>" if extra_n > 0 else "")
            places = f"{len(who)} places call" if len(who) != 1 else "1 place calls"
            calls = (f'<details><summary>{places} this {esc(m["kind"])}.</summary>'
                     f'<ul class="cols">{items}{more}</ul></details>')
        rows.append(f'<tr id="m-{esc(m["name"].lower())}"><td class="kind">{esc(m["kind"])}</td>'
                    f'<td><code>{link_types(m["sig"], known, p)}</code>{badges(flags)}{wiki}{calls}</td>'
                    f'<td class="where">{where}</td></tr>')
    if rows:
        menu.append(("members", "Functions and events"))
        what = (f"these {len(rows)} functions, events and structs" if len(rows) != 1
                else "this one function, event or struct")
        body.append(f'<section id="members"><h2>{name} declares {what}.</h2>'
                    '<table><thead><tr><th>Kind</th><th>Declaration</th><th>Where</th></tr></thead><tbody>'
                    + "".join(rows) + "</tbody></table></section>")

    if s["props"] or s["custom"] or s["states"]:
        menu.append(("props", "Properties and states"))
        part = [f'<section id="props"><h2>{name} declares these properties, custom events and states.</h2>']
        if s["props"]:
            part.append("<table><thead><tr><th>Property</th><th>Type</th><th>Flags</th><th>Where</th></tr></thead><tbody>"
                        + "".join(f'<tr><td><code>{esc(x["name"])}</code></td><td><code>{link_types(x["type"], known, p)}</code></td>'
                                  f'<td>{esc(x["flags"])}</td><td class="where"><a href="#L{x["line"]}">line {x["line"]}</a></td></tr>'
                                  for x in s["props"]) + "</tbody></table>")
        if s["custom"]:
            part.append("<p>Its custom events are " + ", ".join(f'<a href="#L{x["line"]}"><code>{esc(x["name"])}</code></a>'
                                                               for x in s["custom"]) + ".</p>")
        if s["states"]:
            part.append("<p>Its states are " + ", ".join(f'<a href="#L{x["line"]}"><code>{esc(x["name"])}</code></a>'
                                                        + (" (the script starts in this one)" if x["auto"] else "")
                                                        for x in s["states"]) + ".</p>")
        part.append("</section>")
        body.append("".join(part))

    if parents:
        menu.append(("inherited", "Inherited"))
        part = [f'<section id="inherited"><h2>{name} inherits these functions and events from its parent scripts.</h2>']
        for par in parents:
            names = [m["name"] for m in par["members"] if m["kind"] in ("function", "event")]
            what = "1 function or event" if len(names) == 1 else f"{len(names)} functions and events"
            part.append(f'<details><summary>{esc(par["name"])} gives it {what}.</summary><p class="cols">'
                        + " ".join(f'<a href="{page_name(par["name"])}#m-{esc(n.lower())}"><code>{esc(n)}</code></a>' for n in names)
                        + "</p></details>")
        part.append("</section>")
        body.append("".join(part))

    menu.append(("source", "Source"))
    src = highlight(s["text"], known, p)
    body.append(f'<section id="source"><h2>This is the full source of {name}.</h2><pre class="src">'
                + "".join(f'<span class="ln" id="L{i}"><a href="#L{i}">{i}</a></span>{t}\n' for i, t in enumerate(src, 1))
                + "</pre></section>")
    return frame(f"{s['name']} - Papyrus Source", root, "\n".join(body), menu, stamp)


DIAGRAM = """<figure class="diagram"><svg viewBox="0 0 900 150" role="img" aria-labelledby="dg-t">
<title id="dg-t">How this site is made: your Creation Kit's script sources are read on your PC and turned into these pages, and nothing leaves your network.</title>
<g class="box"><rect x="10" y="30" width="250" height="90" rx="10"/><text x="135" y="62">Your Creation Kit install</text><text x="135" y="86">holds Bethesda's script</text><text x="135" y="106">sources (.psc files).</text></g>
<g class="box"><rect x="325" y="30" width="250" height="90" rx="10"/><text x="450" y="62">sf-papyrus-ref html</text><text x="450" y="86">reads them on your PC and</text><text x="450" y="106">links calls to functions.</text></g>
<g class="box"><rect x="640" y="30" width="250" height="90" rx="10"/><text x="765" y="62">These pages stay on your</text><text x="765" y="86">disk or home network and</text><text x="765" y="106">are never published.</text></g>
<path class="arrow" d="M262 75 H318 M311 68 L320 75 L311 82"/><path class="arrow" d="M577 75 H633 M626 68 L635 75 L626 82"/>
</svg><figcaption>The site is rebuilt from your own sources whenever you run the command again, for example after a Creation Kit update.</figcaption></figure>"""


SCRIPT_DIAGRAM = """<figure class="diagram"><svg viewBox="0 0 1150 150" role="img" aria-labelledby="sd-t">
<title id="sd-t">A script goes from source file to compiled file to a record in a plugin, and the game then runs it by calling its events.</title>
<g class="box"><rect x="10" y="30" width="255" height="90" rx="10"/><text x="137" y="62">A modder writes a script</text><text x="137" y="86">as a .psc source file in</text><text x="137" y="106">the Papyrus language.</text></g>
<g class="box"><rect x="305" y="30" width="255" height="90" rx="10"/><text x="432" y="62">The compiler turns it into</text><text x="432" y="86">a .pex file, which the game</text><text x="432" y="106">loads from its Data folder.</text></g>
<g class="box"><rect x="600" y="30" width="255" height="90" rx="10"/><text x="727" y="62">A record in a plugin, such</text><text x="727" y="86">as a quest or an object, names</text><text x="727" y="106">the script and its properties.</text></g>
<g class="box"><rect x="895" y="30" width="255" height="90" rx="10"/><text x="1022" y="62">The game calls its events,</text><text x="1022" y="86">and the script calls functions</text><text x="1022" y="106">that change the game world.</text></g>
<path class="arrow" d="M267 75 H298 M291 68 L300 75 L291 82"/><path class="arrow" d="M562 75 H593 M586 68 L595 75 L586 82"/><path class="arrow" d="M857 75 H888 M881 68 L890 75 L881 82"/>
</svg><figcaption>A script runs only while a record that names it is loaded in the game.</figcaption></figure>"""

# What a novice needs to know about scripts. Our own words; links go to script pages when those scripts exist.
SCRIPT_INTRO = [
    "Starfield runs small programs called scripts to make things happen in the game. A script can advance a "
    "quest, open a door when you press a button, add an item to your inventory or show a message. Bethesda and "
    "mod authors write scripts in a language called Papyrus.",
    "A script is written as a source file that ends in .psc, and that source is what this site shows. The "
    "Papyrus compiler, which comes with the Creation Kit, turns each source file into a compiled file that ends "
    "in .pex. The game loads only the compiled files, either loose from its Data\\Scripts folder or from inside "
    "its BA2 archives.",
    "A script does nothing until a record in a plugin names it. In the Creation Kit, a modder attaches scripts to "
    "records such as a quest, an object placed in the world, an alias in a quest or a magic effect. The record "
    "also stores the script's property values, such as which door to open or which item to give. When the game "
    "loads that record, it starts a copy of the script for it. The script's first line says what kind of thing "
    "it belongs to: a script that extends {Quest} runs on a quest, and one that extends {ObjectReference} runs "
    "on an object in the world.",
    "The game and the script then talk through events and functions. When something happens, such as the player "
    "activating an object, the game calls an event such as OnActivate on that object's scripts. The script "
    "answers by calling functions. Some functions are written in Papyrus in other scripts. Native functions, "
    "which these pages mark Native, are built into the game itself, and they are how a script really changes the "
    "world, for example {ObjectReference}.AddItem or {ObjectReference}.Enable.",
    "Many scripts on this site are fragments. The Creation Kit writes a fragment for each quest stage, scene, "
    "dialogue line, terminal menu, AI package or perk entry that runs a few lines of script, so the fragment "
    "folders hold thousands of very small scripts.",
    "A script can also have states. Only one state is active at a time, and a function declared inside a state "
    "replaces the normal one while that state is active. Some functions are Latent, which means the script waits "
    "until they finish, as with {Utility}.Wait. The game keeps each running script's variables and state in your "
    "save, so a script picks up where it left off when you load a game.",
]
NO_FRAGMENTS_IN_SOURCES = ("The Creation Kit also writes small scripts called fragments, one for each quest stage, "
                           "scene, dialogue line, terminal menu, AI package or perk entry that runs a few lines of "
                           "script. These sources hold no fragment scripts, so none are on this site.")
NO_FRAGMENTS = ("The Creation Kit also writes small scripts called fragments, one for each quest stage, scene, "
                "dialogue line, terminal menu, AI package or perk entry that runs a few lines of script. This build "
                "leaves the fragments out. Run sf-papyrus-ref html with --include-fragments to add them.")

# A line-by-line walkthrough of one short, widely reused Bethesda script. The tool ships only these explanations
# and the patterns that find each line; the lines themselves come from the user's own sources at build time.
WALK_SCRIPT = "DefaultSetGlobalOnTriggerEnter"
DOC_NEXT = "doc comment on the next line"  # step marker: the documentation comment right after the last match
WALK_STEPS = [
    (r"(?i)^\s*scriptname\s+DefaultSetGlobalOnTriggerEnter\b",
     "The Scriptname line names the script, and the name must match the file name. \"Extends ObjectReference\" "
     "means the script goes on a reference, an object placed in the world. Here that object is a trigger, an "
     "invisible box the player can walk into. Const means the script keeps no changing variables or states, so "
     "there is nothing for the game to remember about it. Default only files the script under \"default\" in "
     "the Creation Kit's add-script window, so level designers find it quickly."),
    (DOC_NEXT,
     "Text in curly braces is a documentation comment. The Creation Kit shows it as the script's description, "
     "and the game ignores it."),
    (r"(?i)^\s*GlobalVariable\s+Property\s+GlobalToSet\b",
     "This line declares a property, a setting the modder chooses in the Creation Kit for each object that uses "
     "the script. Its type is GlobalVariable, a record that holds one number the whole game can read; quest "
     "conditions often check globals. \"Const auto\" means the value comes from the Creation Kit and the script "
     "never changes it."),
    (DOC_NEXT,
     "Each property can have its own documentation comment, which the Creation Kit shows beside the property."),
    (r"(?i)^\s*Float\s+Property\s+NumToSetGlobalTo\b",
     "The second property is the number to store. Float means a number that can have decimals. Because each "
     "object fills in its own properties, the same script sets different globals to different values all over "
     "the game."),
    (r"(?i)^\s*Event\s+OnTriggerEnter\b",
     "An event is code the game runs when something happens. OnTriggerEnter runs each time something enters the "
     "trigger, and akActionRef is whatever entered it: the player, a companion, a creature or a thrown object."),
    (r"(?i)^\s*if\b.*GetPlayer",
     "The If line tests a condition. Game.GetPlayer() is a native function that returns the player, so the lines "
     "inside the If run only when the player walks in."),
    (r"(?i)^\s*GlobalToSet\s*\.\s*SetValue\b",
     "This line does the real work. It calls SetValue on the global from the first property and passes the "
     "number from the second, so the global now holds that number. A quest stage, a dialogue condition or another "
     "script can then react to the new value."),
    (r"(?i)^\s*;\s*debug\.trace",
     "A semicolon starts a comment, so the game skips this line. Bethesda left a Debug.Trace call here, switched "
     "off. Switched on, it would write the global's new value to the Papyrus log, which is how modders check that "
     "a script ran."),
    (r"(?i)^\s*endif\b", "EndIf closes the If block."),
    (r"(?i)^\s*endevent\b",
     "EndEvent closes the event. The script has no other code, so it waits until something enters the trigger "
     "again."),
]

# Plain descriptions of the folders in the Creation Kit's sources. Unknown folders get a general sentence.
OWNERS = {"": "the base game", "fx": "the base game", "fxscripts": "the base game",
          "nativeterminal": "the base game", "peo": "the base game", "fragments": "the base game",
          "sfbgs00d": "the free update in SFBGS00D.esm", "sfbgs003": "the Trackers Alliance",
          "dlc03": "the Trackers Alliance"}
FOLDER_TEXT = {
    "": "These are the base game's own scripts. They include the native scripts the engine defines, such as "
        "Actor, Quest, ObjectReference and Debug, the general-purpose Default scripts, and the scripts for quests, "
        "cities and activities.",
    "fx": "This folder holds a visual-effects script that sets off an explosion on an animation event.",
    "fxscripts": "This folder holds visual-effects scripts for camera shakes, effect shaders and landing effects.",
    "nativeterminal": "This folder holds the scripts behind terminals that control alarms, containers, display "
                      "cases, doors, robots and traps.",
    "peo": "This folder holds the scripts for the sleep and sustenance (food and drink) effects.",
    "sfbgs003": "This folder holds the Trackers Alliance scripts (SFBGS003.esm) for bounty missions, the bounty "
                "scanner and wanted posters.",
    "dlc03": "This folder holds more Trackers Alliance scripts, for the Trackers' headquarters and the bounty "
             "\"The Starjacker\" (SFTA00).",
    "sfbgs00d": "This folder holds the scripts of the free update in SFBGS00D.esm, which every copy of the game "
                "loads. Its features include legendary crafting, cruise mode and new elite crew.",
}
FRAGMENT_TEXT = {
    "quests": "These fragments run when a quest reaches a stage.",
    "scenes": "These fragments run at points in a scene, such as when a phase begins or ends.",
    "topicinfos": "These fragments run when a line of dialogue begins or ends.",
    "terminals": "These fragments run when the player picks an item in a terminal menu.",
    "packages": "These fragments run when an AI package begins, ends or changes.",
    "perks": "These fragments run from perk entries, such as an activation choice that a perk adds.",
}

# The site's own changes, newest first (dates are release dates of sf-papyrus-ref).
NEWS = [
    ("2026-11-22", "sf-papyrus-ref 0.2.2 added a personal-use warning to every page, links to the tool, and a "
                   "section that explains how this site was made."),
    ("2026-11-21", "sf-papyrus-ref 0.2.1 added this What's new list, the game and Creation Kit versions, an "
                   "explanation of what a script is and how the game uses it, a line-by-line walkthrough of one "
                   "script and a description of each folder."),
    ("2026-11-21", "sf-papyrus-ref 0.2.0 introduced this site."),
]


def folder_text(folder):
    parts = folder.lower().split("/")
    if "fragments" in parts:
        i = parts.index("fragments")
        kind = parts[i + 1] if i + 1 < len(parts) else ""
        first = FRAGMENT_TEXT.get(kind, "These are fragments, small scripts the Creation Kit writes for records.")
        owner = OWNERS.get(parts[0] if i else "", "")
        return first + (f" They belong to {owner}." if owner else "")
    if parts[0] in FOLDER_TEXT and len(parts) == 1:
        return FOLDER_TEXT[parts[0]]
    return f"This folder holds scripts in the {folder.replace('/', ':')} namespace."


def exe_version(path):
    """The file version of a Windows program (from its VS_FIXEDFILEINFO), or None. Reads from the end, where the
    version resource usually is."""
    # The real VS_FIXEDFILEINFO follows the UTF-16 key "VS_VERSION_INFO" and has structure version 1.0. Taking
    # the first such block from the end skips stray copies of the 4-byte signature in code or data.
    key = "VS_VERSION_INFO".encode("utf-16-le")
    sig = b"\xbd\x04\xef\xfe"
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as f:
            end, chunk, overlap = size, 8 << 20, 256
            while end > 0:
                start = max(0, end - chunk)
                f.seek(start)
                data = f.read(end - start + overlap)
                i = data.rfind(key)
                while i >= 0:
                    j = data.find(sig, i + len(key), i + len(key) + 16)
                    if j >= 0 and j + 16 <= len(data):
                        strucver, ms, ls = struct.unpack_from("<III", data, j + 4)
                        if strucver == 0x00010000:
                            return f"{ms >> 16}.{ms & 0xFFFF}.{ls >> 16}.{ls & 0xFFFF}"
                    i = data.rfind(key, 0, i)
                end = start
    except (OSError, struct.error):
        pass
    return None


def find_versions(sources):
    """(game version, Creation Kit version), each None when it can't be found near the sources."""
    d = os.path.abspath(sources)
    for _ in range(6):
        if os.path.isfile(os.path.join(d, "Starfield.exe")):
            return exe_version(os.path.join(d, "Starfield.exe")), exe_version(os.path.join(d, "CreationKit.exe"))
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    return None, None


def owner_counts(scripts):
    counts = {}
    for s in scripts.values():
        top = folder_of(s["file"]).split("/")[0].lower()
        owner = OWNERS.get(top, f"the {top} folder")
        counts[owner] = counts.get(owner, 0) + 1
    return counts


def content_section(scripts, game, ck):
    counts = owner_counts(scripts)
    items = []
    labels = {"the base game": "The base game (Starfield.esm)",
              "the free update in SFBGS00D.esm": "The free update in SFBGS00D.esm, which every copy of the game loads,",
              "the Trackers Alliance": "The Trackers Alliance (SFBGS003.esm)"}
    for owner, n in sorted(counts.items(), key=lambda x: -x[1]):
        label = labels.get(owner, owner[0].upper() + owner[1:])
        items.append(f"<li>{esc(label)} has {n} script{'s' if n != 1 else ''} here.</li>")
    missing = []
    def has(marker):
        # The marker as a whole word part: at the start or after ":" or "_", and followed by "_", ":" or the end
        # (SFBGS001:..., QF_SFBGS001_...), so a name such as QF_SFTerrainSurvey never counts.
        pat = re.compile(rf"(?:^|[:_]){marker}(?:[_:]|$)")
        return any(pat.search(k) or pat.search(folder_of(s["file"]).lower().replace("/", ":"))
                   for k, s in scripts.items())
    if not has("sfbgs001"):
        missing.append("Shattered Space")
    if not has("sfter"):
        missing.append("the Terran Armada Creation")
    ver = (f"Bethesda ships these sources with the Creation Kit {esc(ck)}" if ck else
           "Bethesda ships these sources with the Creation Kit")
    ver += f", and the game installed next to it is version {esc(game)}." if game else "."
    text = (f"<p>Every script on this site is Starfield Papyrus source. {ver} The sources cover this "
            f"content:</p><ul>{''.join(items)}</ul>")
    if missing:
        text += ("<p>The Creation Kit's sources don't include " + " or ".join(missing) + ", so their scripts "
                 "are not on this site.</p>")
    return '<section id="content"><h2>These are the Starfield scripts that the Creation Kit includes.</h2>' + text + "</section>"


def walkthrough_section(scripts, known):
    s = scripts.get(WALK_SCRIPT.lower())
    if not s:
        return ""
    lines = s["text"].replace("\r\n", "\n").replace("\r", "\n").split("\n")
    # Lines that hold no code: blank lines, ; comments and every line of a ;/ ... /; block comment.
    quiet, in_block = set(), False
    for i, ln in enumerate(lines):
        st = ln.strip()
        if in_block:
            quiet.add(i)
            in_block = "/;" not in st
        elif st.startswith(";/"):
            quiet.add(i)
            in_block = "/;" not in st[2:]
        elif not st or st.startswith(";"):
            quiet.add(i)
    decl = re.compile(r"(?i)^\s*(group|struct|state|auto\s+state|property|event|function)\b|\bproperty\b|\bfunction\b|\bevent\b")
    rows, pos, last = [], 0, None
    for pattern, text in WALK_STEPS:
        if pattern == DOC_NEXT:
            # A documentation comment belongs to the line just before it: look at the next line that holds code.
            if last is not None:
                nxt = next((i for i in range(last + 1, len(lines)) if i not in quiet), None)
            else:
                # No anchor line: the first doc comment before the next declaration.
                nxt = next((i for i in range(pos, len(lines)) if i not in quiet
                            and (re.search(r"^\s*\{", lines[i]) or decl.search(lines[i]))), None)
            hit = nxt if nxt is not None and re.search(r"^\s*\{", lines[nxt]) else None
        else:
            hit = next((i for i in range(pos, len(lines)) if re.search(pattern, lines[i])), None)
            last = hit
        if hit is None:
            code = '<td class="where">not found</td><td><em>This line is not in your version of the script.</em></td>'
        else:
            pos = hit + 1
            code = (f'<td class="where"><a href="s/{page_name(s["name"])}#L{hit + 1}">{hit + 1}</a></td>'
                    f'<td><pre class="src one">{highlight(lines[hit].strip(), known, "s/")[0]}</pre></td>')
        rows.append(f"<tr>{code}<td>{esc(text)}</td></tr>")
    link = f'<a href="s/{page_name(s["name"])}">{esc(s["name"])}</a>'
    return ('<section id="walk"><h2>Here is one script, explained line by line.</h2>'
            f"<p>{link} is one of Bethesda's general-purpose scripts. A level designer can attach it to any "
            "trigger, so that walking into a place sets a global variable that a quest or a conversation can "
            "check. It is short, and it shows most of what a script is made of.</p>"
            '<table class="walk"><thead><tr><th>Line</th><th>Code</th><th>What it does</th></tr></thead><tbody>'
            + "".join(rows) + "</tbody></table>"
            "<p>To use this script in your own mod, you attach it to a trigger in the Creation Kit and fill in its "
            "two properties. You don't write any code.</p></section>")


def whats_new(builds, scripts):
    """The site's news and the recorded builds, newest first. Items sort by full date and time; a NEWS item
    (date only) sorts after the builds of its day, and a later NEWS item before an earlier one."""
    items = [((d, 0, "", len(NEWS) - i), d, esc(t), "") for i, (d, t) in enumerate(NEWS)]
    for order, b in enumerate(builds):  # builds are oldest first, so a later one wins a tie
        extra = ""
        for key, verb in (("added", "were added"), ("changed", "changed"), ("removed", "were removed")):
            names = [n for n in b.get(key) or [] if isinstance(n, str)]
            if names:
                # Link only scripts that still have a page; a later build may have removed one.
                shown = ", ".join(f'<a href="s/{page_name(n)}">{esc(n)}</a>' if n.lower() in scripts else esc(n)
                                  for n in names)
                what = f"This script {verb.replace('were', 'was')}" if len(names) == 1 else f"These {len(names)} scripts {verb}"
                extra += (f"<details><summary>{what}.</summary>"
                          f'<p class="cols">{shown}.</p></details>')
        built = str(b.get("built", ""))
        items.append(((built[:10], 1, built[10:], order), built[:10], esc(b.get("text", "")), extra))
    items.sort(key=lambda x: x[0], reverse=True)
    lis = "".join(f'<li><b>{esc(d)}:</b> {t}{extra}</li>' for _, d, t, extra in items[:8])
    return '<section id="news"><h2>What\'s new</h2><ul class="news">' + lis + "</ul></section>"


def how_section(scripts, n_members, n_calls, sources, stamp, game, ck):
    """How running sf-papyrus-ref against the Creation Kit's sources made these pages, and what the tool is."""
    ver = f" {esc(TOOL['version'])}" if TOOL["version"] else ""
    versions = ""
    if ck or game:
        versions = (" The Creation Kit is version " + esc(ck or "unknown") + ", and the game is version "
                    + esc(game or "unknown") + ".")
    warn = "".join(f"<p>{esc(x)}</p>" for x in IP_WARNING)
    steps = [
        "It read each script's declarations: its Scriptname line and parent script, and its functions, events, "
        "structs, properties and states.",
        f"It worked out which function each call reaches by following variable types and parent scripts. This "
        f"build linked {n_calls} calls.",
        "It added the official flags and wiki links from the name list that ships with the tool.",
        "It wrote one page per script, the A-Z list, the inheritance tree and the search index.",
        "It compared the scripts with the last build to fill in What's new.",
    ]
    commands = [
        ("lookup", "tells you whether a function or event exists, which script it is on and what its flags are."),
        ("script", "lists every function and event on one script."),
        ("list", "lists every function with a flag, such as Latent or DebugOnly."),
        ("check", "checks your mod's .psc or .pex scripts for calls that do nothing on consoles or should never ship."),
        ("compare", "tells you which of a mod's .psc files are Bethesda's scripts, changed or not."),
        ("build-local", "reads signatures from your own Creation Kit into a local cache."),
        ("diff", "compares the official name list with your Creation Kit's sources."),
        ("mcp", "lets AI assistants such as Claude Code look names up instead of guessing."),
    ]
    return (
        '<section id="how"><h2>This is how the site is made.</h2>'
        f'<div class="note warn">{warn}</div>'
        f"<p>This copy was made on {esc(stamp)} by running <code>{esc(TOOL['command'])}</code> with "
        f'<a href="{REPO}" rel="noreferrer">sf-papyrus-ref</a>{ver}. It read {len(scripts)} script source files '
        f"from <code>{esc(sources)}</code>.{versions}</p>"
        + DIAGRAM +
        "<p>The tool worked through the sources in five steps:</p><ol>"
        + "".join(f"<li>{esc(s)}</li>" for s in steps) + "</ol>"
        f"<p>Together, the scripts declare {n_members} functions, events and structs. Nothing was sent anywhere: "
        "the tool runs offline, and the release itself contains no game code.</p>"
        '<h3>About sf-papyrus-ref</h3>'
        f'<p><a href="{REPO}" rel="noreferrer">sf-papyrus-ref</a> is a free, open-source tool (MIT license) for '
        "Starfield modders. It runs offline on Windows or Linux with Python's standard library. Besides "
        "<code>html</code>, which made this site, it has these commands:</p><ul>"
        + "".join(f"<li><code>{esc(c)}</code> {esc(d)}</li>" for c, d in commands) + "</ul>"
        '<h3>How to make your own copy</h3><ol>'
        f'<li>Install Python 3.9 or newer, and download sf-papyrus-ref from its '
        f'<a href="{REPO}/releases" rel="noreferrer">releases page</a>.</li>'
        "<li>Install the Starfield Creation Kit from Steam, which brings the script sources.</li>"
        "<li>Run <code>sf-papyrus-ref html</code>, or <code>sf-papyrus-ref html --include-fragments</code> to add "
        "the thousands of fragment scripts.</li>"
        "<li>Run the same command again after a Creation Kit update, and What's new lists what changed.</li></ol>"
        "</section>")


def home_page(scripts, children, folders, n_members, n_calls, sources, stamp, game=None, ck=None, builds=(),
              fragments=False, asked_fragments=False):
    roots = sorted((s for s in scripts.values() if not s["extends"] or s["extends"].lower() not in scripts),
                   key=lambda s: -len(children.get(s["name"].lower(), [])))
    top = sorted(scripts.values(), key=lambda s: -len(children.get(s["name"].lower(), [])))[:24]
    known = {k: s["name"] for k, s in scripts.items()}

    def link(word):
        return f'<a href="s/{page_name(known[word.lower()])}">{word}</a>' if word.lower() in known else word
    frag_text = NO_FRAGMENTS_IN_SOURCES if asked_fragments else NO_FRAGMENTS
    paras = [p if fragments or not p.startswith("Many scripts on this site are fragments") else frag_text
             for p in SCRIPT_INTRO]
    intro = "".join("<p>" + re.sub(r"\{(\w+)\}", lambda m: link(m.group(1)), esc(p)) + "</p>" for p in paras)
    versions = (f" They come from the Creation Kit {esc(ck)}" if ck else " They come from your Creation Kit")
    versions += f", for Starfield {esc(game)}." if game else "."
    body = [
        "<h1>Papyrus Source</h1>",
        f'<p class="lede">This site holds Starfield\'s Papyrus script sources: {len(scripts)} scripts with '
        f"{n_members} functions, events and structs.{versions} It links {n_calls} calls to the function they "
        "reach. Type in the box at the top to find a script, function, event or property, or browse the A-Z list "
        "and the inheritance tree.</p>",
        f'<p class="note">These pages were read from <code>{esc(sources)}</code> and made with '
        f'<code>{esc(TOOL["command"])}</code>, which anyone can download for free from '
        f'<a href="{REPO}" rel="noreferrer">GitHub</a> to build this site from their own Creation Kit.</p>',
        whats_new(builds, scripts),
        '<section id="scripts"><h2>A script is a small program that the game runs.</h2>' + intro + SCRIPT_DIAGRAM
        + "</section>",
        content_section(scripts, game, ck),
        walkthrough_section(scripts, known),
        '<section id="folders"><h2>The scripts are grouped by the folder they came from.</h2><table><thead><tr>'
        "<th>Folder</th><th>Scripts</th><th>What the scripts are</th></tr></thead><tbody>"
        + "".join(f'<tr><td><a href="az.html#f-{esc(re.sub(r"[^A-Za-z0-9_-]", "_", f or "top"))}">'
                  f'{esc(f or "(top level)")}</a></td><td>{n}</td><td>{esc(folder_text(f))}</td></tr>'
                  for f, n in sorted(folders.items())) + "</tbody></table></section>",
        '<section id="parents"><h2>These scripts are extended most often.</h2><p>The number is how many scripts '
        'extend each one directly.</p><ul class="cols">'
        + "".join(f'<li><a href="s/{page_name(s["name"])}">{esc(s["name"])}</a> '
                  f'<span class="count">{len(children.get(s["name"].lower(), []))}</span></li>'
                  for s in top) + f"</ul><p>{len(roots)} scripts start a family, because they extend nothing or "
        "extend a script that is not in these sources.</p></section>",
        how_section(scripts, n_members, n_calls, sources, stamp, game, ck),
        '<section id="reading"><h2>This is how to read a script page.</h2><p>Each script page lists its functions, '
        "events and structs with their declarations. Flags such as Latent, Non-delayed, DebugOnly and BetaOnly "
        "come from the official Creation Kit wiki list that ships with sf-papyrus-ref, and Native and Global come "
        "from the source. Under each function, a line such as \"3 places call this function\" opens a list of the "
        "places another script calls it. A call is listed when the caller's type can be worked out from the "
        "source, and a call through a chain such as a.b.Name() can't be, so the lists can be short. Line links "
        "jump into the highlighted source at the bottom of the page.</p></section>",
    ]
    menu = [("news", "What's new"), ("scripts", "What a script is"), ("content", "What is included"),
            ("walk", "One script explained"), ("folders", "Scripts by folder"), ("parents", "Most extended"),
            ("how", "How the site is made"), ("reading", "Reading a page")]
    if not walkthrough_section(scripts, known):
        menu = [m for m in menu if m[0] != "walk"]
    return frame("Papyrus Source", "", "\n".join(b for b in body if b), menu, stamp)


def az_page(scripts, stamp):
    by_folder = {}
    for s in scripts.values():
        by_folder.setdefault(folder_of(s["file"]), []).append(s["name"])
    menu, body = [], ["<h1>Every script is listed here from A to Z, folder by folder.</h1>"]
    for f in sorted(by_folder):
        fid = "f-" + re.sub(r"[^A-Za-z0-9_-]", "_", f or "top")
        menu.append((fid, f or "(top level)"))
        names = sorted(by_folder[f], key=str.lower)
        where = f"The {esc(f)} folder" if f else "The top folder"
        count = f"{len(names)} script{'s' if len(names) != 1 else ''}"
        body.append(f'<section id="{fid}"><h2>{where} holds {count}.</h2><p>{esc(folder_text(f))}</p><p class="cols">'
                    + " ".join(f'<a href="s/{page_name(n)}">{esc(n)}</a>' for n in names) + "</p></section>")
    return frame("All scripts - Papyrus Source", "", "\n".join(body), menu, stamp)


def tree_page(scripts, children, stamp):
    def node(name, depth, seen):
        kids = sorted(children.get(name.lower(), []), key=str.lower)
        label = (f'<a href="s/{page_name(name)}">{esc(name)}</a>' if name.lower() in scripts else esc(name))
        if not kids or name.lower() in seen or depth > 40:
            return f"<li>{label}</li>"
        seen = seen | {name.lower()}
        inner = "".join(node(k, depth + 1, seen) for k in kids)
        opn = " open" if depth < 1 else ""
        return f'<li><details{opn}><summary>{label} <span class="count">{len(kids)}</span></summary><ul>{inner}</ul></details></li>'
    roots = sorted({s["extends"] if s["extends"] and s["extends"].lower() not in scripts else s["name"]
                    for s in scripts.values() if not s["extends"] or s["extends"].lower() not in scripts}, key=str.lower)
    big = [r for r in roots if children.get(r.lower())]
    lone = [r for r in roots if not children.get(r.lower())]
    body = ["<h1>The inheritance tree shows which script extends which.</h1>",
            "<p>Each script is listed under the script it extends. The number is how many scripts extend it "
            "directly. Click a name to open its page, or the arrow to open its branch.</p>",
            '<section id="families"><h2>These scripts start the families.</h2><ul class="tree">'
            + "".join(node(r, 0, frozenset()) for r in big) + "</ul></section>",
            '<section id="alone"><h2>These scripts stand alone, because nothing here extends them and they extend nothing here.</h2><p class="cols">'
            + " ".join(f'<a href="s/{page_name(r)}">{esc(r)}</a>' if r.lower() in scripts else esc(r) for r in lone)
            + "</p></section>"]
    return frame("Inheritance tree - Papyrus Source", "", "\n".join(body),
                 [("families", "Families"), ("alone", "Stand-alone scripts")], stamp)


def folder_of(rel):
    parts = rel.split("/")
    for i, p in enumerate(parts):
        if p.lower() == "source":
            parts = parts[i + 1:]
            break
    return "/".join(parts[:-1])


def search_index(scripts):
    """[[name, script, kind, page, line]] for the search box. Kind: s script, f function, e event, t struct,
    p property."""
    rows = []
    kinds = {"function": "f", "event": "e", "struct": "t"}
    for s in sorted(scripts.values(), key=lambda s: s["name"].lower()):
        pg = page_name(s["name"])
        rows.append([s["name"], "", "s", pg, 0])
        for m in s["members"]:
            rows.append([m["name"], s["name"], kinds.get(m["kind"], "f"), pg, m["line"]])
        for x in s["props"]:
            rows.append([x["name"], s["name"], "p", pg, x["line"]])
    return rows


def count(items, one, many):
    return f"1 script {one}" if len(items) == 1 else f"{len(items)} scripts {many}"


def read_manifest(path, log):
    """The last build's record, or None when there is none or it is damaged (then this build starts afresh)."""
    try:
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
    except (OSError, ValueError):
        return None

    def good_build(b):
        return (isinstance(b, dict) and isinstance(b.get("text"), str) and isinstance(b.get("built"), str)
                and all(isinstance(b.get(k), (str, type(None))) for k in ("game", "ck"))
                and all(isinstance(b.get(k, []), list) for k in ("added", "removed", "changed"))
                and isinstance(b.get("fragments", False), bool))
    ok = (isinstance(doc, dict) and isinstance(doc.get("scripts"), dict) and isinstance(doc.get("builds"), list)
          and all(isinstance(v, list) and len(v) == 2 and all(isinstance(x, str) for x in v)
                  for v in doc["scripts"].values())
          and all(good_build(b) for b in doc["builds"]))
    if not ok:
        log.warning("Ignored %s because it is damaged; What's new starts again with this build.", path)
        return None
    return doc


def update_manifest(out, scripts, stamp, game, ck, log, fragments=False):
    """Compare this build's scripts with the last build's (kept in a hidden file in the site folder), record a
    What's new entry when anything changed, and return (the recorded builds, oldest first and at most 10; the game version; the Creation Kit version)."""
    path = os.path.join(out, MANIFEST)
    prev = read_manifest(path, log)
    now = {}
    for key, s in scripts.items():
        text = "\n".join(x.rstrip() for x in s["text"].replace("\r\n", "\n").replace("\r", "\n").split("\n")).strip()
        now[key] = [s["name"], hashlib.sha1(text.encode("utf-8")).hexdigest()]
    builds = prev["builds"] if prev else []
    ckt = f"the Creation Kit {ck}" if ck else "your Creation Kit"
    if not prev or not builds:
        entry = {"built": stamp, "game": game, "ck": ck, "fragments": fragments,
                 "text": f"The site was built for the first time, from the sources in {ckt} ({len(now)} scripts)."}
    else:
        old = prev["scripts"]
        added = sorted(now[k][0] for k in now.keys() - old.keys())
        removed = sorted(old[k][0] for k in old.keys() - now.keys())
        changed = sorted(now[k][0] for k in now.keys() & old.keys() if now[k][1] != old[k][1])
        last = builds[-1] if builds else {}
        # A version this build reads counts as changed when it differs from the last one, including a version read
        # for the first time. A version this build can't read (a copied zip has no .exe next to it) never counts,
        # and the last known one is kept.
        versions = any(new and new != last.get(k) for k, new in (("game", game), ("ck", ck)))
        game, ck = game or last.get("game"), ck or last.get("ck")  # keep a known version when this build can't read it
        ckt = f"the Creation Kit {ck}" if ck else "your Creation Kit"
        entry = None
        if added or removed or changed or versions:
            was = f", which replaced the Creation Kit {last.get('ck')}" if ck and last.get("ck") and last.get("ck") != ck else ""
            why = ""
            if "fragments" in last and last["fragments"] != fragments:
                why = (" This build includes the fragment scripts, which the last one left out."
                       if fragments else " This build leaves out the fragment scripts, which the last one included.")
            entry = {"built": stamp, "game": game, "ck": ck,
                     "fragments": fragments,
                     "text": f"The site was rebuilt from the sources in {ckt}{was}.{why} Since the build of "
                             f"{str(last.get('built', 'before'))[:10]}, {count(added, 'was added', 'were added')}, "
                             f"{count(removed, 'was removed', 'were removed')} and "
                             f"{count(changed, 'changed', 'changed')}.",
                     "added": added[:300], "removed": removed[:300], "changed": changed[:300]}
        log.info("Since the last build: %s", entry["text"] if entry else "no script changed")
    if entry:
        builds = (builds + [entry])[-10:]
    try:
        write(path, json.dumps({"format": 1, "builds": builds, "scripts": now}, ensure_ascii=False))
    except OSError as e:
        log.warning("Could not save %s (%s); What's new will not know about this build.", path, e)
    return builds, game, ck


def write(path, text):
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def build(pscread, sources_iter, sources_label, out, official, stamp, log, assets_dir, asked_fragments=False,
          tool=None):
    """Write the whole site into out (which must be empty or a site this command built). Returns counts."""
    TOOL.update(tool or {})
    scripts = collect(pscread, sources_iter, log)
    if not scripts:
        return None
    known = {k: s["name"] for k, s in scripts.items()}
    children = {}
    for s in scripts.values():
        if s["extends"]:
            children.setdefault(s["extends"].lower(), []).append(s["name"])
    callers = call_index(pscread, scripts, log)
    folders = {}
    for s in scripts.values():
        f = folder_of(s["file"])
        folders[f] = folders.get(f, 0) + 1

    # The marker goes first, so a build that is stopped partway can still be rebuilt over.
    os.makedirs(out, exist_ok=True)
    write(os.path.join(out, ".sf-papyrus-ref-site"), "Built by sf-papyrus-ref html. Safe to rebuild over.\n")
    os.makedirs(os.path.join(out, "s"), exist_ok=True)
    os.makedirs(os.path.join(out, "assets"), exist_ok=True)
    for name in ("site.css", "site.js"):
        shutil.copyfile(os.path.join(assets_dir, name), os.path.join(out, "assets", name))
    write(os.path.join(out, "assets", "search-index.js"),
          "window.SFPR_INDEX=" + json.dumps(search_index(scripts), ensure_ascii=False, separators=(",", ":")) + ";\n")
    n_members = sum(len(s["members"]) for s in scripts.values())
    n_calls = sum(len(v) for v in callers.values())
    game, ck = find_versions(sources_label)
    log.info("Game version %s, Creation Kit version %s", game or "unknown", ck or "unknown")
    fragments = any("fragments" in folder_of(s["file"]).lower().split("/") for s in scripts.values())
    # The page shows the same versions What's new records (the last known ones when this build can't read them).
    builds, game, ck = update_manifest(out, scripts, stamp, game, ck, log, fragments)
    write(os.path.join(out, "index.html"), home_page(scripts, children, folders, n_members, n_calls, sources_label,
                                                     stamp, game, ck, builds, fragments, asked_fragments))
    write(os.path.join(out, "az.html"), az_page(scripts, stamp))
    write(os.path.join(out, "tree.html"), tree_page(scripts, children, stamp))
    wanted = {"index.html", "az.html", "tree.html"}
    pages = set()
    for s in scripts.values():
        pg = page_name(s["name"])
        pages.add(pg.lower())
        write(os.path.join(out, "s", pg), script_page(s, scripts, known, children, callers, official, stamp))
    # Pages of scripts that are gone from the sources since the last build are removed.
    for f in os.listdir(os.path.join(out, "s")):
        if f.lower().endswith(".html") and f.lower() not in pages:
            os.remove(os.path.join(out, "s", f))
            log.debug("Removed old page s/%s", f)
    return {"scripts": len(scripts), "members": n_members, "calls": n_calls, "folders": len(folders),
            "pages": len(pages) + len(wanted)}
