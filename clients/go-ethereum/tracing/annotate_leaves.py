#!/usr/bin/env python3
"""
annotate_leaves.py  – retry-aware Gemini leaf annotator
-------------------------------------------------------

USAGE
-----
# re-try only the previously failed leaves
python3 annotate_leaves.py --retry-only

# normal run (failed leaves first, then new ones)
python3 annotate_leaves.py
"""

import os, json, pathlib, textwrap, re, itertools, time, argparse
from google import genai
from google.genai.types import GenerateContentConfig

import resolve_function_from_id as rfi
import llm_cache

# ─── Config ──────────────────────────────────────────────────────────── #
CTX_LINES     = 3
MAX_RETRIES   = 3
BACKOFF_SEC   = 2
SUCCESS_SLEEP = 0.0          # set to e.g. 0.3 if you hit sustained 429s
TOP_PATHS     = 200
MODEL_ID      = "gemini-2.5-flash-preview-05-20"
API_KEY       = os.getenv("GEMINI_API_KEY", "")
DRY_RUN       = os.getenv("USE_LLM", "0") != "1"

FLOWS_FILE    = pathlib.Path("/output/module_flows_ranked.json")
FUNC_FILE     = pathlib.Path("/output/functions.json")
REPO_SUM_FILE = pathlib.Path("/output/repo_summary.txt")
MOD_SUM_FILE  = pathlib.Path("/output/module_summaries.json")
PROMPT_DIR    = pathlib.Path("/module_prompts"); PROMPT_DIR.mkdir(exist_ok=True)

# ─── Utility helpers ──────────────────────────────────────────────────── #
def safe_name(s): return re.sub(r"[^0-9A-Za-z_\-]", "_", s)[:120] + ".txt"

def shrink_code(code_block: str, keep: int):
    lines = code_block.splitlines()
    return "\n".join(lines[: keep * 2 + 10])

def gather_failed_ids():
    """Return set of ids whose cached text starts with '(API error' or '(TODO'"""
    failed = set()
    for fid, meta in llm_cache._mem.items():
        if meta["text"].startswith("(API error") or meta["text"].startswith("(TODO"):
            failed.add(fid)
    return failed

# ─── Gemini call with retry ──────────────────────────────────────────── #
def ask_gemini(prompt: str):
    client = genai.Client(api_key=API_KEY)
    cfg = GenerateContentConfig(
        temperature=0.2, top_p=0.9, top_k=20, max_output_tokens=8192
    )
    local_ctx = CTX_LINES
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            rsp = client.models.generate_content(model=MODEL_ID, contents=prompt, config=cfg)
            parts = rsp.candidates[0].content.parts
            text = " ".join(p.text for p in parts if getattr(p, "text", None)).strip()
            if text:
                return text
            raise RuntimeError("empty response")
        except Exception as exc:
            if attempt == MAX_RETRIES:
                raise
            time.sleep(BACKOFF_SEC ** attempt)
            local_ctx = max(1, local_ctx // 2)
            prompt = shrink_code(prompt, local_ctx)

# ─── Prompt builders ─────────────────────────────────────────────────── #
REPO_SUM = REPO_SUM_FILE.read_text().strip()
MOD_SUMS = json.loads(MOD_SUM_FILE.read_text())

def build_prompt(mod_path, leaf_id, leaf_code, anc_lines):
    anc = "\n".join(f"- {s}" for s in anc_lines) or "(none)"
    return textwrap.dedent(f"""
        Repository overview:
        {REPO_SUM}

        Module summary:
        {MOD_SUMS.get(mod_path, '(module summary missing)')}

        Ancestor context (trunks):
        {anc}

        Leaf function: {leaf_id}
        Source (±{CTX_LINES} lines):
        ----------------------------
        {leaf_code}

        In **one or two** concise sentences, explain what this function does
        and why it exists within the module.
    """).strip()

def save_prompt(leaf_id, prompt):
    p = PROMPT_DIR / safe_name(f"LEAF_{leaf_id}")
    p.write_text(prompt)
    return p

def ancestor_sentences(path):
    return [llm_cache.get(fid) for fid in path[:-1] if llm_cache.has(fid)]

# ─── Main driver ─────────────────────────────────────────────────────── #
def run(retry_only=False):
    flows = json.loads(FLOWS_FILE.read_text())
    rfi.load_meta(str(FUNC_FILE))

    # Priority queue: failed-first
    failed_ids = gather_failed_ids()

    if DRY_RUN:
        print("🔹 DRY-RUN – prompts only, no Gemini calls\n")

    # Pass 1 –- retry queue
    for fid in list(failed_ids):
        process_leaf_id(fid, flows, retry_only=retry_only)

    # Pass 2 –- fresh leaves
    if not retry_only:
        for mod_path, data in flows.items():
            for path in itertools.islice(data["paths"], TOP_PATHS):
                fid = path[-1]
                if fid.startswith("SCC::") or llm_cache.has(fid):
                    continue
                process_leaf_path(mod_path, path)

def process_leaf_id(fid, flows, retry_only=False):
    # Find the module + one path that ends with this fid
    for mod_path, data in flows.items():
        match = next((p for p in data["paths"] if p[-1] == fid), None)
        if match:
            process_leaf_path(mod_path, match, force=True)
            break

def process_leaf_path(mod_path, path, force=False):
    leaf_id = path[-1]
    if not force and llm_cache.has(leaf_id):
        return                           # already annotated
    anc_lines = ancestor_sentences(path)
    _, code = rfi.snippet(leaf_id, ctx=CTX_LINES)
    prompt = build_prompt(mod_path, leaf_id, code, anc_lines)
    save_prompt(leaf_id, prompt)
    if DRY_RUN:
        llm_cache.put(leaf_id, "(TODO leaf annotation)", level="leaf")
        return
    try:
        ans = ask_gemini(prompt)
        if SUCCESS_SLEEP:
            time.sleep(SUCCESS_SLEEP)
    except Exception as exc:
        llm_cache.put(leaf_id, f"(API error: {exc})", level="leaf")
        print(f"⚠️  {leaf_id}: {exc}")
        return
    llm_cache.put(leaf_id, ans, level="leaf")
    print(f"✅ {leaf_id}")

# ─── CLI entry-point ─────────────────────────────────────────────────── #
if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--retry-only", action="store_true",
                    help="re-annotate leaves with API-error/TODO only")
    args = ap.parse_args()
    run(retry_only=args.retry_only)
