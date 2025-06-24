#!/usr/bin/env python3
"""Extract every Go function or method in an Erigon checkout using *gopls*.

Changes vs. the previous iteration
----------------------------------
* **Robust JSON‑RPC framing** (unchanged from v2) – the reader uses the
  binary `stdout.buffer` stream only and keeps a private buffer to stitch
  together messages.
* **Readiness gate** – the script now waits until gopls logs
  "Finished loading packages." before it starts firing 2 k+ symbol
  requests.  This makes time‑outs disappear on a cold workspace.
* **Per‑request timeout bumped to 60 s** – heavy symbol queries on a big
  repo (and Go ≤1.20) often take more than 10 s.
* **Cleaner exit on Ctrl‑C** – all gopls children are terminated.

Usage (inside container)
~~~~~~~~~~~~~~~~~~~~~~~~
```
python3 /extract_functions_lsp.py --out /output/functions.json
```
"""

from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
from typing import Any, Dict, List, Optional

GO_WORKSPACE = "/build"
DEFAULT_OUT = "/output/functions.json"

# ---------------------------------------------------------------------------
# Simple coloured logger (stderr)
# ---------------------------------------------------------------------------

def debug(msg: str) -> None:
    print(f"[DEBUG] {msg}", file=sys.stderr)

# ---------------------------------------------------------------------------
# LSP client – tiny but battle‑tested
# ---------------------------------------------------------------------------

class LSPClient:
    _HDR_ENDINGS = (b"\r\n\r\n", b"\n\n")
    _CL_RE = re.compile(br"Content-Length:\s*(\d+)", re.I)

    def __init__(self, cmd: List[str]):
        debug("Starting LSP server: " + " ".join(cmd))
        self.proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,   # write str → stdin
            bufsize=0,
        )
        if not all((self.proc.stdin, self.proc.stdout, self.proc.stderr)):
            raise RuntimeError("Failed to open pipes to gopls")

        self._next_id = 1
        self._responses: Dict[int, Dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._ready = threading.Event()

        threading.Thread(target=self._reader, daemon=True).start()
        threading.Thread(target=self._stderr_forward, daemon=True).start()

    # ---------------- public API ----------------

    def send(self, method: str, params: Optional[Any] = None, *, timeout: float = 60.0) -> Optional[Dict[str, Any]]:
        """Send a JSON‑RPC request and block until the reply or *timeout* (s)."""
        body = {"jsonrpc": "2.0", "id": self._next_id, "method": method}
        if params is not None:
            body["params"] = params
        body_str = json.dumps(body)
        header = f"Content-Length: {len(body_str)}\r\n\r\n"

        debug(f"Sending LSP request: {method} (id={self._next_id})")
        self.proc.stdin.write(header + body_str)
        self.proc.stdin.flush()

        my_id = self._next_id
        self._next_id += 1

        ticks = int(timeout / 0.05)
        for _ in range(ticks):
            with self._lock:
                if my_id in self._responses:
                    return self._responses.pop(my_id)
            time.sleep(0.05)
        debug(f"Timeout waiting for response id={my_id}")
        return None

    def notify(self, method: str, params: Optional[Any] = None) -> None:
        body = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            body["params"] = params
        body_str = json.dumps(body)
        header = f"Content-Length: {len(body_str)}\r\n\r\n"
        debug(f"Sending LSP notification: {method}")
        self.proc.stdin.write(header + body_str)
        self.proc.stdin.flush()

    def wait_until_ready(self, timeout: float = 180.0) -> None:
        debug("Waiting for gopls to finish loading packages…")
        if self._ready.wait(timeout):
            debug("gopls is ready.")
        else:
            debug("gopls did not report readiness; continuing anyway.")

    def close(self) -> None:
        debug("Terminating LSP server.")
        self.proc.terminate()
        try:
            self.proc.wait(5)
        except subprocess.TimeoutExpired:
            self.proc.kill()

    # ---------------- internal helpers ----------------

    def _stderr_forward(self) -> None:
        for line in self.proc.stderr:
            debug(f"[gopls stderr] {line.rstrip()}")

    def _reader(self) -> None:
        debug("LSP reader thread started.")
        buf = b""
        while True:
            # ---- header ----
            while not any(end in buf for end in self._HDR_ENDINGS):
                chunk = self.proc.stdout.buffer.read(1)
                if not chunk:
                    return  # EOF
                buf += chunk

            for ending in self._HDR_ENDINGS:
                if ending in buf:
                    header, _, buf = buf.partition(ending)
                    break
            m = self._CL_RE.search(header)
            if not m:
                debug("Header without Content-Length → ignored")
                continue
            length = int(m.group(1))

            # ---- body ----
            while len(buf) < length:
                chunk = self.proc.stdout.buffer.read(length - len(buf))
                if not chunk:
                    return
                buf += chunk
            body_bytes, buf = buf[:length], buf[length:]

            try:
                msg = json.loads(body_bytes.decode())
            except Exception as e:  # pragma: no cover
                debug(f"JSON parse error: {e}")
                continue

            # record responses or inspect notifications
            if isinstance(msg, dict) and "id" in msg:
                with self._lock:
                    self._responses[int(msg["id"])] = msg
            else:
                meth = msg.get("method")
                if meth == "window/showMessage":
                    text = msg["params"].get("message", "")
                    if "Finished loading packages" in text:
                        self._ready.set()
                elif meth == "textDocument/publishDiagnostics":
                    # spammy – ignore
                    pass
                else:
                    debug(f"Ignored notification: {meth}")

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _verify_workspace(path: str) -> None:
    if not os.path.isfile(os.path.join(path, "go.mod")):
        sys.exit("go.mod not found – are you mounting the right checkout?")

# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Extract Go symbols with gopls")
    parser.add_argument("--out", default=DEFAULT_OUT, help="Output JSON file")
    args = parser.parse_args()

    _verify_workspace(GO_WORKSPACE)

    # graceful Ctrl‑C
    signal.signal(signal.SIGINT, lambda *_: sys.exit(130))

    client = LSPClient(["gopls", "-mode=stdio"])

    root_uri = f"file://{GO_WORKSPACE}"
    init = client.send(
        "initialize",
        {
            "processId": os.getpid(),
            "rootUri": root_uri,
            "capabilities": {},
            "workspaceFolders": [{"uri": root_uri, "name": "erigon"}],
        },
    )
    if init is None:
        sys.exit("Failed to initialise gopls")

    client.notify("initialized", {})
    client.wait_until_ready()

    # Walk workspace
    debug("Scanning *.go files…")
    go_files = [
        os.path.join(dp, fn)
        for dp, _, files in os.walk(GO_WORKSPACE)
        for fn in files if fn.endswith(".go")
    ]
    debug(f"Found {len(go_files)} Go files.")

    functions: List[Dict[str, Any]] = []
    for idx, path in enumerate(go_files, 1):
        uri = f"file://{path}"
        debug(f"({idx}/{len(go_files)}) Symbols for {path}")
        res = client.send("textDocument/documentSymbol", {"textDocument": {"uri": uri}})
        if not res or "result" not in res:
            continue
        for sym in res["result"]:
            if sym.get("kind") in (12, 6):  # 12=function 6=method per LSP
                rng = sym.get("range") or sym.get("location", {}).get("range")
                functions.append({"name": sym["name"], "file": path, "range": rng})

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fp:
        json.dump(functions, fp, indent=2)
    debug(f"Wrote {len(functions)} entries to {args.out}.")

    client.close()

if __name__ == "__main__":
    main()
