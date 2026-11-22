# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Richard Bejtlich
"""Tests for sf-papyrus-ref. Run: python -I -m unittest discover -s tests (from the repo folder)."""
import contextlib
import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ref_mod = load("sf_papyrus_ref", os.path.join(ROOT, "sf_papyrus_ref.py"))
build_mod = load("build_names", os.path.join(ROOT, "tools", "build_names.py"))

# A made-up list in the shipped format, so the command tests do not depend on the real data.
FIXTURE = {
    "format": 1, "source": "test", "wiki_revision": 1, "built": "2026-01-01",
    "counts": {"scripts": 3},
    "scripts": ["Alpha", "Beta", "Empty"],
    "entries": [
        {"script": "Alpha", "name": "DoThing", "kind": "function", "flags": ["latent"], "wiki": "w1"},
        {"script": "Alpha", "name": "OnThing", "kind": "event", "flags": [], "wiki": "w2"},
        {"script": "Beta", "name": "DoThing", "kind": "function", "flags": ["nondelayed"], "wiki": "w3"},
        {"script": "Beta", "name": "Shout", "kind": "function", "flags": ["debugonly", "betaonly"], "wiki": "w4"},
    ],
}


def run(*argv, data):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = ref_mod.main([*argv, "--data", data, "--quiet", "--no-local"])
    return code, out.getvalue(), err.getvalue()


def run_real(*argv):
    """With the shipped name list (needed for the fixture checks)."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = ref_mod.main([*argv, "--quiet"])
    return code, out.getvalue(), err.getvalue()


FIX = os.path.join(ROOT, "tests", "fixtures")

# A made-up Creation Kit source tree: a parent with a Latent function and a DebugOnly one, and a child.
FAKE_SOURCES = {
    "Parent.psc": "Scriptname Parent Native Hidden\nFunction Slow() native\n"
                  "Function Peek() native DebugOnly\nint Function Count(string asText = \"a, b\") native global\n",
    "Child.psc": "Scriptname Child extends Parent Native Hidden\nEvent OnPing(Child akSender)\nEndEvent\n",
    "Fragments/Frag.psc": "Scriptname Frag extends Parent\n",
}


class Check(unittest.TestCase):
    def findings(self, path, *extra):
        code, out, err = run_real("check", path, "--json", "--no-local", *extra)
        return code, json.loads(out)["findings"]

    def test_pex_and_psc_agree(self):
        _, a = self.findings(os.path.join(FIX, "SfprFixture.pex"))
        _, b = self.findings(os.path.join(FIX, "SfprFixture.psc"))
        key = lambda x: (x["line"], x["call"], x["rule"])  # noqa: E731
        self.assertEqual(sorted(map(key, a)), sorted(map(key, b)))
        self.assertEqual(sorted(map(key, b)), [(7, "Debug.Trace", "debugonly"), (8, "Debug.Notification", "debugonly"),
                                               (11, "Utility.Wait", "latent-loop"), (15, "Game.Warning", "betaonly"),
                                               (31, "Debug.MessageBox", "debugonly")])  # 31: a property's Set

    def test_severity_and_exit_codes(self):
        code, f = self.findings(os.path.join(FIX, "SfprFixture.psc"))
        self.assertEqual(code, 1)
        self.assertEqual({x["call"]: x["severity"] for x in f}["Game.Warning"], "error")
        code, f = self.findings(os.path.join(FIX, "SfprFixture.psc"), "--creations")
        self.assertEqual({x["call"]: x["severity"] for x in f}["Debug.Notification"], "error")

    def test_allow(self):
        _, f = self.findings(os.path.join(FIX, "SfprFixture.pex"), "--allow", "debug.trace,Debug.Notification")
        self.assertEqual({x["call"] for x in f}, {"Utility.Wait", "Game.Warning", "Debug.MessageBox"})

    def test_bad_log_path_is_a_message(self):
        code, _, err = run_real("lookup", "Wait", "--no-local", "--log",
                                os.path.join(FIX, "no-such-folder", "x.log"))
        self.assertEqual(code, 2)
        self.assertIn("could not open the log file", err)

    def test_missing_path(self):
        code, _, _ = run_real("check", os.path.join(FIX, "nope.psc"), "--no-local")
        self.assertEqual(code, 2)

    def test_psc_with_bom_reads_the_same(self):
        with open(os.path.join(FIX, "SfprFixture.psc"), encoding="utf-8") as f:
            text = f.read()
        with tempfile.TemporaryDirectory() as t:
            p = os.path.join(t, "SfprFixture.psc")
            with open(p, "w", encoding="utf-8-sig", newline="") as f:
                f.write(text)
            _, plain = self.findings(os.path.join(FIX, "SfprFixture.psc"))
            _, bom = self.findings(p)
            key = lambda x: (x["line"], x["call"], x["rule"])  # noqa: E731
            self.assertEqual(sorted(map(key, plain)), sorted(map(key, bom)))

    def test_damaged_pex(self):
        with tempfile.TemporaryDirectory() as t:
            p = os.path.join(t, "Bad.pex")
            with open(os.path.join(FIX, "SfprFixture.pex"), "rb") as f:
                data = f.read()
            with open(p, "wb") as f:
                f.write(data[:200])
            code, _, err = run_real("check", p, "--no-local")
            self.assertEqual(code, 2)
            self.assertIn("ends early", err)


class Local(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.src = os.path.join(self.tmp.name, "src")
        for rel, text in FAKE_SOURCES.items():
            p = os.path.join(self.src, rel)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w", encoding="utf-8") as f:
                f.write(text)
        self.cache = os.path.join(self.tmp.name, "cache", "local.json")

    def tearDown(self):
        self.tmp.cleanup()

    def test_build_local_and_resolution(self):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = ref_mod.main(["build-local", "--sources", self.src, "--cache", self.cache, "--quiet"])
        self.assertEqual(code, 0, err.getvalue())
        with open(self.cache, encoding="utf-8") as f:
            doc = json.load(f)
        self.assertEqual(set(doc["scripts"]), {"parent", "child"})  # Fragments left out
        members = {m["name"]: m for m in doc["scripts"]["parent"]["members"]}
        self.assertEqual(members["Count"]["sig"], 'int Function Count(string asText = "a, b") native global')
        self.assertEqual(members["Peek"]["flags"], ["native", "debugonly"])
        # A call on a Child variable to an inherited DebugOnly function resolves through the cache.
        ref = ref_mod.Ref()
        local = ref_mod.Local(self.cache)
        self.assertEqual(local.chain("Child"), ["Child", "Parent"])
        ch = ref_mod.Checker(ref, local)
        psc = "Scriptname Mine extends Quest\nChild Property C Auto\nFunction F()\n  While True\n    C.Peek()\n" \
              "    C.Slow()\n  EndWhile\nEndFunction\n"
        got = {(x["call"], x["rule"], x["confidence"]) for x in ch.check_psc("Mine.psc", psc)}
        # Latent is never a keyword in the sources (only the wiki marks it), so Slow gives no finding.
        self.assertEqual(got, {("Parent.Peek", "debugonly", "exact")})

    def test_lookup_follows_parents(self):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            ref_mod.main(["build-local", "--sources", self.src, "--cache", self.cache, "--quiet"])
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = ref_mod.main(["lookup", "Child.Peek", "--cache", self.cache, "--json", "--quiet"])
        j = json.loads(out.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(j["inherited_from"], "Parent")
        self.assertEqual(j["matches"][0]["source_flags"], ["debugonly"])

    def test_import_is_followed_with_a_cache(self):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            ref_mod.main(["build-local", "--sources", self.src, "--cache", self.cache, "--quiet"])
        ch = ref_mod.Checker(ref_mod.Ref(), ref_mod.Local(self.cache))
        psc = "Scriptname Mine extends Child\nImport Debug\nFunction F()\n  Notification(\"x\")\n  Peek()\nEndFunction\n"
        got = {(x["call"], x["confidence"]) for x in ch.check_psc("Mine.psc", psc)}
        self.assertEqual(got, {("Debug.Notification", "exact"), ("Parent.Peek", "exact")})

    def test_damaged_cache_warns(self):
        os.makedirs(os.path.dirname(self.cache), exist_ok=True)
        with open(self.cache, "w", encoding="utf-8") as f:
            f.write("{bad")
        err = io.StringIO()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
            code = ref_mod.main(["lookup", "Wait", "--cache", self.cache, "--quiet"])
        self.assertEqual(code, 0)
        self.assertIn("run build-local again", err.getvalue())

    def test_unwritable_cache_is_a_message(self):
        blocker = os.path.join(self.tmp.name, "file")
        with open(blocker, "w") as f:
            f.write("x")
        err = io.StringIO()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
            code = ref_mod.main(["build-local", "--sources", self.src, "--cache", os.path.join(blocker, "c.json"),
                                 "--quiet"])
        self.assertEqual(code, 2)
        self.assertIn("could not write the local cache", err.getvalue())

    def test_lookup_inherited_without_cache(self):
        code, out, _ = run_real("lookup", "Actor.GetValue", "--json", "--no-local")
        j = json.loads(out)
        self.assertEqual(code, 1)
        self.assertIn("ObjectReference", j["on_other_scripts"])
        self.assertIn("inherits", j["note"])

    def test_build_local_bad_path(self):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = ref_mod.main(["build-local", "--sources", os.path.join(self.tmp.name, "none"),
                                 "--cache", self.cache, "--quiet"])
        self.assertEqual(code, 2)
        self.assertIn("does not exist", err.getvalue())


class Psc(unittest.TestCase):
    def test_comments_strings_continuations(self):
        psc_mod = ref_mod.pscread
        text = 'Scriptname S\n;/ Debug.Trace("x")\n/;\nFunction F()\n  Debug.Trace("a(b)" + \\\n  x)\n' \
               '  { Game.Warning() }\nEndFunction\n'
        calls = psc_mod.read_calls(text)["calls"]
        self.assertEqual([(c["line"], c["name"], c["target"]) for c in calls], [(5, "Trace", ("var", "Debug"))])

    def test_late_script_level_declaration_is_typed(self):
        text = "Scriptname S\nFunction F()\n  Target.MoveTo(Target)\nEndFunction\nActor Property Target Auto\n"
        calls = ref_mod.pscread.read_calls(text)["calls"]
        self.assertEqual(calls[0]["types"].get("target"), "Actor")

    def test_states_and_structs(self):
        d = ref_mod.pscread.read_declarations(
            "Scriptname S extends Form\nStruct Point\n  float X\nEndStruct\nFunction A()\nEndFunction\n"
            "State Busy\n  Function A()\n  EndFunction\n  Event OnX()\n  EndEvent\nEndState\n")
        self.assertEqual([(m["name"], m["kind"]) for m in d["members"]],
                         [("Point", "struct"), ("A", "function"), ("OnX", "event")])
        self.assertEqual(d["extends"], "Form")


class Commands(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.data = os.path.join(cls.tmp.name, "names.json")
        with open(cls.data, "w", encoding="utf-8") as f:
            json.dump(FIXTURE, f)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_lookup_any_script(self):
        code, out, _ = run("lookup", "dothing", data=self.data)
        self.assertEqual(code, 0)
        self.assertIn("Alpha.DoThing", out)
        self.assertIn("Beta.DoThing", out)
        self.assertIn("2 scripts", out)

    def test_lookup_script_dot_name(self):
        code, out, _ = run("lookup", "beta.DoThing", "--json", data=self.data)
        self.assertEqual(code, 0)
        j = json.loads(out)
        self.assertEqual([m["script"] for m in j["matches"]], ["Beta"])
        self.assertEqual(j["author"], "Richard Bejtlich")

    def test_lookup_not_found_never_guesses(self):
        code, out, _ = run("lookup", "Alpha.DoThin", "--json", data=self.data)
        self.assertEqual(code, 1)
        j = json.loads(out)
        self.assertFalse(j["found"])
        self.assertEqual(j["matches"], [])
        self.assertEqual(j["near"][0], "Alpha.DoThing")
        self.assertIn("made-up name", j["note"])

    def test_script(self):
        code, out, _ = run("script", "alpha", data=self.data)
        self.assertEqual(code, 0)
        self.assertIn("Alpha - Functions (1)", out)
        self.assertIn("Alpha - Events (1)", out)
        code, out, _ = run("script", "Empty", data=self.data)
        self.assertEqual(code, 0)
        code, out, _ = run("script", "Gamma", data=self.data)
        self.assertEqual(code, 1)

    def test_list_flag(self):
        code, out, _ = run("list", "--flag", "betaonly", "--json", data=self.data)
        self.assertEqual(code, 0)
        self.assertEqual([e["name"] for e in json.loads(out)["entries"]], ["Shout"])
        code, out, _ = run("list", "--flag", "invsafe", data=self.data)
        self.assertEqual(code, 1)
        code, _, err = run("list", "--flag", "latent", "--script", "Nope", data=self.data)
        self.assertEqual(code, 2)

    def test_bad_data_file(self):
        code, _, err = run("data", data=os.path.join(self.tmp.name, "missing.json"))
        self.assertEqual(code, 2)
        self.assertIn("missing", err)


class ShippedData(unittest.TestCase):
    """The shipped list must hold names, flags and links only."""

    def setUp(self):
        with open(os.path.join(ROOT, "data", "official-names.json"), encoding="utf-8") as f:
            self.doc = json.load(f)

    def test_shape(self):
        build_mod.check_shape(self.doc)  # raises SystemExit on anything extra
        for e in self.doc["entries"]:
            self.assertIn(e["kind"], ("function", "event", "struct"))
            self.assertTrue(set(e["flags"]) <= set(build_mod.FLAG_ORDER))

    def test_counts_agree(self):
        c = self.doc["counts"]
        es = self.doc["entries"]
        self.assertEqual(c["functions"] + c["events"] + c["structs"], len(es))
        for f in build_mod.FLAG_ORDER:
            self.assertEqual(c[f], sum(f in e["flags"] for e in es))


class Builder(unittest.TestCase):
    def page(self, name, cats, body):
        return {"page": name, "title": name.replace("_", " "), "cats": set(cats), "body": body, "rev": 5,
                "kind": build_mod.kind_of("", name, set(cats), len(build_mod.plain(body).split()))}

    def test_build_sorts_kinds_and_flags(self):
        words = "<p>" + "word " * 10 + "</p>"
        rows = [
            self.page("Alpha_Script", ["Papyrus", "Script Objects"], words),
            self.page("DoThing_-_Alpha", ["Papyrus", "Latent Functions"], words),
            self.page("OnThing_-_Alpha", ["Papyrus"], "<pre>Event OnThing()</pre>" + words),
            self.page("Point_struct_-_Alpha", ["Papyrus"], words),
            self.page("Intro_(Papyrus)", ["Papyrus", "Papyrus Tutorials"], words),
        ]
        scripts, entries = build_mod.build(rows)
        self.assertEqual(scripts, ["Alpha"])
        got = {(e["name"], e["kind"], tuple(e["flags"])) for e in entries}
        self.assertEqual(got, {("DoThing", "function", ("latent",)), ("OnThing", "event", ()),
                               ("Point", "struct", ())})
        doc = build_mod.document(scripts, entries, 5)
        build_mod.check_shape(doc)

    def test_diff(self):
        old = {"entries": [{"script": "A", "name": "X", "kind": "function", "flags": []}]}
        new = {"entries": [{"script": "A", "name": "X", "kind": "function", "flags": ["latent"]},
                           {"script": "A", "name": "Y", "kind": "event", "flags": []}]}
        lines = build_mod.diff(old, new)
        self.assertIn("+ A.Y (event)", lines)
        self.assertTrue(any(line.startswith("~ A.X") for line in lines))


if __name__ == "__main__":
    unittest.main()
