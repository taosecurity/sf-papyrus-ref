# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Richard Bejtlich
"""Build data/official-names.json from a saved copy (wget mirror) of the official Starfield Creation Kit wiki.

  python -I tools/build_names.py --mirror <folder> [--sources <folder>] [--out data/official-names.json] [--diff]
                                 [--verbose] [--log <file>]

What it keeps from the wiki: each Papyrus function, event and struct NAME, the script it belongs to, whether it is a
function, an event or a struct, the five flags the wiki marks with categories (Latent, Non-delayed, DebugOnly, BetaOnly,
Inventory-safe), and a link to the official page. Nothing else: no descriptions, no signatures, no examples.
The page text is read only to tell an event from a function and is never written out.

--sources  a folder of the Creation Kit's .psc sources. The wiki has no page for the functions and events that the
           quest and alias scripts (Quest, Alias, ReferenceAlias, LocationAlias, RefCollectionAlias) define in Papyrus
           rather than natively, such as Quest.SetStage and ReferenceAlias.OnLoad. Their NAMES are added from the
           sources, marked "origin": "sources" and with no wiki link, with the DebugOnly and BetaOnly keywords of
           their declarations. Nothing else is read from the sources.
--diff     compare the new list with the existing --out file and print what was added, removed or reflagged,
           without writing anything.
--expect   "scripts,functions,events,structs" counts the result must match (a sanity check for maintainers).

Exit codes: 0 done, 1 a problem with the mirror or the counts, 2 bad arguments.
Standard library only. It reads files; it writes only the --out file.
"""
import argparse
import datetime
import html
import json
import logging
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

log = logging.getLogger("build_names")

WIKI_BASE = "https://starfield.creationkit.bethesda.net/w/index.php?title="
FLAG_CATS = {"Latent Functions": "latent", "Non-Delayed Native Functions": "nondelayed",
             "Papyrus Debug Only Functions": "debugonly", "Papyrus Beta Only Functions": "betaonly",
             "Inventory-safe Papyrus Functions": "invsafe"}
FLAG_ORDER = ["latent", "nondelayed", "debugonly", "betaonly", "invsafe"]
EVENT_CATS = {"Events", "Radiant Story Script Events"}
PAPYRUS_HOWTO_CATS = {"Papyrus Tutorials", "Papyrus Language Reference"}
COND_CATS = {"Condition Functions", "Condition Functions For Spaceship References"}
FN_RE = re.compile(r"^(?P<name>\S.*?)\s*-\s+(?P<script>[A-Za-z][A-Za-z0-9_]*)$")
NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_CONFIG_KEYS = ("wgPageName", "wgTitle", "wgCanonicalNamespace", "wgCurRevisionId", "wgCategories")
ALLOWED_ENTRY_KEYS = {"script", "name", "kind", "flags", "wiki", "origin"}
SOURCE_SCRIPTS = ("Quest", "Alias", "ReferenceAlias", "LocationAlias", "RefCollectionAlias")
DECL_RE = re.compile(r"(?im)^[ \t]*(?:[A-Za-z_][\w:]*(?:\[\])?[ \t]+)?(Function|Event)[ \t]+([A-Za-z_]\w*)[ \t]*\(([^\n]*)")
SCRIPT_RE = re.compile(r"(?im)^[ \t]*Scriptname[ \t]+[^\n]*")
SOURCE_FLAGS = {"debugonly", "betaonly"}


def source_flags(line):
    """The DebugOnly and BetaOnly keywords on one declaration or Scriptname line (comments dropped)."""
    words = re.findall(r"[A-Za-z_]+", line.split(";", 1)[0].lower())
    return SOURCE_FLAGS & set(words)


def page_config(text):
    """The wg* values from the page's RLCONF script block (same reading as CK Docs Reloaded's mwpage.py)."""
    out = {}
    for key in _CONFIG_KEYS:
        m = re.search(r'"%s":(\[[^\]]*\]|"(?:[^"\\]|\\.)*"|[^,}]+)' % key, text)
        if m:
            try:
                out[key] = json.loads(m.group(1))
            except ValueError:
                out[key] = m.group(1)
    return out


def content(text):
    start = text.find('<div id="mw-content-text"')
    if start < 0:
        return ""
    end = text.find('<div class="printfooter"', start)
    if end < 0:
        end = text.find('<div id="catlinks"', start)
    return text[start:end if end > 0 else len(text)]


def plain(fragment):
    s = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", fragment)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s))).strip()


def declares_event(body):
    """True when the page's first code block that declares something starts with 'Event'."""
    for m in re.finditer(r"(?is)<pre[^>]*>(.*?)</pre>", body):
        t = plain(m.group(1))
        if re.search(r"\b(Function|Event)\b", t, re.I):
            return bool(re.match(r"(?i)\s*Event\b", t))
    return False


def kind_of(ns, title, cats, words):
    """Same page sorting as CK Docs Reloaded's inventory.py (papyrus-ref, stub, or something we skip)."""
    if ns:
        return "skip"
    ref = None
    if "Console Commands" in cats:
        ref = "console"
    elif cats & COND_CATS:
        ref = "condition"
    elif cats & PAPYRUS_HOWTO_CATS:
        ref = None
    elif "Papyrus" in cats or "Script Objects" in cats or "Events" in cats:
        ref = "papyrus-ref"
    if ref:
        return ref if words >= 5 else "stub"
    return "howto" if words >= 40 else "stub"


def read_mirror(mirror):
    files = sorted(p for p in mirror.rglob("*.html") if p.relative_to(mirror).parts[0] != "w")
    if not files:
        raise SystemExit(f"No saved .html pages in {mirror}. Pass --mirror <folder> with a wget copy of the wiki.")
    log.info("Reading %d saved pages from %s", len(files), mirror)
    pages = defaultdict(list)
    for p in files:
        text = p.read_text(encoding="utf-8", errors="replace")
        cfg = page_config(text)
        name = cfg.get("wgPageName") or p.stem
        pages[name].append((p, text, cfg))
    rows = []
    for name, group in pages.items():
        # One saved file per page: prefer the file named after the page itself (as inventory.py does).
        p, text, cfg = next((g for g in group if g[0].stem == name), None) or min(group, key=lambda g: len(str(g[0])))
        ns = cfg.get("wgCanonicalNamespace") or ""
        title = cfg.get("wgTitle") or name.replace("_", " ")
        cats = set(cfg.get("wgCategories") or [])
        body = content(text)
        rows.append({"page": name, "title": title, "cats": cats, "body": body,
                     "rev": int(cfg.get("wgCurRevisionId") or 0),
                     "kind": kind_of(ns, title, cats, len(plain(body).split()))})
    return rows


def build(rows):
    ref = [r for r in rows if r["kind"] == "papyrus-ref"]
    overview = {r["title"][:-7].strip() for r in ref if r["title"].endswith(" Script")}
    member = defaultdict(Counter)
    for r in ref:
        m = FN_RE.match(r["title"])
        if m and not r["title"].endswith(" Script"):
            member[m.group("script").lower()][m.group("script")] += 1
    canon = {s.lower(): s for s in overview}
    for low, spell in member.items():
        canon.setdefault(low, spell.most_common(1)[0][0])
    entries = []
    for r in rows:
        if r["kind"] not in ("papyrus-ref", "stub"):
            continue
        if r["kind"] == "papyrus-ref" and r["title"].endswith(" Script") and r["title"][:-7].strip() in overview:
            continue
        m = FN_RE.match(r["title"])
        if not m or m.group("script").lower() not in canon:
            continue
        name = m.group("name").strip()
        is_struct = name.lower().endswith(" struct")
        if is_struct:
            name = name[:-7].strip()
        if not NAME_RE.match(name):
            log.warning("Skipped %s: %r is not a Papyrus name", r["page"], name)
            continue
        is_event = not is_struct and (bool(r["cats"] & EVENT_CATS) or declares_event(r["body"]))
        flags = [f for f in FLAG_ORDER if any(FLAG_CATS[c] == f for c in r["cats"] if c in FLAG_CATS)]
        entries.append({"script": canon[m.group("script").lower()], "name": name,
                        "kind": "struct" if is_struct else "event" if is_event else "function", "flags": flags,
                        "wiki": WIKI_BASE + r["page"]})
        log.debug("%s -> %s.%s %s %s", r["page"], entries[-1]["script"], name, entries[-1]["kind"], flags)
    entries.sort(key=lambda e: (e["script"].lower(), e["name"].lower(), e["kind"]))
    scripts = sorted(canon.values(), key=str.lower)
    return scripts, entries


def add_source_names(scripts, entries, folder):
    """Add the names the wiki lacks on SOURCE_SCRIPTS, read from <folder>/<Script>.psc. Names only."""
    have = {(e["script"].lower(), e["name"].lower()) for e in entries}
    added = 0
    for s in SOURCE_SCRIPTS:
        path = Path(folder) / (s + ".psc")
        if not path.is_file():
            log.warning("%s not found in %s: its names were not added", path.name, folder)
            continue
        canon = next((x for x in scripts if x.lower() == s.lower()), s)
        if canon not in scripts:
            scripts.append(canon)
        text = path.read_text(encoding="utf-8-sig", errors="replace")
        head = SCRIPT_RE.search(text)
        script_flags = source_flags(head.group(0)) if head else set()
        for m in DECL_RE.finditer(text):
            name = m.group(2)
            if (s.lower(), name.lower()) in have:
                continue
            have.add((s.lower(), name.lower()))
            flags = [f for f in FLAG_ORDER if f in (source_flags(m.group(3)) | script_flags)]
            entries.append({"script": canon, "name": name, "kind": m.group(1).lower(), "flags": flags, "wiki": "",
                            "origin": "sources"})
            added += 1
            log.debug("source name %s.%s (%s)", canon, name, m.group(1).lower())
    entries.sort(key=lambda e: (e["script"].lower(), e["name"].lower(), e["kind"]))
    scripts.sort(key=str.lower)
    log.info("Added %d names from the Creation Kit sources that the wiki lacks", added)


def document(scripts, entries, revision):
    return {
        "format": 1,
        "source": "Names and flag categories from the official Starfield Creation Kit wiki "
                  "(starfield.creationkit.bethesda.net), plus the names of quest and alias functions and events "
                  "the wiki lacks (origin: sources). Names, flags and links only: no wiki text, "
                  "no signatures and no game script sources.",
        "wiki_revision": revision,
        "built": datetime.date.today().isoformat(),
        "counts": {"scripts": len(scripts), "functions": sum(e["kind"] == "function" for e in entries),
                   "events": sum(e["kind"] == "event" for e in entries),
                   "structs": sum(e["kind"] == "struct" for e in entries),
                   **{f: sum(f in e["flags"] for e in entries) for f in FLAG_ORDER}},
        "scripts": scripts,
        "entries": entries,
    }


def check_shape(doc):
    """Refuse anything that looks like more than names and flags."""
    for e in doc["entries"]:
        extra = set(e) - ALLOWED_ENTRY_KEYS
        if extra:
            raise SystemExit(f"Entry {e.get('script')}.{e.get('name')} has unexpected fields {sorted(extra)}.")
        if not (NAME_RE.match(e["name"]) and NAME_RE.match(e["script"])):
            raise SystemExit(f"Entry {e['script']}.{e['name']} is not a plain Papyrus name.")
        if e.get("origin") == "sources":
            if (e["wiki"] or not set(e["flags"]) <= SOURCE_FLAGS
                    or e["script"].lower() not in {x.lower() for x in SOURCE_SCRIPTS}):
                raise SystemExit(f"Entry {e['script']}.{e['name']} has an odd source-only marker.")
            continue
        if not e["wiki"].startswith(WIKI_BASE) or len(e["wiki"]) > len(WIKI_BASE) + 120:
            raise SystemExit(f"Entry {e['script']}.{e['name']} has an odd wiki link.")


def diff(old, new):
    key = lambda e: (e["script"], e["name"], e["kind"])  # noqa: E731
    o = {key(e): e for e in old.get("entries", [])}
    n = {key(e): e for e in new["entries"]}
    lines = []
    for k in sorted(n.keys() - o.keys()):
        lines.append(f"+ {k[0]}.{k[1]} ({k[2]}) {' '.join(n[k]['flags'])}".rstrip())
    for k in sorted(o.keys() - n.keys()):
        lines.append(f"- {k[0]}.{k[1]} ({k[2]})")
    for k in sorted(o.keys() & n.keys()):
        if o[k]["flags"] != n[k]["flags"]:
            lines.append(f"~ {k[0]}.{k[1]} flags {o[k]['flags']} -> {n[k]['flags']}")
    return lines


def main(argv=None):
    here = Path(__file__).resolve().parent.parent
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mirror", type=Path, required=True, help="the wget copy of starfield.creationkit.bethesda.net")
    ap.add_argument("--sources", type=Path, help="folder of the Creation Kit's .psc sources (see above)")
    ap.add_argument("--out", type=Path, default=here / "data" / "official-names.json")
    ap.add_argument("--diff", action="store_true", help="show changes against --out and write nothing")
    ap.add_argument("--expect", help='counts to match, "scripts,functions,events,structs"')
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--log", type=Path)
    a = ap.parse_args(argv)
    handlers = [logging.StreamHandler()]
    if a.log:
        handlers.append(logging.FileHandler(a.log, mode="w", encoding="utf-8"))
    logging.basicConfig(level=logging.DEBUG if a.verbose else logging.INFO, format="%(levelname)s %(message)s",
                        handlers=handlers)
    if not a.mirror.is_dir():
        log.error("Mirror folder not found: %s. Pass --mirror <folder>.", a.mirror)
        return 1
    rows = read_mirror(a.mirror)
    scripts, entries = build(rows)
    if a.sources:
        if not a.sources.is_dir():
            log.error("Sources folder not found: %s.", a.sources)
            return 1
        add_source_names(scripts, entries, a.sources)
    doc = document(scripts, entries, max(r["rev"] for r in rows))
    check_shape(doc)
    c = doc["counts"]
    log.info("Scripts %d, functions %d, events %d, structs %d; flags %s; wiki revision %d", c["scripts"], c["functions"],
             c["events"], c["structs"], ", ".join(f"{f} {c[f]}" for f in FLAG_ORDER), doc["wiki_revision"])
    if a.expect:
        want = [int(x) for x in a.expect.split(",")]
        got = [c["scripts"], c["functions"], c["events"], c["structs"]]
        if want != got:
            log.error("Counts %s do not match --expect %s.", got, want)
            return 1
    if a.diff:
        old = json.loads(a.out.read_text(encoding="utf-8")) if a.out.is_file() else {}
        lines = diff(old, doc)
        print("\n".join(lines) if lines else "No changes in names or flags.")
        print(f"Old wiki revision {old.get('wiki_revision')}, new {doc['wiki_revision']}; {len(lines)} changes.")
        return 0
    a.out.parent.mkdir(parents=True, exist_ok=True)
    with open(a.out, "w", encoding="utf-8", newline="\n") as f:  # Path.write_text has no newline before 3.10
        f.write(json.dumps(doc, indent=1, ensure_ascii=True) + "\n")
    log.info("Wrote %s", a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
