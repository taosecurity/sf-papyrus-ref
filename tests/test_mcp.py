# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Richard Bejtlich
"""Tests for the MCP server mode: runs the real script as a child process and talks JSON-RPC to it."""
import json
import os
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "sf_papyrus_ref.py")
FIX = os.path.join(ROOT, "tests", "fixtures")


def session(*messages):
    lines = "".join(json.dumps(m) + "\n" for m in messages) + "not json\n"
    p = subprocess.run([sys.executable, "-I", SCRIPT, "mcp", "--quiet", "--no-local"], input=lines.encode("utf-8"),
                       capture_output=True, timeout=60)
    assert p.returncode == 0, p.stderr.decode("utf-8", "replace")
    return [json.loads(x) for x in p.stdout.decode("utf-8").splitlines() if x.strip()]


class Mcp(unittest.TestCase):
    def test_session(self):
        out = session(
            {"jsonrpc": "2.0", "id": 1, "method": "initialize",
             "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
             "params": {"name": "papyrus_lookup", "arguments": {"name": "Debug.Notification"}}},
            {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
             "params": {"name": "papyrus_lookup", "arguments": {"name": "Debug.MakeItSo"}}},
            {"jsonrpc": "2.0", "id": 5, "method": "tools/call",
             "params": {"name": "papyrus_check",
                        "arguments": {"paths": [os.path.join(FIX, "SfprFixture.pex")], "allow": ["Debug.Trace"]}}},
            {"jsonrpc": "2.0", "id": 6, "method": "tools/call", "params": {"name": "nope", "arguments": {}}},
            {"jsonrpc": "2.0", "id": 7, "method": "resources/list"},
        )
        by_id = {m.get("id"): m for m in out}
        self.assertEqual(by_id[1]["result"]["protocolVersion"], "2025-06-18")
        self.assertEqual(by_id[1]["result"]["serverInfo"]["name"], "sf-papyrus-ref")
        self.assertEqual({t["name"] for t in by_id[2]["result"]["tools"]},
                         {"papyrus_lookup", "papyrus_script", "papyrus_list_flag", "papyrus_check"})
        hit = by_id[3]["result"]["structuredContent"]
        self.assertTrue(hit["found"])
        self.assertEqual(hit["matches"][0]["flags"], ["debugonly"])
        miss = by_id[4]["result"]
        self.assertFalse(miss["isError"])
        self.assertFalse(miss["structuredContent"]["found"])
        calls = {f["call"] for f in by_id[5]["result"]["structuredContent"]["findings"]}
        self.assertEqual(calls, {"Debug.Notification", "Utility.Wait", "Game.Warning"})
        self.assertTrue(by_id[6]["result"]["isError"])
        self.assertEqual(by_id[7]["error"]["code"], -32601)
        self.assertEqual(by_id[None]["error"]["code"], -32700)  # the "not json" line
        self.assertNotIn(2.5, by_id)  # the notification got no reply
        self.assertEqual(len(out), 8)


if __name__ == "__main__":
    unittest.main()
