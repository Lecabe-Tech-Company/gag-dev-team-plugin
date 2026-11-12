"""Native stdio bridge against a local fetch fake, with no real HTTP requests."""
import json
from pathlib import Path
import subprocess
import tempfile

from test_project_cli import ProjectCase, ROOT, TOKEN


class BridgeTests(ProjectCase):
    def test_portable_bridge_translates_jsonrpc_and_session_headers_without_secret_output(self):
        self.install.install(self.project, source=ROOT, harnesses=["claude"])
        self.install.configure_scripta(self.project, TOKEN)
        server = json.loads((self.project / ".mcp.json").read_text())["mcpServers"]["docs"]
        with tempfile.TemporaryDirectory(prefix="gag fetch fake ") as temp:
            preload = Path(temp) / "fake-fetch.cjs"
            preload.write_text("""
const expected = """ + json.dumps(TOKEN) + """;
let calls = 0;
global.fetch = async (url, options) => {
  calls++;
  if (url !== 'https://scripta-mcp.lecabe.com.br/mcp') throw Error('wrong endpoint');
  if (options.headers.Authorization !== 'Bearer ' + expected) throw Error('wrong auth');
  if (options.redirect !== 'error') throw Error('redirect must be forbidden');
  const message = JSON.parse(options.body);
  if (calls > 1 && (options.headers['Mcp-Session-Id'] !== 'qa-session' || options.headers['MCP-Protocol-Version'] !== '2025-03-26')) throw Error('session missing');
  return {ok:true, headers:{get:name => name.toLowerCase() === 'mcp-session-id' ? 'qa-session' : 'application/json'},
    text:async () => JSON.stringify({jsonrpc:'2.0',id:message.id,result:message.method === 'initialize' ? {protocolVersion:'2025-03-26',capabilities:{},serverInfo:{name:'qa',version:'1'}} : {tools:[]}})};
};
""")
            messages = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
                        {"jsonrpc": "2.0", "method": "notifications/initialized"},
                        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}]
            nested = self.project / "subdir with spaces"
            nested.mkdir()
            result = subprocess.run([server["command"], "--require", str(preload), *server["args"]], input="\n".join(map(json.dumps, messages)) + "\n", cwd=nested, capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        replies = list(map(json.loads, result.stdout.splitlines()))
        self.assertEqual([reply["id"] for reply in replies], [1, 2])
        self.assertEqual(replies[0]["result"]["protocolVersion"], "2025-03-26")
        self.assertEqual(replies[1]["result"], {"tools": []})
        self.assertNotIn(TOKEN, result.stdout + result.stderr)
        self.assertEqual(result.stderr, "")
