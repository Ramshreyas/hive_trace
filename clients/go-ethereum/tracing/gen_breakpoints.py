#!/usr/bin/env python3
"""
gen_breakpoints.py – full BFS traversal, Gemini yes/no, GDB file emit.
Usage example (inside container):

export USE_LLM=1
export GEMINI_API_KEY="AIza..."
python3 gen_breakpoints.py \
        --callgraph /output/classified_callgraph.json \
        --objective-file /prompt/objective.txt \
        --context-file /prompt/context.txt \
        --n 80 --depth 10 \
        --out-gdb /output/eip_breakpoints.gdb
"""

import argparse, json, os, queue, re, textwrap, time, datetime
from collections import deque
from pathlib import Path
from google import genai
from google.genai.types import GenerateContentConfig

# ───────── constants & dirs ────────────────────────────────────────────────
PROMPT_DIR  = Path("/module_prompts"); PROMPT_DIR.mkdir(parents=True, exist_ok=True)
DEBUG_DIR   = PROMPT_DIR / "debug";    DEBUG_DIR.mkdir(exist_ok=True)
CTX_LINES   = 3
MAX_RETRIES = 3
BACKOFF_SEC = 2
MODEL_ID    = "gemini-2.5-flash-preview-05-20"
DRY_RUN     = os.getenv("USE_LLM", "0") != "1"
API_KEY     = os.getenv("GEMINI_API_KEY", "")

# ───────── helper: identifiers & code lines ───────────────────────────────
def safe_name(s: str) -> str:
    return re.sub(r"[^0-9A-Za-z_\-]", "_", s)[:120]

def first_code_lines(meta, k=CTX_LINES):
    try:
        lines = Path(meta["file"]).read_text().splitlines()
        s, e = meta["range"]["start"]["line"], meta["range"]["end"]["line"]
        return "\n".join(lines[s : min(s + k, e)]).strip()
    except Exception:
        return "(source unavailable)"

def candidate_text(rsp):
    """Return first text part or empty string if none."""
    try:
        cand = rsp.candidates[0]
        if cand.content and cand.content.parts:
            # find the first part that has a .text field
            for p in cand.content.parts:
                if getattr(p, "text", None):
                    return p.text
    except Exception:
        pass
    return ""

# ───────── BFS from an existing queue (level order) ───────────────────────
def bfs_slice_from_queue(Q: deque, cg, n, max_depth, visited, depth_map):
    slice_ids = []
    while Q and len(slice_ids) < n:
        node, d = Q.popleft()
        if node in visited or d > max_depth:
            continue
        visited.add(node); slice_ids.append(node); depth_map[node] = d
        for c in cg[node]["callees"]:
            if c not in visited:
                Q.append((c, d + 1))
    return slice_ids

# ───────── prompt builder (indented bullet tree) ───────────────────────────
def build_prompt(repo_sum, mod_sum, objective, context,
                 slice_ids, depth_map, cg, fn_meta):
    """Produce an indented tree where indentation = depth from root."""
    lines = []
    for fid in sorted(slice_ids, key=lambda x: depth_map[x]):
        indent = "  " * depth_map[fid]               # two spaces per depth
        loc    = fn_meta[fid]
        ntyp   = cg[fid]["node_type"]
        code   = first_code_lines(loc)
        lines.append(f"{indent}• {fid} ({ntyp}): {code}")
    tree_block = "\n".join(lines)

    return textwrap.dedent(f"""
        Objective:
        {objective}

        Repository summary:
        {repo_sum}

        Module summary:
        {mod_sum}

        Context:
        {context[:4000]}

        Call graph slice (indented tree):
        {tree_block}

        Respond ONLY with JSON:
        {{ "results": {{ "<func_id>": true/false, ... }} }}
    """).strip()

# ───────── JSON extraction ────────────────────────────────────────────────
def extract_json(txt: str, fallback_file: Path):
    try:
        return json.loads(txt)
    except Exception:
        m = re.search(r"\{.*\}", txt, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                pass
        fallback_file.write_text(txt)
        raise ValueError(f"Cannot parse JSON, raw saved → {fallback_file}")

# ───────── Gemini call with retry (no prompt-shrink) ──────────────────────
def ask_gemini_retry(prompt: str, root_id: str):
    """
    Send `prompt` to Gemini up to MAX_RETRIES times.
    • On success, returns dict {"func_id": true/false, ...}
    • On empty / malformed replies, retries after an exponential back-off.
    • Saves the last raw response (or exception) to /module_prompts/debug/RAW_*.json
      when a retry is triggered, so you can inspect safety-filter details.
    """
    if DRY_RUN:
        return {}                              # all false in dry-run mode

    client = genai.Client(api_key=API_KEY)
    cfg = GenerateContentConfig(
        temperature=0.2, top_p=0.9, top_k=20, max_output_tokens=8195
    )

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            rsp = client.models.generate_content(
                model=MODEL_ID, contents=prompt, config=cfg
            )

            txt = candidate_text(rsp).strip()  # "" when safety-filtered
            if not txt:
                raise RuntimeError("empty reply (likely safety-filtered)")

            fallback = DEBUG_DIR / f"BAD_{safe_name(root_id)}.txt"
            data = extract_json(txt, fallback)
            return data.get("results", {})

        except Exception as exc:
            # save the full response or exception for post-mortem
            ts   = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            dump = DEBUG_DIR / f"RAW_{safe_name(root_id)}_{ts}.json"
            try:
                dump.write_text(json.dumps(rsp.model_dump(), indent=2))
            except Exception:
                dump.write_text(str(exc))

            if attempt == MAX_RETRIES:
                raise RuntimeError(
                    f"Gemini failed after {MAX_RETRIES} attempts; "
                    f"last raw saved → {dump}"
                ) from exc

            time.sleep(BACKOFF_SEC ** attempt)   # exponential back-off

# ───────── breakpoint writer (reference formatting) ───────────────────────
def write_gdb_file(selected_ids, fn_meta, cg, out_path, repo_root="/build"):
    skipped = 0
    with Path(out_path).open("w", encoding="utf-8") as out:
        out.write("# ---- auto-generated breakpoints ----\n")
        for fid in sorted(selected_ids):
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
            out.write(f"break {rel_path}:{line_no}\n")

            # 2) attach commands (indentation matches your reference)
            out.write("commands\n")
            out.write("  silent\n")
            out.write("  python\n")
            out.write("import gdb\n")
            out.write("# remember the frame we hit\n")
            out.write("start_frame = gdb.selected_frame().name()\n")
            out.write("# keep stepping until we leave that frame\n")
            out.write("while gdb.selected_frame().name() == start_frame:\n")
            out.write("    gdb.execute('next')\n")
            out.write("    gdb.execute('info line *$pc')\n")
            out.write("# once we’ve left, resume normally\n")
            out.write("gdb.execute('continue')\n")
            out.write("  end\n")            # end of python block
            out.write("end\n\n")            # end of commands block

    kept = len(selected_ids) - skipped
    print(f"✓ wrote {kept} breakpoints → {out_path}  (skipped {skipped})")

# ───────── main ───────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser(description="Generate GDB breakpoints via BFS + Gemini")
    ap.add_argument("--callgraph", default="/output/classified_callgraph.json", type=Path)
    ap.add_argument("--functions", default="/output/functions.json",           type=Path)
    ap.add_argument("--repo-summary", default="/output/repo_summary.txt",      type=Path)
    ap.add_argument("--module-summaries", default="/output/module_summaries.json", type=Path)
    ap.add_argument("--objective-file", default="/prompt/objective.txt", type=Path)
    ap.add_argument("--context-file",   default="/prompt/context.txt",   type=Path)
    ap.add_argument("--n", type=int, default=80)
    ap.add_argument("--depth", type=int, default=10)
    ap.add_argument("--out-gdb", default="/output/eip_breakpoints.gdb", type=Path)
    args = ap.parse_args()

    cg        = json.loads(args.callgraph.read_text())
    fn_meta   = {f["name"]: f for f in json.loads(args.functions.read_text())}
    repo_sum  = args.repo_summary.read_text().strip()
    mod_sums  = json.loads(args.module_summaries.read_text())
    objective = args.objective_file.read_text().strip()
    context   = args.context_file.read_text().strip()

    roots     = [fid for fid,m in cg.items() if not m["callers"]]
    visited   = set()
    selected  = set()
    depth_map = {}

    for root in roots:
        Q = deque([(root,0)])
        while Q:
            slice_ids = bfs_slice_from_queue(Q, cg, args.n, args.depth,
                                             visited, depth_map)
            if not slice_ids:
                break
            mod_sum = mod_sums.get(cg[root]["pkg"],
                                   "(module summary missing)")
            prompt  = build_prompt(repo_sum, mod_sum, objective, context,
                                   slice_ids, depth_map, cg, fn_meta)
            pfile = PROMPT_DIR / f"SLICE_{safe_name(root)}_{len(visited)}.txt"
            pfile.write_text(prompt)
            verdict = ask_gemini_retry(prompt, root)
            yes_ids = [fid for fid, ok in verdict.items() if ok]
            selected.update(yes_ids)
            # enqueue children of current slice for BFS
            for fid in slice_ids:
                d = depth_map.get(fid, 0)
                for child in cg[fid]["callees"]:
                    if child not in visited and d+1 <= args.depth:
                        Q.append((child, d+1))
        print(f"root {root} done  –  total selected so far: {len(selected)}")

    # emit GDB breakpoint file
    write_gdb_file(selected, fn_meta, cg, args.out_gdb)

if __name__ == "__main__":
    main()
