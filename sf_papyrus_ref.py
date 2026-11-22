# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Richard Bejtlich
"""Offline Papyrus reference for Starfield: look up a function or event by name and see its official flags.

  python -I sf_papyrus_ref.py lookup <Name | Script.Name>     where a name lives, its flags, its official page
  python -I sf_papyrus_ref.py script <Script>                 every function and event on one script
  python -I sf_papyrus_ref.py list --flag <flag> [--script X] every entry with a flag
  python -I sf_papyrus_ref.py data                            which wiki revision the shipped list comes from
  python -I sf_papyrus_ref.py build-local [--sources <path>]  read YOUR Creation Kit's script sources into a
                                                               local cache: signatures and parent scripts
  python -I sf_papyrus_ref.py diff                            the official list against your sources
  python -I sf_papyrus_ref.py html [--out <folder>]           a browsable website of YOUR Creation Kit's scripts
                                                               (keep it on your PC or home network)
  python -I sf_papyrus_ref.py compare <files or folders>      .psc files against your Creation Kit's sources:
                                                               identical, changed or not from the CK
  python -I sf_papyrus_ref.py check <files or folders>        BetaOnly, DebugOnly and Latent-in-a-loop calls in
                                                               .psc or .pex scripts

Flags: latent, nondelayed, debugonly, betaonly, invsafe (Latent, Non-delayed, DebugOnly, BetaOnly, Inventory-safe).

Options (after the command): --json (machine-readable output), --quiet (no byline), --verbose (log to stderr),
--log <file> (log to a file), --data <file> (another official-names.json), --cache <file> (the local cache;
default %LOCALAPPDATA%\\sf-papyrus-ref\\local.json, or ~/.cache/sf-papyrus-ref/local.json), --no-local.
check also takes --allow Script.Name (never report it), --creations (DebugOnly is an error) and --strict.

The shipped list holds names, flags and links to the official Creation Kit wiki only. It never guesses: a name
that is not in the list is reported as not found, with near matches. Signatures come only from your own sources.
Exit codes: lookup and script 0 found, 1 not found; list 0 matched, 1 none; check 0 clean, 1 findings;
compare 0 all identical, 1 some changed or not from the CK;
2 bad arguments, an unreadable data file or script, or no sources found.
It only reads files. It writes only the local cache (build-local), the site folder (html) and the --log file.
"""
import argparse
import datetime
import difflib
import importlib.util
import json
import logging
import os
import re
import sys
import zipfile

VERSION = "0.2.0"
AUTHOR = "Richard Bejtlich"
LICENSE = "MIT"
URL = "https://github.com/taosecurity/sf-papyrus-ref"
BYLINE = f"sf-papyrus-ref {VERSION} by {AUTHOR} - {LICENSE} - {URL}"
FLAGS = {"latent": "Latent", "nondelayed": "Non-delayed", "debugonly": "DebugOnly", "betaonly": "BetaOnly",
         "invsafe": "Inventory-safe"}
HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DATA = os.path.join(HERE, "data", "official-names.json")
NOT_FOUND_HINT = ("Not in the official list. It may be a script extender (SFSE) function, a function from "
                  "another mod's script, or a made-up name. The Papyrus compiler is the final judge.")

log = logging.getLogger("sf-papyrus-ref")


def _load(name):
    """A module from this script's folder (python -I leaves that folder off the import path)."""
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


pexread = _load("pexread")
pscread = _load("pscread")
htmlsite = _load("htmlsite")


class DataError(Exception):
    pass


# ------------------------------------------------------------------ the local cache (the user's own sources)

def default_cache():
    base = os.environ.get("LOCALAPPDATA") if os.name == "nt" else None
    base = base or os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache")
    return os.path.join(base, "sf-papyrus-ref", "local.json")


def steam_libraries():
    """Steam library folders that may hold Starfield (the default one plus those in libraryfolders.vdf)."""
    roots = []
    if os.name == "nt":
        for env in ("ProgramFiles(x86)", "ProgramFiles"):
            if os.environ.get(env):
                roots.append(os.path.join(os.environ[env], "Steam"))
    else:
        home = os.path.expanduser("~")
        roots += [os.path.join(home, ".steam", "steam"), os.path.join(home, ".local", "share", "Steam")]
    libs = []
    for root in roots:
        libs.append(root)
        vdf = os.path.join(root, "steamapps", "libraryfolders.vdf")
        try:
            with open(vdf, encoding="utf-8", errors="replace") as f:
                libs += [p.replace("\\\\", "\\") for p in re.findall(r'"path"\s+"([^"]+)"', f.read())]
        except OSError:
            pass
    seen, out = set(), []
    for lib in libs:
        key = os.path.normcase(os.path.abspath(lib))
        if key not in seen:
            seen.add(key)
            out.append(lib)
    return out


def find_sources():
    """Where the Creation Kit's script sources are, or None. Tries Tools\\ContentResources.zip, then an
    extracted Data\\Scripts\\Source that holds the base game's Debug.psc."""
    tried = []
    for lib in steam_libraries():
        game = os.path.join(lib, "steamapps", "common", "Starfield")
        for cand in (os.path.join(game, "Tools", "ContentResources.zip"),
                     os.path.join(game, "Data", "Scripts", "Source")):
            tried.append(cand)
            if cand.endswith(".zip") and os.path.isfile(cand):
                return cand, tried
            if os.path.isfile(os.path.join(cand, "Debug.psc")):
                return cand, tried
    return None, tried


def iter_sources(path, include_fragments=False):
    """(relative name, text) for every .psc in a folder or a zip. Fragments are left out unless asked for."""
    def keep(rel):
        parts = [p.lower() for p in rel.replace("\\", "/").split("/")]
        return rel.lower().endswith(".psc") and (include_fragments or "fragments" not in parts)
    if os.path.isfile(path) and path.lower().endswith(".zip"):
        with zipfile.ZipFile(path) as z:
            for n in sorted(z.namelist()):
                if keep(n):
                    yield n, z.read(n).decode("utf-8-sig", "replace")
        return
    for dirpath, dirs, files in os.walk(path):
        dirs.sort()
        for f in sorted(files):
            full = os.path.join(dirpath, f)
            rel = os.path.relpath(full, path)
            if keep(rel):
                with open(full, encoding="utf-8-sig", errors="replace") as fh:
                    yield rel, fh.read()


def build_cache(path, include_fragments=False):
    scripts = {}
    for rel, text in iter_sources(path, include_fragments):
        d = pscread.read_declarations(text)
        if not d["name"]:
            log.debug("Skipped %s: no Scriptname line", rel)
            continue
        key = d["name"].lower()
        if key in scripts:
            log.debug("Skipped %s: %s was already read from %s", rel, d["name"], scripts[key]["file"])
            continue
        d["file"] = rel.replace("\\", "/")
        scripts[key] = d
    return {"format": 1, "kind": "sf-papyrus-ref local cache",
            "note": "Read from your own Creation Kit script sources. Keep it on this machine; do not share it.",
            "sources": os.path.abspath(path), "built": datetime.datetime.now().isoformat(timespec="seconds"),
            "tool_version": VERSION, "scripts": scripts}


class Local:
    """The per-user cache built by build-local, or an empty stand-in when there is none."""

    def __init__(self, path, use=True):
        self.path, self.scripts, self.doc = path, {}, None
        if not use or not path or not os.path.isfile(path):
            log.debug("No local cache in use (%s)", path)
            return
        try:
            with open(path, encoding="utf-8") as f:
                self.doc = json.load(f)
            self.scripts = self.doc.get("scripts", {})
            log.debug("Read local cache %s: %d scripts from %s", path, len(self.scripts), self.doc.get("sources"))
        except (OSError, ValueError) as e:
            log.warning("Local cache %s could not be read (%s); run build-local again.", path, e)

    def member(self, script, name):
        s = self.scripts.get(script.lower())
        if s:
            for m in s["members"]:
                if m["name"].lower() == name.lower():
                    return m
        return None

    def chain(self, script):
        """The script and its parents, as far as the cache knows them."""
        out, seen = [], set()
        s = script
        while s and s.lower() not in seen:
            seen.add(s.lower())
            out.append(s)
            d = self.scripts.get(s.lower())
            s = d["extends"] if d else ""
        return out


class Ref:
    """The shipped name list, indexed for lookups."""

    def __init__(self, path=DEFAULT_DATA):
        self.path = path
        try:
            with open(path, encoding="utf-8") as f:
                self.doc = json.load(f)
        except FileNotFoundError:
            raise DataError(f"{path} is missing. Reinstall sf-papyrus-ref, or pass --data <official-names.json>.")
        except (OSError, ValueError) as e:
            raise DataError(f"{path} could not be read ({e}). Reinstall sf-papyrus-ref, or pass --data <file>.")
        if self.doc.get("format") != 1 or not isinstance(self.doc.get("entries"), list):
            raise DataError(f"{path} is not an sf-papyrus-ref name list (format 1).")
        self.entries = self.doc["entries"]
        self.scripts = {s.lower(): s for s in self.doc.get("scripts", [])}
        self.by_name = {}
        for e in self.entries:
            self.by_name.setdefault(e["name"].lower(), []).append(e)
        log.debug("Read %d entries on %d scripts from %s (wiki revision %s)", len(self.entries), len(self.scripts),
                  path, self.doc.get("wiki_revision"))

    def script_name(self, name):
        return self.scripts.get(name.lower())

    def lookup(self, query):
        """Entries for 'Name' (any script) or 'Script.Name'. Case does not matter, as in Papyrus."""
        q = query.strip()
        if "." in q:
            script, _, name = q.rpartition(".")
            hits = [e for e in self.by_name.get(name.lower(), []) if e["script"].lower() == script.lower()]
            log.debug("lookup %s: %d match(es) on script %s", q, len(hits), script)
            return hits
        hits = self.by_name.get(q.lower(), [])
        log.debug("lookup %s: %d match(es)", q, len(hits))
        return hits

    def near(self, query, n=5):
        q = query.strip()
        if "." in q:
            script, _, name = q.rpartition(".")
            s = self.script_name(script)
            if s:
                pool = [e["name"] for e in self.entries if e["script"] == s]
                return [f"{s}.{m}" for m in difflib.get_close_matches(name, pool, n=n, cutoff=0.6)]
            q = name
        low = {e["name"].lower(): e["name"] for e in self.entries}
        return [low[m] for m in difflib.get_close_matches(q.lower(), list(low), n=n, cutoff=0.6)]

    def of_script(self, script):
        s = self.script_name(script)
        return s, [e for e in self.entries if e["script"] == s] if s else []

    def with_flag(self, flag, script=None):
        s = self.script_name(script) if script else None
        return [e for e in self.entries if flag in e["flags"] and (not script or e["script"] == s)]


def flag_text(e):
    return ", ".join(FLAGS[f] for f in e["flags"]) or "none"


def meta(ref):
    return {"tool": "sf-papyrus-ref", "version": VERSION, "author": AUTHOR, "license": LICENSE, "url": URL,
            "wiki_revision": ref.doc.get("wiki_revision"), "data_built": ref.doc.get("built")}


def out_json(obj):
    sys.stdout.write(json.dumps(obj, indent=1, ensure_ascii=False) + "\n")


def local_only(local, query):
    """Members found only in the user's own sources (scripts or names the official list does not have)."""
    q = query.strip()
    script, _, name = q.rpartition(".") if "." in q else ("", "", q)
    out = []
    for key, s in local.scripts.items():
        if script and key != script.lower():
            continue
        for m in s["members"]:
            if m["name"].lower() == name.lower():
                out.append({"script": s["name"], "name": m["name"], "kind": m["kind"], "signature": m["sig"],
                            "source_flags": sorted(effective_source_flags(s, m) & {"debugonly", "betaonly"}),
                            "file": s.get("file", "")})
    return out


def inherited(ref, local, query):
    """For Script.Name not on Script itself: (entries on the nearest parent that has it, that parent's name)."""
    if "." not in query:
        return [], ""
    script, _, name = query.strip().rpartition(".")
    for parent in local.chain(script)[1:]:
        hits = ref.lookup(f"{parent}.{name}")
        if hits:
            return hits, parent
        m = local.member(parent, name)
        if m:
            s = local.scripts[parent.lower()]
            return [{"script": s["name"], "name": m["name"], "kind": m["kind"], "flags": [], "wiki": "",
                     "source_flags": sorted(effective_source_flags(s, m) & {"debugonly", "betaonly"})}], parent
    return [], ""


def cmd_lookup(ref, a):
    local = a.local
    hits = [dict(e) for e in ref.lookup(a.name)]
    via = ""
    if not hits:
        found, via = inherited(ref, local, a.name)
        hits = [dict(e, inherited_by=a.name.strip().rpartition(".")[0]) for e in found]
    elsewhere = []
    if not hits and "." in a.name:
        elsewhere = sorted({e["script"] for e in ref.lookup(a.name.strip().rpartition(".")[2])})
    for e in hits:
        m = local.member(e["script"], e["name"])
        if m:
            e["signature"] = m["sig"]
    official = {(e["script"].lower(), e["name"].lower()) for e in hits}
    extra = [x for x in local_only(local, a.name) if (x["script"].lower(), x["name"].lower()) not in official]
    found = bool(hits or extra)
    near = [] if found else ref.near(a.name)
    note = ""
    if not found:
        note = NOT_FOUND_HINT
        if elsewhere:
            note = (f"Not declared on {a.name.strip().rpartition('.')[0]} in the official list, but these scripts "
                    f"have it: {', '.join(elsewhere)}. If the script extends one of them, it inherits it."
                    + ("" if local.doc else " Run build-local so lookups follow parent scripts."))
    if a.json:
        out_json({**meta(ref), "query": a.name, "found": found, "inherited_from": via or None, "matches": hits,
                  "local_only": extra, "on_other_scripts": elsewhere, "near": near,
                  "local_cache": local.path if local.doc else None, "note": note})
        return 0 if found else 1
    if not found:
        print(f"{a.name}: {note}")
        if near and not elsewhere:
            print("Did you mean: " + ", ".join(near))
        return 1
    if via:
        print(f"{a.name} is inherited from {via}:")
    for e in hits:
        print(f"{e['script']}.{e['name']}  ({e['kind']})")
        if e.get("signature"):
            print(f"  Signature (your sources): {e['signature']}")
        if e.get("wiki"):
            print(f"  Flags: {flag_text(e)}")
            print(f"  Official page: {e['wiki']}")
        else:
            print("  Not on the official list; found in your sources"
                  + (f" (marked {', '.join(FLAGS[f] for f in e['source_flags'])})" if e.get("source_flags") else ""))
    for x in extra:
        print(f"{x['script']}.{x['name']}  ({x['kind']}, in your sources only: {x['file']})")
        print(f"  Signature (your sources): {x['signature']}")
    if hits and not local.doc:
        print("Run 'sf-papyrus-ref build-local' once to see signatures from your own Creation Kit sources.")
    if len(hits) > 1:
        print(f"{len(hits)} scripts have a {hits[0]['kind'] if len({h['kind'] for h in hits}) == 1 else 'member'} "
              f"named {hits[0]['name']}; use Script.Name to pick one.")
    return 0


def cmd_script(ref, a):
    s, items = ref.of_script(a.script)
    ls = a.local.scripts.get(a.script.lower())
    if not s and ls:
        if a.json:
            out_json({**meta(ref), "script": ls["name"], "found": True, "official": False, "extends": ls["extends"],
                      "file": ls.get("file"), "entries": ls["members"]})
            return 0
        print(f"{ls['name']} (in your sources only: {ls.get('file')})"
              + (f", extends {ls['extends']}" if ls["extends"] else ""))
        for m in ls["members"]:
            print(f"  {m['sig']}")
        return 0
    if s and ls:
        items = [dict(e, signature=(a.local.member(s, e["name"]) or {}).get("sig", "")) for e in items]
    if a.json:
        out_json({**meta(ref), "script": s or a.script, "found": bool(s), "entries": items,
                  "near": [] if s else difflib.get_close_matches(a.script, list(ref.scripts.values()), n=5)})
        return 0 if s else 1
    if not s:
        near = difflib.get_close_matches(a.script, list(ref.scripts.values()), n=5)
        print(f"{a.script}: no script by that name in the official list."
              + (" Did you mean: " + ", ".join(near) if near else ""))
        return 1
    if not items:
        print(f"{s}: the official wiki has a page for this script but lists no functions or events on it.")
        return 0
    for kind, head in (("function", "Functions"), ("event", "Events"), ("struct", "Structs")):
        group = [e for e in items if e["kind"] == kind]
        if group:
            print(f"{s} - {head} ({len(group)})")
            for e in group:
                print(f"  {e.get('signature') or e['name']}" + (f"  [{flag_text(e)}]" if e["flags"] else ""))
    if ls and ls["extends"]:
        print(f"{s} extends {ls['extends']} (from your sources).")
    return 0


def cmd_list(ref, a):
    if a.script and not ref.script_name(a.script):
        print(f"{a.script}: no script by that name in the official list.", file=sys.stderr)
        return 2
    items = ref.with_flag(a.flag, a.script)
    if a.json:
        out_json({**meta(ref), "flag": a.flag, "script": a.script, "count": len(items), "entries": items})
    else:
        for e in items:
            print(f"{e['script']}.{e['name']}  ({e['kind']})")
        print(f"{len(items)} entries flagged {FLAGS[a.flag]}" + (f" on {ref.script_name(a.script)}" if a.script else "")
              + ".")
    return 0 if items else 1


def cmd_data(ref, a):
    d = ref.doc
    if a.json:
        out_json({**meta(ref), "file": ref.path, "counts": d.get("counts"), "source": d.get("source")})
        return 0
    c = d.get("counts", {})
    print(f"Data file: {ref.path}")
    print(f"Official wiki revision {d.get('wiki_revision')}, list built {d.get('built')}.")
    print(f"{c.get('scripts')} scripts, {c.get('functions')} functions, {c.get('events')} events, "
          f"{c.get('structs', 0)} structs.")
    print("Flags: " + ", ".join(f"{FLAGS[f]} {c.get(f)}" for f in FLAGS))
    print(d.get("source", ""))
    return 0


def cmd_build_local(ref, a):
    path = a.sources
    if not path:
        path, tried = find_sources()
        if not path:
            print("Error: no Creation Kit script sources found. Looked in:\n  " + "\n  ".join(tried)
                  + "\nInstall the Creation Kit from Steam, or pass --sources <folder or ContentResources.zip>.",
                  file=sys.stderr)
            return 2
    if not os.path.exists(path):
        print(f"Error: {path} does not exist. Pass --sources <folder or ContentResources.zip>.", file=sys.stderr)
        return 2
    log.info("Reading script sources from %s", path)
    try:
        doc = build_cache(path, a.include_fragments)
    except (OSError, zipfile.BadZipFile) as e:
        print(f"Error: could not read {path} ({e}).", file=sys.stderr)
        return 2
    if not doc["scripts"]:
        print(f"Error: no .psc scripts in {path}. Pass the folder that holds Debug.psc, or ContentResources.zip.",
              file=sys.stderr)
        return 2
    tmp = a.cache + ".tmp"
    try:
        os.makedirs(os.path.dirname(os.path.abspath(a.cache)), exist_ok=True)
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            json.dump(doc, f, ensure_ascii=False)
        os.replace(tmp, a.cache)
    except OSError as e:
        print(f"Error: could not write the local cache {a.cache} ({e.strerror or e}). "
              "Pass --cache <a file in a folder you can write to>.", file=sys.stderr)
        return 2
    n_members = sum(len(s["members"]) for s in doc["scripts"].values())
    official = sum(1 for s in ref.scripts if s in doc["scripts"])
    if a.json:
        out_json({**meta(ref), "cache": a.cache, "sources": doc["sources"], "scripts": len(doc["scripts"]),
                  "members": n_members, "official_scripts_found": official})
    else:
        print(f"Read {len(doc['scripts'])} scripts ({n_members} functions, events and structs) from {path}.")
        print(f"{official} of the {len(ref.scripts)} scripts on the official list are among them.")
        print(f"Saved the local cache to {a.cache} (it stays on this machine; never share it).")
    return 0


def effective_source_flags(s, m):
    return set(m["flags"]) | ({"debugonly", "betaonly"} & set(s["flags"]))


def cmd_diff(ref, a):
    local = a.local
    if not local.doc:
        print(f"Error: no local cache at {local.path}. Run 'sf-papyrus-ref build-local' first.", file=sys.stderr)
        return 2
    missing_scripts = sorted(name for low, name in ref.scripts.items() if low not in local.scripts)
    only_wiki, only_src, flag_diffs = [], [], []
    for low, sname in sorted(ref.scripts.items()):
        s = local.scripts.get(low)
        if not s:
            continue
        wiki = {e["name"].lower(): e for e in ref.entries if e["script"] == sname}
        src = {m["name"].lower(): m for m in s["members"]}
        only_wiki += [f"{sname}.{wiki[k]['name']}" for k in sorted(wiki.keys() - src.keys())]
        only_src += [f"{sname}.{src[k]['name']}" for k in sorted(src.keys() - wiki.keys())]
        for k in sorted(wiki.keys() & src.keys()):
            wf = set(wiki[k]["flags"]) & {"debugonly", "betaonly"}
            sf = effective_source_flags(s, src[k]) & {"debugonly", "betaonly"}
            if wf != sf:
                flag_diffs.append({"name": f"{sname}.{wiki[k]['name']}", "wiki": sorted(wf), "sources": sorted(sf)})
    counts = {}
    for f in ("debugonly", "betaonly"):
        counts[f] = {"wiki": sum(f in e["flags"] for e in ref.entries),
                     "sources_keyword": sum(f in m["flags"] for low in ref.scripts if low in local.scripts
                                            for m in local.scripts[low]["members"]),
                     "sources_with_script_flag": sum(f in effective_source_flags(local.scripts[low], m)
                                                     for low in ref.scripts if low in local.scripts
                                                     for m in local.scripts[low]["members"])}
    if a.json:
        out_json({**meta(ref), "cache": local.path, "scripts_missing_from_sources": missing_scripts,
                  "only_on_wiki": only_wiki, "only_in_sources": only_src, "flag_differences": flag_diffs,
                  "flag_counts": counts})
        return 0
    print(f"Official list (wiki revision {ref.doc.get('wiki_revision')}) against your sources ({local.doc.get('sources')}).")
    print(f"Scripts on the official list but not in your sources: {len(missing_scripts)}"
          + (": " + ", ".join(missing_scripts) if missing_scripts else ""))
    for title, items in (("Names on the wiki but not in your sources", only_wiki),
                         ("Names in your sources but not on the wiki", only_src)):
        print(f"{title}: {len(items)}")
        for x in items if a.all else items[:40]:
            print(f"  {x}")
        if not a.all and len(items) > 40:
            print(f"  ... {len(items) - 40} more (use --all or --json)")
    print(f"DebugOnly or BetaOnly marked differently: {len(flag_diffs)}")
    for d in flag_diffs:
        print(f"  {d['name']}: wiki {', '.join(d['wiki']) or 'none'}; sources {', '.join(d['sources']) or 'none'}")
    for f, c in counts.items():
        print(f"{FLAGS[f]}: wiki {c['wiki']}; sources {c['sources_keyword']} by the function keyword, "
              f"{c['sources_with_script_flag']} counting a script-wide {FLAGS[f]}.")
    return 0


# ------------------------------------------------------------------ html and compare (read the sources themselves)

SITE_MARK = ".sf-papyrus-ref-site"
# The whole name, then a space or the line's end: odd text after it must not turn a named script into a
# file-name match, and a broken name (Foo.Bar, Foo:) must not match a shorter one.
SCRIPTNAME_START = re.compile(rf"(?i)^\s*scriptname\s+((?:{pscread.IDENT}:)*{pscread.IDENT})(?=\s|$)")


def script_name(text):
    """The name on the script's Scriptname line, ignoring comments (so a commented-out line never counts)."""
    for _, line in pscread.clean(text):
        m = SCRIPTNAME_START.match(line)
        if m:
            return m.group(1)
        if re.match(r"(?i)^\s*scriptname\s+[^\s=]", line):
            return UNREADABLE  # a Scriptname line that can't be read: never match it by file name
    return ""


UNREADABLE = "?"


def default_site():
    return os.path.join(os.path.dirname(default_cache()), "site")


def sources_or_error(given):
    """(path, None) or (None, exit code) after printing the reason."""
    path = given
    if not path:
        path, tried = find_sources()
        if not path:
            print("Error: no Creation Kit script sources found. Looked in:\n  " + "\n  ".join(tried)
                  + "\nInstall the Creation Kit from Steam, or pass --sources <folder or ContentResources.zip>.",
                  file=sys.stderr)
            return None, 2
    if not os.path.exists(path):
        print(f"Error: {path} does not exist. Pass --sources <folder or ContentResources.zip>.", file=sys.stderr)
        return None, 2
    return path, None


def cmd_html(ref, a):
    path, code = sources_or_error(a.sources)
    if not path:
        return code
    out = os.path.abspath(a.out)
    if os.path.isdir(out) and os.listdir(out) and not os.path.isfile(os.path.join(out, SITE_MARK)):
        print(f"Error: {out} already holds files that this command did not write. Pass --out <an empty or new "
              "folder>, so nothing of yours is overwritten.", file=sys.stderr)
        return 2
    official = {(e["script"].lower(), e["name"].lower()): e for e in ref.entries}
    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    log.info("Reading script sources from %s (fragments %s)", path, "included" if a.include_fragments else "left out")
    try:
        os.makedirs(out, exist_ok=True)
        counts = htmlsite.build(pscread, iter_sources(path, a.include_fragments), path, out, official, stamp, log,
                                os.path.join(HERE, "site-assets"))
    except (OSError, zipfile.BadZipFile) as e:
        print(f"Error: could not build the site ({e}). Check that {path} is readable and that you can write to "
              f"{out}, or pass --out <another folder>.", file=sys.stderr)
        return 2
    if not counts:
        print(f"Error: no .psc scripts in {path}. Pass the folder that holds Debug.psc, or ContentResources.zip.",
              file=sys.stderr)
        return 2
    index = os.path.join(out, "index.html")
    if a.json:
        out_json({**meta(ref), "sources": os.path.abspath(path), "out": out, "index": index, **counts})
    else:
        print(f"Read {counts['scripts']} scripts ({counts['members']} functions, events and structs) from {path}.")
        print(f"Linked {counts['calls']} calls to the function they reach.")
        print(f"Wrote {counts['pages']} pages to {out}. Open {index} in your browser.")
        print("These pages hold Bethesda's script text from your own install: keep them on your PC or home network, "
              "and never publish them.")
    return 0


def normalized(text):
    lines = [x.rstrip() for x in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    while lines and not lines[-1]:
        lines.pop()
    return lines


def iter_given(paths, errors):
    """(shown path, text) for every .psc under the given files, folders and zips."""
    for p in paths:
        if not os.path.exists(p):
            errors.append(f"{p}: not found")
        elif os.path.isfile(p) and not p.lower().endswith(".zip"):
            if not p.lower().endswith(".psc"):
                errors.append(f"{p}: not a .psc source file (compare reads Papyrus sources; compiled .pex files "
                              "can't be compared)")
                continue
            try:
                with open(p, encoding="utf-8-sig", errors="replace") as f:
                    yield p, f.read()
            except OSError as e:
                errors.append(f"{p}: could not be read ({e.strerror or e})")
        else:
            try:
                for rel, text in iter_sources(p, include_fragments=True):
                    yield os.path.join(p, rel), text
            except (OSError, zipfile.BadZipFile) as e:
                errors.append(f"{p}: could not be read ({e})")


def cmd_compare(ref, a):
    path, code = sources_or_error(a.sources)
    if not path:
        return code
    by_name, by_file = {}, {}
    try:
        for rel, text in iter_sources(path, include_fragments=True):
            name = script_name(text)
            entry = (rel.replace("\\", "/"), text)
            if name == UNREADABLE:
                continue  # never matched, by name or by file name
            if name:
                by_name.setdefault(name.lower(), entry)
            base = os.path.basename(rel.replace("\\", "/")).lower()
            by_file[base] = None if base in by_file else entry  # a file name used twice matches nothing
    except (OSError, zipfile.BadZipFile) as e:
        print(f"Error: could not read the sources {path} ({e}).", file=sys.stderr)
        return 2
    log.info("Read %d Creation Kit scripts from %s", len(by_name), path)
    errors, results = [], []
    for shown, text in iter_given(a.paths, errors):
        name = script_name(text)
        # The file name is used only when the file has no Scriptname line: a mod's own script that shares a
        # file name with one of Bethesda's is not a copy of it.
        unreadable = name == UNREADABLE
        if unreadable:
            name, ck = "", None
        else:
            ck = by_name.get(name.lower()) if name else by_file.get(os.path.basename(shown).lower())
        r = {"file": shown, "script": name, "ck_file": ck[0] if ck else ""}
        if unreadable:
            r["note"] = "the Scriptname line could not be read"
        if not ck:
            r["status"] = "not-in-ck"
        else:
            mine, theirs = normalized(text), normalized(ck[1])
            if mine == theirs:
                r["status"] = "identical"
            else:
                diff = list(difflib.unified_diff(theirs, mine, lineterm="", n=0))
                r["status"] = "changed"
                r["lines_added"] = sum(1 for x in diff if x.startswith("+") and not x.startswith("+++"))
                r["lines_removed"] = sum(1 for x in diff if x.startswith("-") and not x.startswith("---"))
        log.debug("%s: %s (%s)", shown, r["status"], r["ck_file"] or "no match")
        results.append(r)
    counts = {k: sum(r["status"] == k for r in results) for k in ("identical", "changed", "not-in-ck")}
    if a.json:
        out_json({**meta(ref), "sources": os.path.abspath(path), "files": len(results), "counts": counts,
                  "results": results, "errors": errors})
    else:
        for r in results:
            if r["status"] == "changed":
                print(f"changed    {r['file']}  (+{r['lines_added']} -{r['lines_removed']} lines against {r['ck_file']})")
            elif r["status"] == "not-in-ck":
                why = f"  (Scriptname {r['script']})" if r["script"] else f"  ({r['note']})" if r.get("note") else ""
                print(f"not in CK  {r['file']}{why}")
            elif a.all:
                print(f"identical  {r['file']}")
        for e in errors:
            print(f"Error: {e}", file=sys.stderr)
        if results:
            print(f"Compared {len(results)} scripts with {path}: {counts['identical']} identical, "
                  f"{counts['changed']} changed, {counts['not-in-ck']} not from the Creation Kit"
                  + (f"; {len(errors)} paths could not be read" if errors else "") + ".")
    if errors or not results:
        if not results and not errors:
            print("Error: no .psc files in the given paths.", file=sys.stderr)
        return 2
    return 0 if counts["identical"] == len(results) else 1


# ------------------------------------------------------------------ check

RULES = {
    "betaonly": ("error", "is BetaOnly: it is meant for beta builds and should never ship"),
    "debugonly": ("warning", "is DebugOnly: it does nothing in release builds on Xbox and PlayStation"),
    "latent-loop": ("warning", "is Latent and is called inside a loop: each pass waits for it to finish"),
}


class Checker:
    def __init__(self, ref, local, allow=(), creations=False, strict=False):
        self.ref, self.local = ref, local
        self.allow = {x.strip().lower() for x in allow if x.strip()}
        self.creations, self.strict = creations, strict

    def known_script(self, name):
        return bool(self.ref.script_name(name)) or name.lower() in self.local.scripts

    def flags_on(self, script, name):
        """(flags, exists) for script.name from the official list and the local cache."""
        flags, exists = set(), False
        for e in self.ref.by_name.get(name.lower(), []):
            if e["script"].lower() == script.lower():
                flags |= set(e["flags"])
                exists = True
        s = self.local.scripts.get(script.lower())
        if s:
            m = self.local.member(script, name)
            if m:
                flags |= effective_source_flags(s, m)
                exists = True
        return flags, exists

    def resolve(self, chain, name):
        """[(script, flags, confidence)] for a call to name on an object whose type chain is given.
        An empty chain means the type is not known: every official script with that name is a candidate."""
        for s in chain:
            flags, exists = self.flags_on(s, name)
            if exists:
                return [(self.ref.script_name(s) or s, flags, "exact")]
        if chain and any(s.lower() in self.local.scripts for s in chain):
            return []  # the type is known from the user's sources and has no such member (another mod, SFSE)
        return [(e["script"], set(e["flags"]), "name only") for e in self.ref.by_name.get(name.lower(), [])]

    def resolve_bare(self, chain, imports, name):
        """A call written without an object: the script's own chain first, then each imported script."""
        for s in chain:
            flags, exists = self.flags_on(s, name)
            if exists:
                return [(self.ref.script_name(s) or s, flags, "exact")]
        for s in imports:
            flags, exists = self.flags_on(s, name)
            if exists:
                return [(self.ref.script_name(s) or s, flags, "exact")]
        if chain and any(s.lower() in self.local.scripts for s in chain) and not imports:
            return []
        return [(e["script"], set(e["flags"]), "name only") for e in self.ref.by_name.get(name.lower(), [])]

    def chain_of(self, type_name, own=None):
        """Type chain for a type name; own = (name, extends) of the script being checked."""
        t = (type_name or "").rstrip("[]").strip()
        if not t:
            return []
        if own and t.lower() == own[0].lower():
            return [own[0]] + (self.local.chain(own[1]) if own[1] else [])
        return self.local.chain(t)

    def judge(self, where, line, name, cands, in_loop):
        out = []
        if not cands:
            return out
        exact = cands[0][2] == "exact"
        spelled = {e["name"].lower(): e["name"] for e in self.ref.by_name.get(name.lower(), [])}
        name = spelled.get(name.lower(), name)  # .pex files keep the caller's spelling; show the official one
        labels = [f"{c[0]}.{name}" for c in cands]
        if any(lbl.lower() in self.allow for lbl in labels):
            log.debug("%s:%s: %s allowed", where, line, labels[0])
            return out
        for rule, flag in (("betaonly", "betaonly"), ("debugonly", "debugonly"), ("latent-loop", "latent")):
            if rule == "latent-loop" and not in_loop:
                continue
            has = [c for c in cands if flag in c[1]]
            if not has:
                continue
            if not exact and len(has) < len(cands) and not self.strict:
                log.debug("%s:%s: %s skipped (only %d of %d scripts with that name are %s; --strict reports it)",
                          where, line, name, len(has), len(cands), flag)
                continue
            sev, text = RULES[rule]
            if rule == "debugonly" and self.creations:
                sev = "error"
            call = labels[0] if exact else " or ".join(f"{c[0]}.{name}" for c in has)
            conf = "exact" if exact else ("name only" if len(has) == len(cands) else "name only, some")
            out.append({"file": where, "line": line, "call": call, "rule": rule, "severity": sev,
                        "confidence": conf, "message": f"{call} {text}"})
        return out

    def check_psc(self, path, text):
        info = pscread.read_calls(text)
        own = (info["name"] or os.path.splitext(os.path.basename(path))[0], info["extends"])
        findings = []
        for c in info["calls"]:
            kind, val = c["target"]
            if kind == "self" and c["target"] == ("self", "") and c["name"].lower() not in info["own"]:
                # A bare Name(...) is this script's or a parent's function, or a global from an Import line.
                cands = self.resolve_bare(self.chain_of(own[0], own), info["imports"], c["name"])
                findings += self.judge(path, c["line"], c["name"], cands, c["loop"])
                continue
            if kind == "self":
                if c["name"].lower() in info["own"]:
                    continue
                chain = self.chain_of(own[0], own)
            elif kind == "parent":
                chain = self.local.chain(own[1]) if own[1] else []
            elif kind == "cast":
                chain = self.chain_of(val, own)
            elif kind == "var":
                base = val.rstrip("[]")
                if base.lower() in c["types"]:
                    t = c["types"][base.lower()]
                    chain = self.chain_of(t.rstrip("[]") if val.endswith("[]") else t, own)
                elif self.known_script(base) or base.lower() == own[0].lower():
                    chain = self.chain_of(base, own)
                else:
                    log.debug("%s:%d: type of %s not known; matching %s by name", path, c["line"], base, c["name"])
                    chain = []
            else:
                chain = []
            findings += self.judge(path, c["line"], c["name"], self.resolve(chain, c["name"]), c["loop"])
        return findings

    def check_pex(self, path, data):
        pex = pexread.read_pex(data, path)
        findings = []
        for obj in pex["objects"]:
            own = (obj["name"], obj["extends"])
            own_fns = {f["name"].lower() for f in obj["functions"]}
            for fn in obj["functions"]:
                types = {k.lower(): v for k, v in list(obj["properties"].items()) + list(obj["variables"].items())}
                types.update({n.lower(): t for n, t in fn["params"] + fn["locals"]})
                loops = []
                for i, (op, args) in enumerate(fn["code"]):
                    off = args[0][1] if op == "jmp" else args[1][1] if op in ("jmpt", "jmpf") else None
                    if isinstance(off, int) and off < 0:
                        loops.append((i + off, i))
                dname, dtype = fn["debug"]
                lines = pex["lines"].get((obj["name"].lower(), fn["state"].lower(), dname.lower(), dtype), [])
                for i, (op, args) in enumerate(fn["code"]):
                    if op not in ("callmethod", "callstatic", "callparent"):
                        continue
                    if op == "callstatic":
                        name, chain = args[1][1], self.chain_of(args[0][1], own)
                    elif op == "callparent":
                        name, chain = args[0][1], self.local.chain(own[1]) if own[1] else []
                    else:
                        name, target = args[0][1], args[1]
                        if target[0] == "ident" and target[1].lower() == "self":
                            if name.lower() in own_fns:
                                continue
                            chain = self.chain_of(own[0], own)
                        elif target[0] == "ident" and target[1].lower() in types:
                            chain = self.chain_of(types[target[1].lower()], own)
                        else:
                            chain = []
                    line = lines[i] if i < len(lines) else 0
                    where_line = line or f"{fn['name']}#{i}"
                    in_loop = any(a <= i <= b for a, b in loops)
                    findings += self.judge(path, where_line, name, self.resolve(chain, name), in_loop)
        return findings

    def check_path(self, path):
        """(findings, errors) for one file or a folder (searched below it) of .psc and .pex files."""
        files = []
        if os.path.isdir(path):
            for dirpath, dirs, names in os.walk(path):
                dirs.sort()
                files += [os.path.join(dirpath, n) for n in sorted(names) if n.lower().endswith((".psc", ".pex"))]
        else:
            files = [path]
        findings, errors = [], []
        for f in files:
            log.debug("Checking %s", f)
            try:
                if f.lower().endswith(".pex"):
                    with open(f, "rb") as fh:
                        findings += self.check_pex(f, fh.read())
                elif f.lower().endswith(".psc"):
                    with open(f, encoding="utf-8-sig", errors="replace") as fh:
                        findings += self.check_psc(f, fh.read())
                else:
                    errors.append(f"{f}: not a .psc or .pex file")
            except (OSError, pexread.PexError) as e:
                errors.append(str(e) if isinstance(e, pexread.PexError) else f"{f}: {e.strerror or e}")
        return findings, errors, len(files)


def cmd_check(ref, a):
    allow = [x for item in (a.allow or []) for x in item.split(",")]
    ch = Checker(ref, a.local, allow, a.creations, a.strict)
    findings, errors, n = [], [], 0
    for p in a.paths:
        if not os.path.exists(p):
            errors.append(f"{p}: not found")
            continue
        f, e, k = ch.check_path(p)
        findings += f
        errors += e
        n += k
    if a.json:
        out_json({**meta(ref), "files": n, "local_cache": a.local.path if a.local.doc else None,
                  "findings": findings, "errors": errors})
    else:
        for x in findings:
            low = "" if x["confidence"] == "exact" else f" [{x['confidence']}]"
            print(f"{x['file']}:{x['line']}: {x['severity']}: {x['message']}{low}")
        for e in errors:
            print(f"Error: {e}", file=sys.stderr)
        errs = sum(x["severity"] == "error" for x in findings)
        print(f"Checked {n} files: {errs} errors, {len(findings) - errs} warnings"
              + (f", {len(errors)} files could not be read" if errors else "") + ".")
        if not a.local.doc:
            print("Tip: run 'sf-papyrus-ref build-local' once so calls on inherited functions are matched exactly.")
    if errors:
        return 2
    return 1 if findings else 0


# ------------------------------------------------------------------ MCP server (stdio, read-only)

MCP_VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")
MCP_TOOLS = [
    {"name": "papyrus_lookup",
     "description": "Look up a Starfield Papyrus function, event or struct by name (Name or Script.Name). Returns "
                    "the script it is on, its official flags (Latent, Non-delayed, DebugOnly, BetaOnly, "
                    "Inventory-safe), a link to the official Creation Kit wiki page, and the signature when the "
                    "user has run build-local. found=false means the name is not in the official list: do not "
                    "use it unless it comes from a script you can read.",
     "inputSchema": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}},
    {"name": "papyrus_script",
     "description": "List every function, event and struct on one Starfield Papyrus script, with flags.",
     "inputSchema": {"type": "object", "properties": {"script": {"type": "string"}}, "required": ["script"]}},
    {"name": "papyrus_list_flag",
     "description": "List every Starfield Papyrus function or event with one official flag, optionally on one script.",
     "inputSchema": {"type": "object", "properties": {
         "flag": {"type": "string", "enum": list(FLAGS)}, "script": {"type": "string"}}, "required": ["flag"]}},
    {"name": "papyrus_check",
     "description": "Check .psc or .pex files (or folders) for BetaOnly calls (errors), DebugOnly calls "
                    "(warnings; errors when creations=true, for console players) and Latent calls inside loops. "
                    "Read-only.",
     "inputSchema": {"type": "object", "properties": {
         "paths": {"type": "array", "items": {"type": "string"}, "minItems": 1},
         "allow": {"type": "array", "items": {"type": "string"},
                   "description": "Script.Name calls never reported, for example Debug.Trace"},
         "creations": {"type": "boolean"}}, "required": ["paths"]}},
]


def mcp_call(ref, base, name, args):
    """Run one tool through the same code as the --json commands. Returns (result object, is_error)."""
    import io
    ns = argparse.Namespace(**vars(base))
    ns.json = True
    if name == "papyrus_lookup":
        ns.name, fn = str(args["name"]), cmd_lookup
    elif name == "papyrus_script":
        ns.script, fn = str(args["script"]), cmd_script
    elif name == "papyrus_list_flag":
        if args.get("flag") not in FLAGS:
            return {"error": f"flag must be one of {', '.join(FLAGS)}"}, True
        ns.flag, ns.script, fn = args["flag"], args.get("script"), cmd_list
    elif name == "papyrus_check":
        paths = args.get("paths")
        if not isinstance(paths, list) or not paths:
            return {"error": "paths must be a list of .psc or .pex files or folders"}, True
        allow = args.get("allow") or []
        if isinstance(allow, str):
            allow = [allow]
        if not isinstance(allow, list):
            return {"error": "allow must be a list of Script.Name strings"}, True
        ns.paths, ns.allow = [str(p) for p in paths], [str(x) for x in allow]
        ns.creations, ns.strict, fn = bool(args.get("creations")), False, cmd_check
    else:
        return {"error": f"unknown tool {name}"}, True
    buf, err = io.StringIO(), io.StringIO()
    old_out, old_err = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = buf, err
    try:
        code = fn(ref, ns)
    finally:
        sys.stdout, sys.stderr = old_out, old_err
    text = buf.getvalue().strip()
    try:
        result = json.loads(text) if text else {}
    except ValueError:
        result = {"output": text}
    if err.getvalue().strip():
        result["messages"] = err.getvalue().strip().splitlines()
    result["exit_code"] = code
    return result, code == 2


def mcp_reply(msg_id, result=None, error=None):
    out = {"jsonrpc": "2.0", "id": msg_id}
    if error is not None:
        out["error"] = error
    else:
        out["result"] = result
    sys.stdout.write(json.dumps(out, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def cmd_mcp(ref, a):
    """A Model Context Protocol server on stdin and stdout: one JSON-RPC message per line."""
    log.info("MCP server ready (data %s, local cache %s)", ref.path, a.local.path if a.local.doc else "none")
    for stream in (sys.stdin, sys.stdout):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", newline="\n")  # MCP messages are UTF-8 on every OS
    for raw in sys.stdin:
        raw = raw.strip()
        if not raw:
            continue
        try:
            msg = json.loads(raw)
        except ValueError:
            mcp_reply(None, error={"code": -32700, "message": "Parse error"})
            continue
        if not isinstance(msg, dict):
            mcp_reply(None, error={"code": -32600, "message": "Invalid request"})
            continue
        method, msg_id, params = msg.get("method"), msg.get("id"), msg.get("params")
        if params is None:
            params = {}
        log.debug("MCP %s %s", method, json.dumps(params)[:300])
        if msg_id is None:
            continue  # a notification, such as notifications/initialized
        if not isinstance(params, dict):
            mcp_reply(msg_id, error={"code": -32602, "message": "params must be an object"})
            continue
        try:
            mcp_handle(ref, a, method, msg_id, params)
        except Exception as e:  # one bad request must never stop the server
            log.error("MCP request %s failed: %r", method, e)
            mcp_reply(msg_id, error={"code": -32603, "message": f"Internal error: {e}"})
    return 0


def mcp_handle(ref, a, method, msg_id, params):
    """Answer one MCP request that has an id."""
    if method == "initialize":
        asked = params.get("protocolVersion")
        mcp_reply(msg_id, {"protocolVersion": asked if asked in MCP_VERSIONS else MCP_VERSIONS[0],
                           "capabilities": {"tools": {}},
                           "serverInfo": {"name": "sf-papyrus-ref", "version": VERSION},
                           "instructions": "Offline Starfield Papyrus reference. Look a name up before using "
                                           "it; a name that is not found is not in the official list."})
    elif method == "ping":
        mcp_reply(msg_id, {})
    elif method == "tools/list":
        mcp_reply(msg_id, {"tools": MCP_TOOLS})
    elif method == "tools/call":
        name, args = params.get("name"), params.get("arguments") or {}
        if not isinstance(args, dict):
            mcp_reply(msg_id, error={"code": -32602, "message": "arguments must be an object"})
            return
        try:
            result, is_error = mcp_call(ref, a, name, args)
        except (KeyError, TypeError) as e:
            result, is_error = {"error": f"missing or bad argument: {e}"}, True
        mcp_reply(msg_id, {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}],
                           "structuredContent": result, "isError": is_error})
    else:
        mcp_reply(msg_id, error={"code": -32601, "message": f"Method not found: {method}"})


def setup_logging(a):
    """Warnings always reach stderr; --verbose adds the details; --log writes everything to a file.
    Returns an error message when the log file can't be opened."""
    for h in list(log.handlers):
        log.removeHandler(h)
        h.close()
    log.setLevel(logging.DEBUG)
    log.propagate = False
    fmt = logging.Formatter("%(levelname)s %(message)s")
    console = logging.StreamHandler(sys.stderr)
    console.setLevel(logging.DEBUG if a.verbose else logging.WARNING)
    console.setFormatter(fmt)
    log.addHandler(console)
    if a.log:
        try:
            fh = logging.FileHandler(a.log, mode="w", encoding="utf-8")
        except OSError as e:
            return (f"could not open the log file {a.log} ({e.strerror or e}). "
                    "Pass --log <a file in a folder you can write to>.")
        fh.setFormatter(fmt)
        log.addHandler(fh)
    return None


def parser():
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", help="machine-readable output")
    common.add_argument("--quiet", action="store_true", help="leave out the byline on stderr")
    common.add_argument("--verbose", action="store_true", help="log what was read and decided to stderr")
    common.add_argument("--log", help="also write the log to this file")
    common.add_argument("--data", default=DEFAULT_DATA, help="the name list to read (default: the shipped one)")
    common.add_argument("--cache", default=default_cache(),
                        help="the local cache from build-local (default: %(default)s)")
    common.add_argument("--no-local", action="store_true", help="ignore the local cache")
    ap = argparse.ArgumentParser(prog="sf-papyrus-ref", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", action="store_true", help="show the version and credits")
    sub = ap.add_subparsers(dest="cmd")
    p = sub.add_parser("lookup", parents=[common], help="find a function or event by name")
    p.add_argument("name", help="Name or Script.Name, for example Notification or Debug.Notification")
    p = sub.add_parser("script", parents=[common], help="list one script's functions and events")
    p.add_argument("script")
    p = sub.add_parser("list", parents=[common], help="list every entry with a flag")
    p.add_argument("--flag", required=True, choices=list(FLAGS))
    p.add_argument("--script", help="only this script")
    sub.add_parser("data", parents=[common], help="show where the shipped list comes from")
    p = sub.add_parser("build-local", parents=[common],
                       help="read your own Creation Kit script sources into a local cache (signatures, parents)")
    p.add_argument("--sources", help="a folder of .psc files or the CK's ContentResources.zip (default: found)")
    p.add_argument("--include-fragments", action="store_true", help="also read Fragments scripts")
    p = sub.add_parser("diff", parents=[common], help="compare the official list with your local sources")
    p.add_argument("--all", action="store_true", help="print every name, not the first 40 of each list")
    p = sub.add_parser("html", parents=[common],
                       help="build a browsable offline website from your own Creation Kit script sources")
    p.add_argument("--sources", help="a folder of .psc files or the CK's ContentResources.zip (default: found)")
    p.add_argument("--out", default=default_site(), help="the folder to write the site to (default: %(default)s)")
    p.add_argument("--include-fragments", action="store_true", help="also add the Fragments scripts")
    p = sub.add_parser("compare", parents=[common],
                       help="compare .psc files with your Creation Kit sources: identical, changed or not from the CK")
    p.add_argument("paths", nargs="+", help=".psc files, folders or zips")
    p.add_argument("--sources", help="a folder of .psc files or the CK's ContentResources.zip (default: found)")
    p.add_argument("--all", action="store_true", help="also list the identical files")
    p = sub.add_parser("check", parents=[common], help="find BetaOnly, DebugOnly and Latent-in-loop calls")
    p.add_argument("paths", nargs="+", help=".psc or .pex files, or folders searched below them")
    p.add_argument("--allow", action="append", metavar="SCRIPT.NAME",
                   help="calls never reported, for example Debug.Trace (repeat, or separate with commas)")
    p.add_argument("--creations", action="store_true", help="report DebugOnly calls as errors (console players)")
    p.add_argument("--strict", action="store_true",
                   help="also report a name-only match when only some scripts with that name carry the flag")
    sub.add_parser("mcp", parents=[common], help="run as a read-only MCP server on stdin and stdout (for AI agents)")
    return ap


def version_text():
    return (f"{BYLINE}\nName list: official Starfield Creation Kit wiki categories (names, flags and links only).\n"
            "Free software under the MIT license, with no warranty.")


def main(argv=None):
    ap = parser()
    a = ap.parse_args(argv)
    if a.version:
        print(version_text())
        return 0
    if not a.cmd:
        ap.print_help()
        return 2
    problem = setup_logging(a)
    if problem:
        print(f"Error: {problem}", file=sys.stderr)
        return 2
    if not a.quiet:
        print(BYLINE, file=sys.stderr)
    try:
        ref = Ref(a.data)
    except DataError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2
    a.local = Local(a.cache, use=not a.no_local and a.cmd != "build-local")
    return {"lookup": cmd_lookup, "script": cmd_script, "list": cmd_list, "data": cmd_data,
            "build-local": cmd_build_local, "diff": cmd_diff, "html": cmd_html, "compare": cmd_compare,
            "check": cmd_check, "mcp": cmd_mcp}[a.cmd](ref, a)


def run():
    """main() for the command line: a reader that stops early (head, Select-Object -First) ends the run quietly."""
    def closed_pipe(e):
        # Windows reports a closed pipe as EINVAL with no file name; a real file error always names its file.
        return isinstance(e, BrokenPipeError) or (e.errno == 22 and e.filename is None)

    def silence():
        try:
            os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        except OSError:
            pass
    try:
        code = main()
    except OSError as e:
        if not closed_pipe(e):
            raise
        silence()
        return 0
    try:
        sys.stdout.flush()
    except OSError as e:
        if not closed_pipe(e):
            raise
        silence()
    return code


if __name__ == "__main__":
    sys.exit(run())
