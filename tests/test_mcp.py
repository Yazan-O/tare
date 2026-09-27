import base64
import json
import subprocess
import sys
import unittest

from tests.helpers import REPO, RED, Sandbox


def session(sb, messages, argv=None):
    argv = argv or [sys.executable, "-m", "tare.mcp_server"]
    data = "".join(json.dumps(m) + "\n" for m in messages)
    r = subprocess.run(argv, cwd=sb.root, env=sb.env(), input=data, capture_output=True, text=True, timeout=120)
    return [json.loads(l) for l in r.stdout.splitlines() if l.strip()], r.stderr


class McpServer(unittest.TestCase):
    def setUp(self):
        self.sb = Sandbox()
        self.sb.put_run("local", RED)

    def tearDown(self):
        self.sb.close()

    def test_initialize_list_weigh(self):
        out, err = session(self.sb, [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize",
             "params": {"protocolVersion": "2025-03-26", "capabilities": {},
                        "clientInfo": {"name": "test", "version": "0"}}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "weigh", "arguments": {"side": "local"}}},
            {"jsonrpc": "2.0", "id": 4, "method": "ping"},
        ])
        self.assertEqual([m["id"] for m in out], [1, 2, 3, 4], err)
        self.assertEqual(out[0]["result"]["protocolVersion"], "2025-03-26")
        tools = out[1]["result"]["tools"]
        self.assertEqual([t["name"] for t in tools], ["run_mainframe", "run_port", "weigh", "explain"])
        for t in tools:
            self.assertEqual(t["inputSchema"]["type"], "object")
        self.assertEqual(tools[1]["inputSchema"]["properties"]["side"]["enum"], ["local", "exact", "halfup"])
        res = out[2]["result"]
        self.assertFalse(res["isError"])
        text, image = res["content"]
        self.assertEqual(text["type"], "text")
        self.assertIn("3 of 5 records differ", text["text"])
        self.assertEqual(image["type"], "image")
        self.assertEqual(image["mimeType"], "image/png")
        png = base64.b64decode(image["data"])
        self.assertEqual(png[:8], b"\x89PNG\r\n\x1a\n")
        self.assertEqual(int.from_bytes(png[16:20], "big"), 768)
        self.assertEqual(int.from_bytes(png[20:24], "big"), 432)
        self.assertTrue((self.sb.root / ".tare" / "weigh_local.json").is_file())

    def test_unknown_version_gets_latest_and_file_launch_works(self):
        out, err = session(self.sb, [{"jsonrpc": "2.0", "id": 1, "method": "initialize",
                                      "params": {"protocolVersion": "1999-01-01"}}],
                           argv=[sys.executable, str(REPO / "tare" / "mcp_server.py")])
        self.assertEqual(out[0]["result"]["protocolVersion"], "2025-06-18", err)

    def test_explain_and_errors(self):
        out, _ = session(self.sb, [
            {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
             "params": {"name": "explain", "arguments": {"key": "A10001", "field": "total_lb", "side": "local"}}},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "weigh", "arguments": {"side": "../x"}}},
            {"jsonrpc": "2.0", "id": 3, "method": "nope"},
        ])
        self.assertIn("UNITSUM.cbl:100", out[0]["result"]["content"][0]["text"])
        self.assertTrue(out[1]["result"]["isError"])
        self.assertEqual(out[2]["error"]["code"], -32601)


if __name__ == "__main__":
    unittest.main()
