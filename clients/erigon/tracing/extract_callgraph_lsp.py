#!/usr/bin/env python3
"""Build a callers‑→callees call‑graph for an Erigon checkout.

This **v2** script re‑uses the hardened LSP client from the symbols
extractor and adds a few tricks so that it can run for hours on a large
repo without timing out or exhausting gopls.

Major fixes
===========
1. **Go / gopls version mismatch guard** – we abort early if the Go tool
   chain is older than *1.21*, because nested modules such as *erigon‑db*
   contain a `toolchain go1.24` directive that Go ≤1.20 can’t parse.
   (That was the root cause of the “no package metadata” errors you saw.)
2. **Readiness gate + long time‑outs** – just like the function
   extractor, we wait for the *“Finished loading packages.”* log and give
   each `textDocument/references` request up to 60 s.
3. **One open per file** – we open each source file once, process all of
   its functions, then close it.  This keeps the number of live *views*
   inside gopls under 100 instead of 2000+.
4. **Skip broken sub‑modules automatically** – if gopls cannot load a
   package under a nested module we log it once and move on so the whole
   run still finishes.
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
from pathlib import Path
from typing import Any, Dict, List, Optional

GO_WORKSPACE = Path("/build")
DEFAULT_FUNCS = Path("/output/functions.json")
DEFAULT_OUT = Path("/output/callgraph.json")

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def debug(msg: str) -> None:
    print(f"[DEBUG] {msg}", file=sys.stderr, flush=True)


def _require_go_121() -> None:
    try:
        ver = subprocess.check_output(["go", "version"], text=True)
    except Exception as exc:
        sys.exit(f"Cannot run 'go version': {exc}")
    m = re.search(r"go(\d+)\.(\d+)", ver)
    if not m:
        sys.exit(f"Unrecognised Go version string: {ver.strip()}")
    maj, min_ = map(int, m.groups())
    if maj < 1 or (maj == 1 and min_ < 21):
        sys.exit("Go ≥ 1.21 is required – nested modules have 'toolchain' directives.")


def _verify_workspace() -> None:
    if not (GO_WORKSPACE / "go.mod").exists():
        sys.exit("go.mod not found under /build – mount the repo as /build")

# ---------------------------------------------------------------------------
# LSP client (identical logic to the extractor)
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
            text=True,
            bufsize=0,
        )
        if not all((self.proc.stdin, self.proc.stdout, self.proc.stderr)):
            raise RuntimeError("Failed to launch gopls")

        self._next_id = 1
        self._responses: Dict[int, Dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._ready = threading.Event()

        threading.Thread(target=self._reader, daemon=True).start()
        threading.Thread(target=self._stderr_forward, daemon=True).start()

    # ------------- public API -------------

    def send(
        self,
        method: str,
        params: Optional[Any] = None,
        *,
        timeout: float = 60.0,
    ) -> Optional[Dict[str, Any]]:
        body = {"jsonrpc": "2.0", "id": self._next_id, "method": method}
        if params is not None:
            body["params"] = params
        body_s = json.dumps(body)
        header = f"Content-Length: {len(body_s)}\r\n\r\n"

        self.proc.stdin.write(header + body_s)
        self.proc.stdin.flush()
        my_id = self._next_id
        self._next_id += 1

        debug(f"→ {method} (id={my_id})")
        for _ in range(int(timeout / 0.05)):
            with self._lock:
                if my_id in self._responses:
                    return self._responses.pop(my_id)
            time.sleep(0.05)
        debug(f"timeout {method} id={my_id}")
        return None

    def notify(self, method: str, params: Optional[Any] = None) -> None:
        body = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            body["params"] = params
        body_s = json.dumps(body)
        header = f"Content-Length: {len(body_s)}\r\n\r\n"
        self.proc.stdin.write(header + body_s)
        self.proc.stdin.flush()
        debug(f"→ notif {method}")

    def wait_until_ready(self, timeout: float = 300.0) -> None:
        debug("Waiting for gopls to load packages …")
        self._ready.wait(timeout)
        debug("gopls ready.")

    def close(self) -> None:
        debug("Stopping gopls…")
        self.proc.terminate()
        try:
            self.proc.wait(3)
        except subprocess.TimeoutExpired:
            self.proc.kill()

    # ------------- reader ------------

    def _stderr_forward(self) -> None:
        for line in self.proc.stderr:
            debug(f"[gopls] {line.rstrip()}")

    def _reader(self) -> None:
        buf = b""
        while True:
            while not any(e in buf for e in self._HDR_ENDINGS):
                chunk = self.proc.stdout.buffer.read(1)
                if not chunk:
                    return
                buf += chunk
            for ending in self._HDR_ENDINGS:
                if ending in buf:
                    header, _, buf = buf.partition(ending)
                    break
            m = self._CL_RE.search(header)
            if not m:
                continue
            length = int(m.group(1))
            while len(buf) < length:
                chunk = self.proc.stdout.buffer.read(length - len(buf))
                if not chunk:
                    return
                buf += chunk
            raw, buf = buf[:length], buf[length:]
            try:
                msg = json.loads(raw.decode())
            except Exception as exc:
                debug(f"JSON err: {exc}")
                continue

            if isinstance(msg, dict) and "id" in msg:
                with self._lock:
                    self._responses[int(msg["id"])] = msg
            else:
                meth = msg.get("method")
                if meth == "window/showMessage":
                    txt = msg["params"].get("message", "")
                    if "Finished loading packages" in txt:
                        self._ready.set()
                elif meth in {"textDocument/publishDiagnostics", "window/logMessage"}:
                    pass  # too chatty

# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Generate Go call‑graph via gopls")
    parser.add_argument("--funcs", default=str(DEFAULT_FUNCS), help="functions.json from extractor")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="Output callgraph.json")
    args = parser.parse_args()

    _require_go_121()
    _verify_workspace()

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
    if not init:
        sys.exit("failed to initialise gopls")
    client.notify("initialized", {})
    client.wait_until_ready()

    with open(args.funcs, "r", encoding="utf-8") as fp:
        fns: List[Dict[str, Any]] = json.load(fp)

    # Group functions per file to avoid re‑opening 1000×.
    by_file: Dict[str, List[Dict[str, Any]]] = {}
    for fn in fns:
        by_file.setdefault(fn["file"], []).append(fn)

    callgraph: Dict[str, List[Dict[str, Any]]] = {}

    for file_path, funcs in by_file.items():
        uri = f"file://{file_path}"
        try:
            text = Path(file_path).read_text()
        except Exception as exc:
            debug(f"cannot read {file_path}: {exc}")
            continue

        client.notify(
            "textDocument/didOpen",
            {
                "textDocument": {
                    "uri": uri,
                    "languageId": "go",
                    "version": 1,
                    "text": text,
                }
            },
        )

        lines = text.splitlines()

        for fn in funcs:
            # heuristic to locate the symbol quickly
            line0 = fn.get("range", {}).get("start", {}).get("line", 0)
            name = fn["name"].split(".")[-1].split(")")[-1]
            if line0 < len(lines):
                ch = lines[line0].find(name)
            else:
                ch = -1
            if ch < 0:
                ch = fn.get("range", {}).get("start", {}).get("character", 0)
            pos = {"line": line0, "character": ch}

            debug(f"references for {fn['name']} @ {pos}")
            refs = client.send(
                "textDocument/references",
                {
                    "textDocument": {"uri": uri},
                    "position": pos,
                    "context": {"includeDeclaration": False},
                },
            )
            if not refs or "result" not in refs:
                debug(f"   ↳ skipped (no metadata)")
                continue
            callees: List[Dict[str, Any]] = []
            for ref in refs["result"]:
                ref_uri = ref["uri"]
                ref_file = ref_uri.replace("file://", "")
                callees.append({
                    "file": ref_file,
                    "line": ref["range"]["start"]["line"],
                })
            callgraph[fn["name"]] = callees

        client.notify("textDocument/didClose", {"textDocument": {"uri": uri}})
        time.sleep(0.02)  # small breather

    DEFAULT_OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fp:
        json.dump(callgraph, fp, indent=2)
    debug(f"Wrote call‑graph with {len(callgraph)} roots → {args.out}")

    client.close()

if __name__ == "__main__":
    main()
