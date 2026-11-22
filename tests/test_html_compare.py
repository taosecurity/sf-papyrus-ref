# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Richard Bejtlich
"""Tests for the html and compare commands. Run: python -I -m unittest discover -s tests (from the repo folder)."""
import contextlib
import html
import importlib.util
import io
import json
import os
import re
import tempfile
import unittest
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("sf_papyrus_ref", os.path.join(ROOT, "sf_papyrus_ref.py"))
ref_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ref_mod)

# Made-up sources: a parent, a child that calls the parent in three ways, a struct, a property, a state,
# a namespaced script, markup characters in a comment and a string, and a fragment.
SOURCES = {
    "Scripts/Source/Parent.psc": "Scriptname Parent extends ScriptObject Native Hidden\nFunction Slow() native\n"
                                 "Function Peek() native DebugOnly\nStruct Pair\n  int A\nEndStruct\n",
    "Scripts/Source/Child.psc": "Scriptname Child extends Parent\n"
                                "Parent Property Other Auto Const Mandatory\n"
                                "bool Property Ready = True Auto Hidden\n"
                                "int Property Count = 5 AutoReadOnly\n"
                                "Event OnPing(Child akSender)\n  Slow()\n  Other.Peek()\n  (akSender as Parent).Slow()\n"
                                "  Parent:Pair p = new Parent:Pair\nEndEvent\n"
                                "Auto State Waiting\n  Function Tick()\n  EndFunction\nEndState\n"
                                "; <script>alert(1)</script>\nstring Function Say()\n  return \"<b>&</b>\"\nEndFunction\n",
    "Scripts/Source/NS/Deep.psc": "Scriptname NS:Deep extends Child\nFunction Go()\n  Say()\nEndFunction\n",
    "Scripts/Source/Fragments/Quests/QF_A.psc": "Scriptname Fragments:Quests:QF_A extends Parent\n",
}


def call(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = ref_mod.main([*argv, "--quiet", "--no-local"])
    return code, out.getvalue(), err.getvalue()


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.src = os.path.join(self.tmp.name, "src")
        for rel, text in SOURCES.items():
            p = os.path.join(self.src, rel)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w", encoding="utf-8", newline="\n") as f:
                f.write(text)
        self.out = os.path.join(self.tmp.name, "site")

    def tearDown(self):
        self.tmp.cleanup()

    def page(self, name):
        with open(os.path.join(self.out, name), encoding="utf-8") as f:
            return f.read()


class Html(Base):
    def test_builds_pages_and_links_calls(self):
        code, out, err = call("html", "--sources", self.src, "--out", self.out, "--json")
        self.assertEqual(code, 0, err)
        r = json.loads(out)
        self.assertEqual(r["scripts"], 3)  # fragments are left out by default
        self.assertEqual(r["calls"], 4)  # Slow twice, Peek and Say; Tick is never called
        for name in ("index.html", "az.html", "tree.html", "s/Parent.html", "s/Child.html", "s/NS.Deep.html",
                     "assets/site.css", "assets/site.js", "assets/search-index.js"):
            self.assertTrue(os.path.isfile(os.path.join(self.out, name)), name)
        parent = self.page("s/Parent.html")
        self.assertIn("2 places call this function.", parent)  # Slow(): on self and through a cast
        self.assertIn("1 place calls this function.", parent)  # Peek(): through a typed property
        self.assertIn('href="Child.html#L8"', parent)
        self.assertIn("noindex", parent)
        child = self.page("s/Child.html")
        self.assertIn('href="Parent.html#m-pair"', child)  # Parent:Pair links to the struct
        self.assertIn("(state Waiting)", child)
        self.assertIn("Mandatory", child)
        self.assertIn("<td>Auto Hidden</td>", child)  # the default value True is not a flag
        self.assertIn("<td>AutoReadOnly</td>", child)
        self.assertIn("ScriptObject.</p>", self.page("s/NS.Deep.html"))  # the outside ancestor ends the chain
        self.assertIn('id="m-pair"', parent)  # anchors are lowercase, as Papyrus names ignore case

    def test_front_page_sections(self):
        # A made-up stand-in for the walkthrough script: only some of the explained lines are in it.
        p = os.path.join(self.src, "Scripts", "Source", "DefaultSetGlobalOnTriggerEnter.psc")
        with open(p, "w", encoding="utf-8") as f:
            f.write("Scriptname DefaultSetGlobalOnTriggerEnter extends ObjectReference\n"
                    "Event OnTriggerEnter(ObjectReference akActionRef)\nEndEvent\n")
        code, _, err = call("html", "--sources", self.src, "--out", self.out)
        self.assertEqual(code, 0, err)
        home = html.unescape(self.page("index.html"))
        for heading in ("What's new", "A script is a small program that the game runs.",
                        "These are the Starfield scripts that the Creation Kit includes.",
                        "Here is one script, explained line by line.",
                        "The scripts are grouped by the folder they came from."):
            self.assertIn(heading, home)
        self.assertIn("The site was built for the first time", home)
        self.assertIn("This line is not in your version of the script.", home)  # the If line is missing
        self.assertIn('href="s/DefaultSetGlobalOnTriggerEnter.html#L2"', home)  # the event line was found
        self.assertIn("These are the base game's own scripts.", home)  # the folder description column
        self.assertIn("The NS folder holds 1 script.", self.page("az.html"))

    def test_whats_new_lists_changes_between_builds(self):
        call("html", "--sources", self.src, "--out", self.out)
        with open(os.path.join(self.src, "Scripts", "Source", "Parent.psc"), "a", encoding="utf-8") as f:
            f.write("Function Extra() native\n")
        os.remove(os.path.join(self.src, "Scripts", "Source", "NS", "Deep.psc"))
        call("html", "--sources", self.src, "--out", self.out)
        home = self.page("index.html")
        self.assertIn("0 scripts were added, 1 script was removed and 1 script changed.", home)
        self.assertIn("This script changed.", home)
        self.assertIn('<a href="s/Parent.html">Parent</a>', home)
        call("html", "--sources", self.src, "--out", self.out)  # nothing changed: no new entry
        self.assertEqual(self.page("index.html").count("The site was rebuilt"), 1)

    def test_exe_version(self):
        htmlsite = ref_mod.htmlsite
        p = os.path.join(self.tmp.name, "Starfield.exe")
        import struct
        sig = b"\xbd\x04\xef\xfe"
        real = "VS_VERSION_INFO".encode("utf-16-le") + b"\0\0" + sig + struct.pack("<III", 0x10000, 0x10010, 0xF40000)
        stray = sig + struct.pack("<III", 0x12345, 0x50002, 0)  # the signature bytes in data, after the real one
        with open(p, "wb") as f:
            f.write(b"MZ" + b"\0" * 1000 + real + b"\0" * 100 + stray + b"\0" * 100)
        self.assertEqual(htmlsite.exe_version(p), "1.16.244.0")
        self.assertEqual(htmlsite.find_versions(os.path.join(self.tmp.name, "Tools", "x.zip"))[0], "1.16.244.0")
        self.assertIsNone(htmlsite.exe_version(os.path.join(self.tmp.name, "missing.exe")))
        with open(p, "wb") as f:
            f.write(b"MZ" + stray)  # no version resource at all
        self.assertIsNone(htmlsite.exe_version(p))

    def test_review_cases(self):
        htmlsite = ref_mod.htmlsite
        src = os.path.join(self.src, "Scripts", "Source")
        # A doc comment with a ; comment line between it and its property is still found.
        with open(os.path.join(src, "DefaultSetGlobalOnTriggerEnter.psc"), "w", encoding="utf-8") as f:
            f.write("Scriptname DefaultSetGlobalOnTriggerEnter extends ObjectReference\n{About}\n\n"
                    "GlobalVariable Property GlobalToSet Auto Const\n; note\n{The global}\n")
        # A Shattered Space fragment named the way fragments are (QF_SFBGS001_...).
        os.makedirs(os.path.join(src, "Fragments", "Quests"), exist_ok=True)
        with open(os.path.join(src, "Fragments", "Quests", "QF_SFBGS001_X.psc"), "w", encoding="utf-8") as f:
            f.write("Scriptname Fragments:Quests:QF_SFBGS001_X extends Quest\n")
        code, _, err = call("html", "--sources", self.src, "--out", self.out, "--include-fragments")
        self.assertEqual(code, 0, err)
        home = html.unescape(self.page("index.html"))
        self.assertIn('href="s/DefaultSetGlobalOnTriggerEnter.html#L6"', home)  # the doc comment after "; note"
        self.assertNotIn("don't include Shattered Space", home)
        self.assertIn("don't include the Terran Armada Creation", home)
        # --include-fragments on sources without fragments: no advice to pass the flag again.
        os.remove(os.path.join(src, "Fragments", "Quests", "QF_SFBGS001_X.psc"))
        os.remove(os.path.join(src, "Fragments", "Quests", "QF_A.psc"))
        call("html", "--sources", self.src, "--out", self.out, "--include-fragments")
        home = html.unescape(self.page("index.html"))
        self.assertIn("These sources hold no fragment scripts", home)
        self.assertNotIn("Run sf-papyrus-ref html with --include-fragments", home)
        # A version read for the first time is news even when no script changed.
        builds, _, _, _ = htmlsite.update_manifest(self.out, htmlsite.collect(ref_mod.pscread, ref_mod.iter_sources(self.src),
                                                                     ref_mod.log), "2026-11-22 10:00", "1.2.3.4",
                                          "1.2.3.4", ref_mod.log)
        self.assertIn("the Creation Kit 1.2.3.4", builds[-1]["text"])

    def test_markers_and_block_comments(self):
        htmlsite = ref_mod.htmlsite
        src = os.path.join(self.src, "Scripts", "Source")
        with open(os.path.join(src, "QF_SFTerrainSurvey_1.psc"), "w", encoding="utf-8") as f:
            f.write("Scriptname QF_SFTerrainSurvey_1 extends Quest\n")  # not a Terran Armada script
        with open(os.path.join(src, "DefaultSetGlobalOnTriggerEnter.psc"), "w", encoding="utf-8") as f:
            f.write("Scriptname DefaultSetGlobalOnTriggerEnter extends ObjectReference\n"
                    "GlobalVariable Property GlobalToSet Auto Const\n;/ a note\nmore /;\n{The global}\n")
        call("html", "--sources", self.src, "--out", self.out)
        home = html.unescape(self.page("index.html"))
        self.assertIn("the Terran Armada Creation", home)  # still reported as missing
        self.assertIn('href="s/DefaultSetGlobalOnTriggerEnter.html#L5"', home)  # found past the block comment
        self.assertIsNotNone(htmlsite)

    def test_warning_links_and_how_made(self):
        call("html", "--sources", self.src, "--out", self.out)
        home = html.unescape(self.page("index.html"))
        script = html.unescape(self.page("s/Child.html"))
        version = ref_mod.VERSION
        for page in (home, script):
            self.assertIn("contain Bethesda's proprietary content. They are for the owner's personal use only.", page)
            self.assertIn(f'<a href="https://github.com/taosecurity/sf-papyrus-ref" rel="noreferrer">sf-papyrus-ref</a> '
                          f"{version}, a free, open-source tool", page)
        self.assertIn("This is how the site is made.", home)
        self.assertIn("sf-papyrus-ref does not exist to share Bethesda's proprietary intellectual property.", home)
        # The page shows the command as given: the options that change the site, with paths.
        import argparse
        shown = ref_mod.html_command(argparse.Namespace(include_fragments=False, sources=self.src, out=self.out))
        self.assertIn(f"by running <code>{shown}</code>", home)
        self.assertIn("It recorded the scripts, so that the next build", home)  # a first build compares nothing
        call("html", "--sources", self.src, "--out", self.out, "--include-fragments")
        home = html.unescape(self.page("index.html"))
        self.assertIn("<code>sf-papyrus-ref html --include-fragments --sources", home)
        self.assertIn("It compared the scripts with the last build", home)
        call("html", "--sources", self.src, "--out", self.out, "--include-fragments")  # nothing changed
        self.assertIn("It compared the scripts with the last build", html.unescape(self.page("index.html")))

    def test_html_command_and_tool_reset(self):
        import argparse
        a = argparse.Namespace(include_fragments=False, sources=None, out=ref_mod.default_site())
        self.assertEqual(ref_mod.html_command(a), "sf-papyrus-ref html")  # the default folder is not repeated
        a = argparse.Namespace(include_fragments=True, sources=r"C:\My Sources", out="site")
        self.assertEqual(ref_mod.html_command(a),
                         'sf-papyrus-ref html --include-fragments --sources "C:\\My Sources" --out site')
        a = argparse.Namespace(include_fragments=False, sources="C:\\Mods\\Src;old\\", out=ref_mod.default_site())
        self.assertEqual(ref_mod.html_command(a), 'sf-papyrus-ref html --sources "C:\\Mods\\Src;old"')
        htmlsite = ref_mod.htmlsite
        htmlsite.TOOL.update({"command": "stale"})
        htmlsite.build(ref_mod.pscread, ref_mod.iter_sources(self.src), self.src, self.out, {}, "2026-11-22 01:00",
                       ref_mod.log, os.path.join(ref_mod.HERE, "site-assets"))
        self.assertEqual(htmlsite.TOOL["command"], "sf-papyrus-ref html")  # a build without tool info resets it

    def test_az_names_fit_their_columns(self):
        call("html", "--sources", self.src, "--out", self.out, "--include-fragments")
        az = self.page("az.html")
        # The folder heading gives the namespace, so the link shows the short name; the tooltip has the full one.
        self.assertIn('<a href="s/Fragments.Quests.QF_A.html" title="Fragments:Quests:QF_A">'
                      '<span class="ns">Fragments:Quests:</span>QF_A</a>', az)
        self.assertIn('<a href="s/NS.Deep.html" title="NS:Deep"><span class="ns">NS:</span>Deep</a>', az)

    def test_az_keeps_names_whose_namespace_is_not_the_folder(self):
        with open(os.path.join(self.src, "Scripts", "Source", "MyQuest.psc"), "w", encoding="utf-8") as f:
            f.write("Scriptname MyMod:Zeta extends Quest\n")
        with open(os.path.join(self.src, "Scripts", "Source", "Alpha.psc"), "w", encoding="utf-8") as f:
            f.write("Scriptname Alpha extends Quest\n")
        call("html", "--sources", self.src, "--out", self.out)
        az = self.page("az.html")
        self.assertIn('title="MyMod:Zeta">MyMod:<wbr>Zeta</a>', az)  # not cut: the top folder is not MyMod
        self.assertLess(az.index(">Alpha</a>"), az.index(">Child</a>"))  # sorted by the shown name

    def test_long_unlinked_names_can_wrap(self):
        call("html", "--sources", self.src, "--out", self.out)
        os.remove(os.path.join(self.src, "Scripts", "Source", "NS", "Deep.psc"))
        call("html", "--sources", self.src, "--out", self.out)
        self.assertIn("NS:<wbr>Deep.</p>", self.page("index.html"))  # a removed script, shown as plain text

    def test_damaged_manifest_is_ignored(self):
        os.makedirs(self.out)
        with open(os.path.join(self.out, ".sf-papyrus-ref-site"), "w") as f:
            f.write("x")
        with open(os.path.join(self.out, ".sf-papyrus-ref-manifest.json"), "w") as f:
            f.write('{"scripts": {"a": "x"}, "builds": [1]}')
        code, _, err = call("html", "--sources", self.src, "--out", self.out)
        self.assertEqual(code, 0, err)
        self.assertIn("built for the first time", self.page("index.html"))

    def test_fragments_wording_follows_the_build(self):
        call("html", "--sources", self.src, "--out", self.out)
        self.assertIn("This build leaves the fragments out.", self.page("index.html"))
        call("html", "--sources", self.src, "--out", self.out, "--include-fragments")
        home = self.page("index.html")
        self.assertIn("Many scripts on this site are fragments.", home)
        self.assertIn("This build includes the fragment scripts, which the last one left out.", home)

    def test_source_text_is_escaped_and_no_inline_scripts(self):
        call("html", "--sources", self.src, "--out", self.out)
        child = self.page("s/Child.html")
        self.assertNotIn("<script>alert", child)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", child)
        self.assertIn("&lt;b&gt;&amp;&lt;/b&gt;", child)
        for name in ("index.html", "az.html", "tree.html", "s/Child.html"):
            for tag in re.findall(r"<script[^>]*>", self.page(name)):
                self.assertIn("src=", tag)  # works under a strict Content-Security-Policy

    def test_fragments_and_zip(self):
        z = os.path.join(self.tmp.name, "ContentResources.zip")
        with zipfile.ZipFile(z, "w") as zf:
            for rel, text in SOURCES.items():
                zf.writestr(rel.replace("/", "\\"), text)
        code, out, _ = call("html", "--sources", z, "--out", self.out, "--include-fragments", "--json")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["scripts"], 4)
        self.assertTrue(os.path.isfile(os.path.join(self.out, "s", "Fragments.Quests.QF_A.html")))

    def test_refuses_a_folder_it_did_not_write(self):
        os.makedirs(self.out)
        with open(os.path.join(self.out, "mine.txt"), "w") as f:
            f.write("keep")
        code, _, err = call("html", "--sources", self.src, "--out", self.out)
        self.assertEqual(code, 2)
        self.assertIn("did not write", err)
        self.assertTrue(os.path.isfile(os.path.join(self.out, "mine.txt")))

    def test_rebuild_removes_old_pages(self):
        call("html", "--sources", self.src, "--out", self.out)
        os.remove(os.path.join(self.src, "Scripts", "Source", "NS", "Deep.psc"))
        code, _, _ = call("html", "--sources", self.src, "--out", self.out)
        self.assertEqual(code, 0)
        self.assertFalse(os.path.exists(os.path.join(self.out, "s", "NS.Deep.html")))

    def test_no_sources(self):
        empty = os.path.join(self.tmp.name, "empty")
        os.makedirs(empty)
        code, _, err = call("html", "--sources", empty, "--out", self.out)
        self.assertEqual(code, 2)
        self.assertIn("no .psc scripts", err)


class Compare(Base):
    def write(self, rel, text):
        p = os.path.join(self.tmp.name, "mine", rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8", newline="") as f:
            f.write(text)
        return p

    def test_identical_changed_and_not_in_ck(self):
        self.write("Parent.psc", SOURCES["Scripts/Source/Parent.psc"].replace("\n", "\r\n") + "\r\n\r\n")
        self.write("Renamed.psc", SOURCES["Scripts/Source/Child.psc"] + "Function Extra()\nEndFunction\n")
        self.write("Other.psc", "Scriptname SomeoneElse extends Quest\n")
        code, out, _ = call("compare", os.path.join(self.tmp.name, "mine"), "--sources", self.src, "--json")
        self.assertEqual(code, 1)
        r = {os.path.basename(x["file"]): x for x in json.loads(out)["results"]}
        self.assertEqual(r["Parent.psc"]["status"], "identical")  # line endings and trailing blank lines ignored
        self.assertEqual(r["Renamed.psc"]["status"], "changed")  # matched by Scriptname, not file name
        self.assertEqual(r["Renamed.psc"]["lines_added"], 2)
        self.assertEqual(r["Other.psc"]["status"], "not-in-ck")

    def test_all_identical_is_exit_0(self):
        p = self.write("Parent.psc", SOURCES["Scripts/Source/Parent.psc"])
        code, out, _ = call("compare", p, "--sources", self.src)
        self.assertEqual(code, 0)
        self.assertIn("1 is identical, 0 are changed and 0 are not from the Creation Kit", out)

    def test_bom_is_ignored(self):
        p = self.write("Parent.psc", "﻿" + SOURCES["Scripts/Source/Parent.psc"])
        code, out, _ = call("compare", p, "--sources", self.src, "--json")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["results"][0]["status"], "identical")

    def test_own_script_with_a_bethesda_file_name_is_not_a_copy(self):
        p = self.write("Child.psc", "Scriptname MyMod:Child extends Quest\n")
        code, out, _ = call("compare", p, "--sources", self.src, "--json")
        self.assertEqual(json.loads(out)["results"][0]["status"], "not-in-ck")

    def test_commented_scriptname_is_ignored(self):
        p = self.write("X.psc", ";/\nScriptname Parent\n/;\nScriptname Brand:New extends Quest\n")
        code, out, _ = call("compare", p, "--sources", self.src, "--json")
        r = json.loads(out)["results"][0]
        self.assertEqual((r["script"], r["status"]), ("Brand:New", "not-in-ck"))

    def test_broken_scriptname_never_matches_a_shorter_name_or_the_file_name(self):
        for text in ("Scriptname Parent.Extra extends Quest\n", "Scriptname Parent:\n", "Scriptname\n",
                     "Scriptname:Parent\n"):
            p = self.write("Parent.psc", text)
            code, out, _ = call("compare", p, "--sources", self.src, "--json")
            r = json.loads(out)["results"][0]
            self.assertEqual((r["status"], r["script"]), ("not-in-ck", ""), text)
            self.assertIn("could not be read", r["note"])
        for text in ("ScriptName = 1\n", "ScriptName += 1\n", "ScriptName.X = 1\n", "ScriptName[0] = 1\n",
                     "ScriptName()\n"):  # statements, not Scriptname lines: the file name decides
            p = self.write("Parent.psc", text)
            code, out, _ = call("compare", p, "--sources", self.src, "--json")
            self.assertEqual(json.loads(out)["results"][0]["status"], "changed", text)

    def test_trailing_text_after_the_name_still_matches(self):
        p = self.write("Other.psc", "Scriptname Parent extends ScriptObject Native Hidden , odd\n")
        code, out, _ = call("compare", p, "--sources", self.src, "--json")
        self.assertEqual(json.loads(out)["results"][0]["status"], "changed")

    def test_pex_given_directly_is_an_error(self):
        p = self.write("Foo.pex", "binary")
        code, _, err = call("compare", p, "--sources", self.src)
        self.assertEqual(code, 2)
        self.assertIn("not a .psc source file", err)

    def test_missing_path(self):
        code, _, err = call("compare", os.path.join(self.tmp.name, "nope"), "--sources", self.src)
        self.assertEqual(code, 2)
        self.assertIn("not found", err)


if __name__ == "__main__":
    unittest.main()
