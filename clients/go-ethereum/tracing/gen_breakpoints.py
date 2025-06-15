#!/usr/bin/env python3
# gen_breakpoints.py  –  Step 4: call Gemini & collect YES functions

import argparse, json, sys, queue, re, textwrap, time, os
from pathlib import Path
from google import genai
from google.genai.types import GenerateContentConfig
import json, re, pathlib, datetime

# ---------- constants & dirs ------------------------------------------------
PROMPT_DIR = Path("/module_prompts"); PROMPT_DIR.mkdir(parents=True, exist_ok=True)
CTX_LINES  = 3
MAX_RETRIES = 3
BACKOFF_SEC = 2
MODEL_ID    = "gemini-2.5-flash-preview-05-20"
DRY_RUN     = os.getenv("USE_LLM", "0") != "1"
API_KEY     = os.getenv("GEMINI_API_KEY", "")

# ---------- helper funcs (unchanged bfs_slice + safe_name) -----------------
def bfs_slice(root_id, callgraph, n, max_depth, visited):
    out, q = [], queue.Queue(); q.put((root_id, 0))
    while not q.empty() and len(out) < n:
        node, d = q.get()
        if node in visited or d > max_depth: continue
        visited.add(node); out.append(node)
        for c in callgraph[node]["callees"]:
            q.put((c, d + 1))
    return out

def safe_name(s): return re.sub(r"[^0-9A-Za-z_\-]", "_", s)[:120]

def first_code_lines(meta, k=CTX_LINES):
    try:
        lines = Path(meta["file"]).read_text().splitlines()
        s, e = meta["range"]["start"]["line"], meta["range"]["end"]["line"]
        return "\n".join(lines[s : min(s + k, e)])
    except Exception:
        return "(source unavailable)"
    
DEBUG_DIR = PROMPT_DIR / "debug"; DEBUG_DIR.mkdir(exist_ok=True)

def extract_json(txt: str, fallback_file: pathlib.Path):
    """
    Try plain json.loads. If that fails, look for the first {...} block
    in triple-backticks or anywhere in the text.  Save raw text to
    fallback_file for debugging if still not parseable.
    """
    try:
        return json.loads(txt)
    except Exception:
        m = re.search(r"\{.*\}", txt, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                pass
        # save for manual inspection
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        fallback_file.write_text(txt)
        raise ValueError(f"Cannot parse JSON, raw saved → {fallback_file}")

# ---------- prompt builder (same as Step 3, just returns prompt) -----------
def build_prompt(repo_sum, mod_sum, objective, context, slice_ids, cg, fn_meta):
    bullets = []
    for fid in slice_ids:
        loc  = fn_meta[fid]
        ntyp = cg[fid]["node_type"]
        code = first_code_lines(loc)
        bullets.append(f"• {fid} ({ntyp}):\n    {code}")
    funcs_block = "\n".join(bullets)

    return textwrap.dedent(f"""
        Objective:
        {objective}

        Repository summary:
        {repo_sum}

        Module summary:
        {mod_sum}

        Context:
        {context[:4000]}

        Candidate functions ({len(slice_ids)}):
        {funcs_block}

        Respond exactly as JSON:
        {{ "results": {{ "<func_id>": true/false, ... }} }}
    """).strip()

# ---------- NEW: Gemini call with retry ------------------------------------
def shrink_prompt(prompt, factor=0.5):
    """Remove code lines to shrink prompt size on retry."""
    parts = prompt.split("Candidate functions", 1)
    if len(parts) != 2:
        return prompt
    header, body = parts
    lines = body.splitlines()
    keep = int(len(lines) * factor)
    return header + "Candidate functions (trimmed):\n" + "\n".join(lines[:keep])

def ask_gemini_retry(prompt, root_id):
    if DRY_RUN:
        # Stub out: mark everything false
        return {}
    client = genai.Client(api_key=API_KEY)
    cfg = GenerateContentConfig(temperature=0.2, top_p=0.9, top_k=20, max_output_tokens=8192)

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            rsp = client.models.generate_content(model=MODEL_ID, contents=prompt, config=cfg)
            txt = rsp.candidates[0].content.parts[0].text.strip()
            fallback = DEBUG_DIR / f"BAD_{safe_name(root_id)}.txt"
            data = extract_json(txt, fallback)
            return data["results"]
        except Exception as exc:
            if attempt == MAX_RETRIES:
                raise
            time.sleep(BACKOFF_SEC ** attempt)
            # prompt = shrink_prompt(prompt)

# ---------- main -----------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="Step 4: Gemini yes/no for first root slice")
    ap.add_argument("--callgraph", default="/output/classified_callgraph.json", type=Path)
    ap.add_argument("--functions", default="/output/functions.json", type=Path)
    ap.add_argument("--repo-summary", default="/output/repo_summary.txt", type=Path)
    ap.add_argument("--module-summaries", default="/output/module_summaries.json", type=Path)
    ap.add_argument("--objective-file", default="/prompt/objective.txt", type=Path)
    ap.add_argument("--context-file",   default="/prompt/context.txt",   type=Path)
    ap.add_argument("--n", type=int, default=80)
    ap.add_argument("--depth", type=int, default=10)
    args = ap.parse_args()

    cg   = json.loads(args.callgraph.read_text())
    fn_meta = {f["name"]: f for f in json.loads(args.functions.read_text())}
    repo_sum = args.repo_summary.read_text().strip()
    mod_sums = json.loads(args.module_summaries.read_text())
    objective = args.objective_file.read_text().strip()
    context   = args.context_file.read_text().strip()

    roots   = [fid for fid,m in cg.items() if not m["callers"]]
    visited = set()
    selected = set()

    root = roots[0]                                 # FIRST root only
    slice_ids = bfs_slice(root, cg, args.n, args.depth, visited)

    mod_sum = mod_sums.get(cg[root]["pkg"], "(module summary missing)")
    prompt  = build_prompt(repo_sum, mod_sum, objective, context,
                           slice_ids, cg, fn_meta)

    pfile = PROMPT_DIR / f"SLICE_{safe_name(root)}.txt"
    pfile.write_text(prompt)
    print(f"📄 prompt saved ({len(slice_ids)} funcs) → {pfile}")

    # ----- Gemini call -----------------------------------------------------
    verdict = ask_gemini_retry(prompt, root)
    yes_ids = [fid for fid, ok in verdict.items() if ok]
    selected.update(yes_ids)
    print(f"✅ Gemini returned YES for {len(yes_ids)} / {len(slice_ids)} functions")

    # summary
    print("Currently selected funcs:", len(selected))
    sys.exit(0)

if __name__ == "__main__":
    main()
