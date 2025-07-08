#!/usr/bin/env python3
"""gen_breakpoints.py  –  Call‑graph slicing + Gemini ⇒ GDB script

v5 — **Full‑coverage edition** (2025‑06‑25)
==========================================
* **Dangling‑nodes pass** — after all true roots are processed we run a
  second BFS wave starting from any function that is still unvisited, so
  *every* node in the call‑graph appears in at least one prompt.
* **Robust Gemini parsing** — `ask_gemini()` now tolerates replies where
  `content` or `parts` are missing and falls back to `{}` instead of
  crashing (`TypeError: 'NoneType' object is not subscriptable`).
* Prompt format (indented tree + explicit arrows + code bodies) is
  unchanged from v4.
"""
from __future__ import annotations

import argparse, json, os, re, textwrap, time, datetime, importlib
from collections import deque
from pathlib import Path
from typing import Any, Dict, List

from google import genai
from google.genai.types import GenerateContentConfig

# ───────────────────────────── config ─────────────────────────────────────
PROMPT_DIR = Path("/module_prompts"); PROMPT_DIR.mkdir(parents=True, exist_ok=True)
DEBUG_DIR  = PROMPT_DIR / "debug";    DEBUG_DIR.mkdir(exist_ok=True)
MODEL_ID   = "gemini-2.5-flash-preview-05-20"
MAX_RETRIES = 3
BACKOFF_SEC = 2
DRY_RUN     = os.getenv("USE_LLM", "0") != "1"
API_KEY     = os.getenv("GEMINI_API_KEY", "")

# ─────────────────────────── utilities ────────────────────────────────────

def safe_name(s: str) -> str:
    return re.sub(r"[^0-9A-Za-z_\-]", "_", s)[:120]

# optional helper to extract code snippets
try:
    rmod = importlib.import_module("resolve_function_from_id")
    HAVE_RESOLVE = True
except ModuleNotFoundError:
    HAVE_RESOLVE = False


def code_snippet(fid: str, meta: Dict[str, Any], max_lines: int) -> str:
    if HAVE_RESOLVE and hasattr(rmod, "snippet"):
        try:
            rmod.load_meta()
            _p, txt = rmod.snippet(fid, ctx=0)
            return "\n".join(txt.splitlines()[:max_lines])
        except Exception:
            pass
    try:
        src = Path(meta["file"]).read_text().splitlines()
        s   = meta["range"]["start"]["line"]
        e   = meta["range"]["end"]["line"]
        return "\n".join(src[s:e+1][:max_lines])
    except Exception:
        return "(source unavailable)"

# ───────────────────── BFS slice helper ───────────────────────────────────

def bfs_slice_from_queue(Q: deque, cg, n, max_depth, visited, depth_map):
    slice_ids = []
    while Q and len(slice_ids) < n:
        node, d = Q.popleft()
        if node in visited or d > max_depth:
            continue
        visited.add(node)
        depth_map[node] = d
        slice_ids.append(node)
        for c in cg[node]["callees"]:
            if c not in visited:
                Q.append((c, d+1))
    return slice_ids

# ───────────────────── prompt builder ─────────────────────────────────────

def build_prompt(repo_sum: str, objective: str, context: str,
                 slice_ids: List[str], depth_map: Dict[str, int],
                 cg: Dict[str, Any], fn_meta: Dict[str, Any], *,
                 max_lines: int = 40) -> str:
    in_slice = set(slice_ids)
    blocks: List[str] = []

    for fid in sorted(slice_ids, key=lambda x: depth_map[x]):
        d      = depth_map[fid]
        indent = "  " * d
        ntyp   = cg[fid]["node_type"]
        code   = code_snippet(fid, fn_meta[fid], max_lines)
        kids   = [c for c in cg[fid]["callees"] if c in in_slice and depth_map.get(c) == d+1]
        arrow  = f"{indent}  → " + ", ".join(kids) if kids else ""
        indented_code = textwrap.indent(code, indent + "    ")
        block = f"{indent}• {fid} ({ntyp})"
        if arrow:
            block += f"\n{arrow}"
        block += f"\n{indented_code}"
        blocks.append(block)

    tree_block = "\n".join(blocks)

    return textwrap.dedent(f"""
        Objective:
        {objective}

        Repository summary:
        {repo_sum}

        Context:
        {context}

        Call graph slice (indented tree with code and explicit arrows):
        {tree_block}

        Respond ONLY with JSON:
        {{ "results": {{ "<func_id>": true/false, ... }} }}
    """).strip()

# ───────────────────── Gemini wrapper ─────────────────────────────────────

def ask_gemini(prompt: str, root_id: str):
    if DRY_RUN:
        return {}

    client = genai.Client(api_key=API_KEY)
    cfg = GenerateContentConfig(
        temperature=0.2, top_p=0.9, top_k=20, max_output_tokens=8192,
    )

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            rsp = client.models.generate_content(model=MODEL_ID, contents=prompt, config=cfg)
            # defensive extraction — candidates or content may be missing
            if not rsp.candidates:
                raise ValueError("Gemini replied without candidates")
            cand = rsp.candidates[0]
            parts = cand.content.parts if cand.content else []
            txt = next((p.text for p in parts if getattr(p, "text", None)), "").strip()
            if not txt:
                raise ValueError("Gemini reply empty or filtered")
            return json.loads(re.search(r"\{.*\}", txt, re.S).group(0)).get("results", {})
        except Exception as exc:
            # save raw for debugging then retry/back‑off
            ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            (DEBUG_DIR / f"RAW_{safe_name(root_id)}_{ts}.txt").write_text(str(exc))
            if attempt == MAX_RETRIES:
                print(f"⚠︎  giving up on {root_id} after {attempt} attempts → treating as no‑selection")
                return {}
            time.sleep(BACKOFF_SEC ** attempt)

# ───────────────────── breakpoint file writer ─────────────────────────────

def write_gdb_file(selected, fn_meta, cg, out_path, repo_root="/build"):
    skipped = 0
    with Path(out_path).open("w", encoding="utf-8") as fh:
        fh.write("# ---- auto-generated breakpoints ----\n")
        for fid in sorted(selected):
            meta = fn_meta.get(fid) or cg.get(fid)
            if not meta:
                skipped += 1
                continue                                  # no location info
            try:
                rel_path = Path(meta["file"]).relative_to(repo_root)
            except ValueError:
                rel_path = Path(meta["file"])              # absolute fallback
            line_no = meta["range"]["start"]["line"]

            # 1) line-based breakpoint
            fh.write(f"break {rel_path}:{line_no}\n")

            # 2) attach commands (indentation matches your reference)
            fh.write("commands\n")
            fh.write("  silent\n")
            fh.write("  python\n")
            fh.write("import gdb\n")
            fh.write("# remember the frame we hit\n")
            fh.write("start_frame = gdb.selected_frame().name()\n")
            fh.write("# keep stepping until we leave that frame\n")
            fh.write("while gdb.selected_frame().name() == start_frame:\n")
            fh.write("    gdb.execute('next')\n")
            fh.write("    gdb.execute('info line *$pc')\n")
            fh.write("# once we've left, resume normally\n")
            fh.write("gdb.execute('continue')\n")
            fh.write("  end\n")            # end of python block
            fh.write("end\n\n")            # end of commands block

    kept = len(selected) - skipped
    print(f"✓ wrote {kept} breakpoints → {out_path}  (skipped {skipped})")

# ───────────────────────────── main ───────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="Gemini‑assisted breakpoint picker (full coverage)")
    ap.add_argument("--callgraph",      default="/output/classified_callgraph.json", type=Path)
    ap.add_argument("--functions",      default="/output/functions.json",           type=Path)
    ap.add_argument("--repo-summary",   default="/output/repo_summary.txt",         type=Path)
    ap.add_argument("--objective-file", default="/prompt/objective.txt",            type=Path)
    ap.add_argument("--context-file",   default="/prompt/context.txt",              type=Path)
    ap.add_argument("--n", type=int, default=80)
    ap.add_argument("--depth", type=int, default=10)
    ap.add_argument("--max-lines", type=int, default=40)
    ap.add_argument("--out-gdb", default="/output/eip_breakpoints.gdb", type=Path)
    args = ap.parse_args()

    cg       = json.loads(args.callgraph.read_text())
    fn_meta  = {f["name"]: f for f in json.loads(args.functions.read_text())}
    repo_sum = args.repo_summary.read_text().strip()
    objective= args.objective_file.read_text().strip()
    context  = args.context_file.read_text().strip()

    visited: set[str] = set()
    depth_map: Dict[str, int] = {}
    selected: set[str] = set()

    def run_bfs_from_roots(root_ids: List[str]):
        for root in root_ids:
            queue = deque([(root, 0)])
            while queue:
                slice_ids = bfs_slice_from_queue(queue, cg, args.n, args.depth,
                                                 visited, depth_map)
                if not slice_ids:
                    break
                prompt = build_prompt(repo_sum, objective, context, slice_ids,
                                      depth_map, cg, fn_meta, max_lines=args.max_lines)
                (PROMPT_DIR / f"SLICE_{safe_name(root)}_{len(visited)}.txt").write_text(prompt)
                verdict = ask_gemini(prompt, root)
                selected.update(fid for fid, ok in verdict.items() if ok)
                # enqueue children for next round
                for fid in slice_ids:
                    nd = depth_map[fid]
                    for c in cg[fid]["callees"]:
                        if c not in visited and nd+1 <= args.depth:
                            queue.append((c, nd+1))
            print(f"root {root} done — selected so far: {len(selected)}")

    # 1) primary pass from true roots
    true_roots = [fid for fid, m in cg.items() if not m["callers"]]
    run_bfs_from_roots(true_roots)

    # 2) dangling‑nodes pass for full coverage
    dangling = [fid for fid in cg if fid not in visited]
    print(f"{len(dangling)} dangling nodes — launching second pass")
    run_bfs_from_roots(dangling)

    write_gdb_file(selected, fn_meta, cg, args.out_gdb)

if __name__ == "__main__":
    main()
