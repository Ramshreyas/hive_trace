#!/usr/bin/env python3
import subprocess
import json
import os
import sys
import threading
import time

go_workspace = "/build"

def debug(msg):
    print(f"[DEBUG] {msg}", file=sys.stderr)

class LSPClient:
    def __init__(self, cmd):
        debug(f"Starting LSP server: {' '.join(cmd)}")
        self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=0)
        self.id = 1
        self.responses = {}
        self.lock = threading.Lock()
        self.reader_thread = threading.Thread(target=self._reader, daemon=True)
        self.reader_thread.start()

    def _reader(self):
        debug("LSP reader thread started.")
        while True:
            header = b""
            while not header.endswith(b"\r\n\r\n"):
                chunk = self.proc.stdout.buffer.read(1)
                if not chunk:
                    debug("LSP server stdout closed.")
                    return
                header += chunk
            headers = header.decode().split("\r\n")
            content_length = 0
            for h in headers:
                if h.lower().startswith("content-length:"):
                    content_length = int(h.split(":")[1].strip())
            if content_length == 0:
                debug("No content-length found in LSP response header.")
                continue
            body = self.proc.stdout.read(content_length)
            debug(f"Received LSP response: {body[:200]}")
            resp = json.loads(body)
            if 'id' in resp:
                with self.lock:
                    self.responses[resp['id']] = resp

    def send(self, method, params=None):
        msg = {
            "jsonrpc": "2.0",
            "id": self.id,
            "method": method
        }
        if params is not None:
            msg["params"] = params
        body = json.dumps(msg)
        header = f"Content-Length: {len(body)}\r\n\r\n"
        debug(f"Sending LSP request: {method} (id={self.id})")
        self.proc.stdin.write(header + body)
        self.proc.stdin.flush()
        my_id = self.id
        self.id += 1
        # Wait for response
        for _ in range(100):
            with self.lock:
                if my_id in self.responses:
                    debug(f"Got response for id={my_id}")
                    return self.responses.pop(my_id)
            time.sleep(0.05)
        debug(f"Timeout waiting for response to id={my_id}")
        return None

    def notify(self, method, params=None):
        msg = {
            "jsonrpc": "2.0",
            "method": method
        }
        if params is not None:
            msg["params"] = params
        body = json.dumps(msg)
        header = f"Content-Length: {len(body)}\r\n\r\n"
        debug(f"Sending LSP notification: {method}")
        self.proc.stdin.write(header + body)
        self.proc.stdin.flush()

    def close(self):
        debug("Terminating LSP server.")
        self.proc.terminate()
        self.proc.wait()

lsp_cmd = ["gopls", "-mode=stdio"]
client = LSPClient(lsp_cmd)

root_uri = f"file://{go_workspace}"
init_params = {
    "processId": os.getpid(),
    "rootUri": root_uri,
    "capabilities": {},
    "workspaceFolders": [{"uri": root_uri, "name": "go-ethereum"}]
}
debug("Sending initialize request to LSP server.")
resp = client.send("initialize", init_params)
if not resp:
    debug("No response to initialize request. Exiting.")
    sys.exit(1)
client.notify("initialized", {})

go_files = []
debug(f"Walking workspace {go_workspace} to find Go files.")
for dirpath, _, filenames in os.walk(go_workspace):
    for f in filenames:
        if f.endswith(".go"):
            go_files.append(os.path.join(dirpath, f))
debug(f"Found {len(go_files)} Go files.")

functions = []
for f in go_files:
    uri = f"file://{f}"
    params = {"textDocument": {"uri": uri}}
    debug(f"Requesting document symbols for {f}")
    resp = client.send("textDocument/documentSymbol", params)
    if resp and 'result' in resp:
        for sym in resp['result']:
            if sym.get('kind') in (12, 6):  # Function or Method
                # Try to get 'range' directly, else from 'location', else None
                rng = sym.get('range')
                if rng is None and 'location' in sym and 'range' in sym['location']:
                    rng = sym['location']['range']
                if rng is None:
                    debug(f"No range found for symbol {sym.get('name')} in {f}")
                functions.append({"name": sym['name'], "file": f, "range": rng})
    else:
        debug(f"No symbols found or error for {f}")

print("=== All Functions and Methods ===")
for fn in functions:
    print(f"{fn['name']} ({fn['file']})")

# Write functions to JSON file
os.makedirs("/output", exist_ok=True)
with open("/output/functions.json", "w") as f:
    json.dump(functions, f, indent=2)

# --- Call graph extraction ---
callgraph = {}
for fn in functions:
    uri = f"file://{fn['file']}"
    pos = fn['range']['start'] if fn['range'] else {"line": 0, "character": 0}
    params = {
        "textDocument": {"uri": uri},
        "position": pos,
        "context": {"includeDeclaration": False}
    }
    debug(f"Requesting references for {fn['name']} in {fn['file']} at {pos}")
    resp = client.send("textDocument/references", params)
    callees = []
    if resp and 'result' in resp and resp['result']:
        for ref in resp['result']:
            ref_uri = ref['uri']
            ref_file = ref_uri.replace("file://", "")
            ref_line = ref['range']['start']['line']
            callees.append({"file": ref_file, "line": ref_line})
    callgraph[fn['name']] = callees

with open("/output/callgraph.json", "w") as f:
    json.dump(callgraph, f, indent=2)

client.close()
