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
import html
import json
import os
import re
import shutil

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
STATE_RE = re.compile(rf"(?i)^\s*(?P<auto>auto\s+)?state\s+(?P<name>{IDENT})\s*$")
CUSTOMEVENT_RE = re.compile(rf"(?i)^\s*customevent\s+(?P<name>{IDENT})\s*$")
FLAG_LABELS = {"latent": "Latent", "nondelayed": "Non-delayed", "debugonly": "DebugOnly", "betaonly": "BetaOnly",
               "invsafe": "Inventory-safe", "native": "Native", "global": "Global"}
MAX_CALLERS = 300  # per function, on its page (the count is always exact)
NOTE = ("Built from your own Creation Kit script sources. These pages hold Bethesda's script text: keep them on "
        "your PC or your home network, and never publish or share them.")


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
            words = [w for w in re.findall(IDENT, line[m.end("name"):]) if w.lower() in KEYWORDS]
            props.append({"name": m.group("name"), "type": m.group("type"), "line": num,
                          "flags": " ".join(w.capitalize() for w in words)})
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
                out.append(f'<a class="t" href="{prefix}{page_name(known[head.lower()])}#m-{esc(tail)}">{esc(tok)}</a>')
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
            parts.append(f'<a href="{prefix}{page_name(known[head.lower()])}#m-{esc(tail)}">{esc(word)}</a>')
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
</header>
<aside class="menu"><a href="#top" class="on">Top</a>{nav}</aside>
<main>
{body}
<footer><p>{esc(NOTE)}</p><p>Built {esc(stamp)} by sf-papyrus-ref (MIT, https://github.com/taosecurity/sf-papyrus-ref).</p></footer>
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
    head = [f'<h1>{esc(s["name"])}</h1>']
    line = f'<p class="sub">{badges(s["flags"])} '
    if ext:
        line += f'Extends {link_types(ext, known, p)}. '
    line += f'File <code>{esc(s["file"])}</code>.</p>'
    head.append(line)
    if parents or ext:
        names = [s["name"]] + [x["name"] for x in parents]
        if ext and ext.lower() not in scripts:
            names.append(ext)
        head.append('<p class="chain">' + " &rarr; ".join(link_types(n, known, p) if i else f"<b>{esc(n)}</b>"
                                                         for i, n in enumerate(names)) + "</p>")
    kids = sorted(children.get(key, []), key=str.lower)
    if kids:
        head.append(f'<p class="kids">{len(kids)} script{"s" if len(kids) != 1 else ""} extend this one: '
                    + ", ".join(link_types(k, known, p) for k in kids[:60])
                    + (f" and {len(kids) - 60} more (see the Tree page)" if len(kids) > 60 else "") + ".</p>")
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
            more = f"<li>and {len(who) - MAX_CALLERS} more</li>" if len(who) > MAX_CALLERS else ""
            calls = (f'<details><summary>Called from {len(who)} place{"s" if len(who) != 1 else ""}</summary>'
                     f'<ul class="cols">{items}{more}</ul></details>')
        rows.append(f'<tr id="m-{esc(m["name"])}"><td class="kind">{esc(m["kind"])}</td>'
                    f'<td><code>{link_types(m["sig"], known, p)}</code>{badges(flags)}{wiki}{calls}</td>'
                    f'<td class="where">{where}</td></tr>')
    if rows:
        menu.append(("members", "Functions and events"))
        body.append(f'<section id="members"><h2>Functions, events and structs ({len(rows)})</h2>'
                    '<table><thead><tr><th>Kind</th><th>Declaration</th><th>Where</th></tr></thead><tbody>'
                    + "".join(rows) + "</tbody></table></section>")

    if s["props"] or s["custom"] or s["states"]:
        menu.append(("props", "Properties and states"))
        part = ['<section id="props"><h2>Properties, custom events and states</h2>']
        if s["props"]:
            part.append("<table><thead><tr><th>Property</th><th>Type</th><th>Flags</th><th>Where</th></tr></thead><tbody>"
                        + "".join(f'<tr><td><code>{esc(x["name"])}</code></td><td><code>{link_types(x["type"], known, p)}</code></td>'
                                  f'<td>{esc(x["flags"])}</td><td class="where"><a href="#L{x["line"]}">line {x["line"]}</a></td></tr>'
                                  for x in s["props"]) + "</tbody></table>")
        if s["custom"]:
            part.append("<p>Custom events: " + ", ".join(f'<a href="#L{x["line"]}"><code>{esc(x["name"])}</code></a>'
                                                        for x in s["custom"]) + ".</p>")
        if s["states"]:
            part.append("<p>States: " + ", ".join(f'<a href="#L{x["line"]}"><code>{esc(x["name"])}</code></a>'
                                                 + (" (starts here)" if x["auto"] else "") for x in s["states"]) + ".</p>")
        part.append("</section>")
        body.append("".join(part))

    if parents:
        menu.append(("inherited", "Inherited"))
        part = ['<section id="inherited"><h2>Inherited from parent scripts</h2>']
        for par in parents:
            names = [m["name"] for m in par["members"] if m["kind"] in ("function", "event")]
            part.append(f'<details><summary>{esc(par["name"])}: {len(names)} functions and events</summary><p class="cols">'
                        + " ".join(f'<a href="{page_name(par["name"])}#m-{esc(n)}"><code>{esc(n)}</code></a>' for n in names)
                        + "</p></details>")
        part.append("</section>")
        body.append("".join(part))

    menu.append(("source", "Source"))
    src = highlight(s["text"], known, p)
    body.append('<section id="source"><h2>Source</h2><pre class="src">'
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


def home_page(scripts, children, folders, n_members, n_calls, sources, stamp):
    roots = sorted((s for s in scripts.values() if not s["extends"] or s["extends"].lower() not in scripts),
                   key=lambda s: -len(children.get(s["name"].lower(), [])))
    top = sorted(scripts.values(), key=lambda s: -len(children.get(s["name"].lower(), [])))[:24]
    body = [
        "<h1>Papyrus Source</h1>",
        f'<p class="lede">{len(scripts)} scripts with {n_members} functions, events and structs, and {n_calls} '
        "calls linked to the function they reach. Type in the box at the top to find a script, function, event or "
        "property, or browse the A-Z list and the inheritance tree.</p>",
        f'<p class="note">{esc(NOTE)} Read from <code>{esc(sources)}</code>.</p>',
        '<section id="how"><h2>How the site is made</h2>' + DIAGRAM + "</section>",
        '<section id="folders"><h2>Scripts by folder</h2><table><thead><tr><th>Folder</th><th>Scripts</th></tr></thead><tbody>'
        + "".join(f'<tr><td><a href="az.html#f-{esc(re.sub(r"[^A-Za-z0-9_-]", "_", f or "top"))}">{esc(f or "(top level)")}</a></td><td>{n}</td></tr>'
                  for f, n in sorted(folders.items())) + "</tbody></table></section>",
        '<section id="parents"><h2>Most extended scripts</h2><p>The number is how many scripts extend each one '
        'directly.</p><ul class="cols">'
        + "".join(f'<li><a href="s/{page_name(s["name"])}">{esc(s["name"])}</a> '
                  f'<span class="count">{len(children.get(s["name"].lower(), []))}</span></li>'
                  for s in top) + f"</ul><p>{len(roots)} scripts start a family (they extend nothing, or a script "
        "that is not in these sources).</p></section>",
        '<section id="reading"><h2>Reading a script page</h2><p>Each script page lists its functions, events and '
        "structs with their declarations. Flags such as Latent, Non-delayed, DebugOnly and BetaOnly come from the "
        "official Creation Kit wiki list that ships with sf-papyrus-ref, and Native and Global come from the source. "
        "\"Called from\" lists every place another script calls that function, when the caller's type can be worked "
        "out from the source (a call through a chain such as a.b.Name() cannot, so the lists can be short). "
        "Line links jump into the highlighted source at the bottom of the page.</p></section>",
    ]
    menu = [("how", "How the site is made"), ("folders", "Scripts by folder"), ("parents", "Most extended"),
            ("reading", "Reading a page")]
    return frame("Papyrus Source", "", "\n".join(body), menu, stamp)


def az_page(scripts, stamp):
    by_folder = {}
    for s in scripts.values():
        by_folder.setdefault(folder_of(s["file"]), []).append(s["name"])
    menu, body = [], ["<h1>All scripts, A-Z</h1>"]
    for f in sorted(by_folder):
        fid = "f-" + re.sub(r"[^A-Za-z0-9_-]", "_", f or "top")
        menu.append((fid, f or "(top level)"))
        names = sorted(by_folder[f], key=str.lower)
        body.append(f'<section id="{fid}"><h2>{esc(f or "(top level)")} ({len(names)})</h2><p class="cols">'
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
    body = ["<h1>Inheritance tree</h1>",
            "<p>Each script is listed under the script it extends. The number is how many scripts extend it "
            "directly. Click a name to open its page, or the arrow to open its branch.</p>",
            '<section id="families"><h2>Families</h2><ul class="tree">' + "".join(node(r, 0, frozenset()) for r in big)
            + "</ul></section>",
            '<section id="alone"><h2>Scripts that nothing extends and that extend nothing here</h2><p class="cols">'
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


def write(path, text):
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def build(pscread, sources_iter, sources_label, out, official, stamp, log, assets_dir):
    """Write the whole site into out (which must be empty or a site this command built). Returns counts."""
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

    os.makedirs(os.path.join(out, "s"), exist_ok=True)
    os.makedirs(os.path.join(out, "assets"), exist_ok=True)
    for name in ("site.css", "site.js"):
        shutil.copyfile(os.path.join(assets_dir, name), os.path.join(out, "assets", name))
    write(os.path.join(out, "assets", "search-index.js"),
          "window.SFPR_INDEX=" + json.dumps(search_index(scripts), ensure_ascii=False, separators=(",", ":")) + ";\n")
    n_members = sum(len(s["members"]) for s in scripts.values())
    n_calls = sum(len(v) for v in callers.values())
    write(os.path.join(out, "index.html"), home_page(scripts, children, folders, n_members, n_calls, sources_label, stamp))
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
    write(os.path.join(out, ".sf-papyrus-ref-site"), "Built by sf-papyrus-ref html. Safe to rebuild over.\n")
    return {"scripts": len(scripts), "members": n_members, "calls": n_calls, "folders": len(folders),
            "pages": len(pages) + len(wanted)}
