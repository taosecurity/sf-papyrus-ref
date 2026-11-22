# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Richard Bejtlich
"""Tests for the html and compare commands. Run: python -I -m unittest discover -s tests (from the repo folder)."""
import contextlib
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
    "Scripts/Source/Parent.psc": "Scriptname Parent Native Hidden\nFunction Slow() native\n"
                                 "Function Peek() native DebugOnly\nStruct Pair\n  int A\nEndStruct\n",
    "Scripts/Source/Child.psc": "Scriptname Child extends Parent\n"
                                "Parent Property Other Auto Const Mandatory\n"
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
        self.assertIn("Called from 2 places", parent)  # Slow(): on self and through a cast
        self.assertIn("Called from 1 place<", parent)  # Peek(): through a typed property
        self.assertIn('href="Child.html#L6"', parent)
        self.assertIn("noindex", parent)
        child = self.page("s/Child.html")
        self.assertIn('href="Parent.html#m-Pair"', child)  # Parent:Pair links to the struct
        self.assertIn("(state Waiting)", child)
        self.assertIn("Mandatory", child)

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
        self.assertIn("1 identical, 0 changed, 0 not from the Creation Kit", out)

    def test_missing_path(self):
        code, _, err = call("compare", os.path.join(self.tmp.name, "nope"), "--sources", self.src)
        self.assertEqual(code, 2)
        self.assertIn("not found", err)


if __name__ == "__main__":
    unittest.main()
