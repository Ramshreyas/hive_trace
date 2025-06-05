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
        buffer = b""
        while True:
            # Read header
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
            # Read exactly content_length bytes
            body = b""
            while len(body) < content_length:
                chunk = self.proc.stdout.buffer.read(content_length - len(body))
                if not chunk:
                    debug("LSP server stdout closed during body read.")
                    return
                body += chunk
            try:
                body_str = body.decode()
                debug(f"Received LSP response: {body_str[:200]}")
                resp = json.loads(body_str)
                if 'id' in resp:
                    with self.lock:
                        self.responses[resp['id']] = resp
            except json.JSONDecodeError as e:
                debug(f"JSON decode error: {e} in body: {body[:200]}")
                continue

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

# Initialize and warm up gopls
lsp_cmd = ["gopls", "-mode=stdio"]
client = LSPClient(lsp_cmd)

init_params = {
    "processId": os.getpid(),
    "rootUri": f"file://{go_workspace}",
    "capabilities": {},
    "trace": "verbose"
}
resp = client.send("initialize", init_params)
if not resp:
    debug("No response to initialize request. Exiting.")
    sys.exit(1)
client.notify("initialized", {})

time.sleep(5)  # Give gopls time to warm up and index the workspace

# Read functions.json
with open("/output/functions.json") as f:
    functions = json.load(f)

callgraph = {}
for fn in functions:
    uri = f"file://{fn['file']}"
    # Send didOpen notification for the file
    try:
        with open(fn['file'], 'r') as fobj:
            lines = fobj.readlines()
            text = ''.join(lines)
        client.notify("textDocument/didOpen", {
            "textDocument": {
                "uri": uri,
                "languageId": "go",
                "version": 1,
                "text": text
            }
        })
        # Try to find the function name position on the start line
        line_num = fn['range']['start']['line'] if fn.get('range') else 0
        func_name = fn['name'].split('.')[-1].split(')')[-1]  # crude, works for most Go funcs
        line_text = lines[line_num] if line_num < len(lines) else ''
        char_pos = line_text.find(func_name)
        if char_pos == -1:
            char_pos = fn['range']['start']['character'] if fn.get('range') else 0
        pos = {"line": line_num, "character": char_pos}
    except Exception as e:
        debug(f"Failed to open file or find function name position for {fn['name']} in {fn['file']}: {e}")
        pos = fn['range']['start'] if fn.get('range') else {"line": 0, "character": 0}
    params = {
        "textDocument": {"uri": uri},
        "position": pos,
        "context": {"includeDeclaration": False}
    }
    debug(f"Requesting references for {fn.get('name')} in {fn.get('file')} at {pos}")
    resp = client.send("textDocument/references", params)
    callees = []
    if resp and 'result' in resp and resp['result']:
        for ref in resp['result']:
            ref_uri = ref['uri']
            ref_file = ref_uri.replace("file://", "")
            ref_line = ref['range']['start']['line']
            callees.append({"file": ref_file, "line": ref_line})
    callgraph[fn.get('name')] = callees

    # Close the file in gopls to free resources
    client.notify("textDocument/didClose", {
        "textDocument": {"uri": uri}
    })
    time.sleep(0.1)  # Throttle to avoid overloading gopls

with open("/output/callgraph.json", "w") as f:
    json.dump(callgraph, f, indent=2)

client.close()
