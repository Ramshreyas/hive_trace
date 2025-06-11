#!/usr/bin/env python3
"""
annotate_trunks.py  – Phase-4 trunk annotations (Gemini)

Inputs
------
/output/module_flows_ranked.json   (Phase-3 + ranking)
/output/bidirectional_callgraph.json
/output/functions.json
/output/repo_summary.txt
/output/module_summaries.json

Outputs
-------
/module_prompts/*.txt              (prompt inspection)
/output/module_annotations.json     (via llm_cache.py)
"""

import os, json, pathlib, re, textwrap
from google import genai
from google.genai.types import GenerateContentConfig
import resolve_function_from_id as rfi
import llm_cache
import json, datetime
from google.protobuf.json_format import MessageToDict

# ─── Paths ──────────────────────────────────────────────────────────────── #
FLOWS_FILE   = pathlib.Path("/output/module_flows_ranked.json")
CALLGRAPH_FILE = pathlib.Path("/output/bidirectional_callgraph.json")
FUNC_FILE    = pathlib.Path("/output/functions.json")
REPO_SUM     = pathlib.Path("/output/repo_summary.txt").read_text().strip()
MOD_SUMS     = json.loads(pathlib.Path("/output/module_summaries.json").read_text())

PROMPT_DIR   = pathlib.Path("/module_prompts")
PROMPT_DIR.mkdir(exist_ok=True)

DEBUG_DIR = PROMPT_DIR / "debug"
DEBUG_DIR.mkdir(exist_ok=True)

# ─── Runtime flags ──────────────────────────────────────────────────────── #
CTX_LINES = 3
TOP_K     = 10                          # trunks per module
DRY_RUN   = os.getenv("USE_LLM", "0") != "1"
API_KEY   = os.getenv("GEMINI_API_KEY")
MODEL_ID  = "gemini-2.5-flash-preview-05-20"

# ─── Load once ──────────────────────────────────────────────────────────── #
flows      = json.loads(FLOWS_FILE.read_text())
callgraph  = json.loads(CALLGRAPH_FILE.read_text())
rfi.load_meta(str(FUNC_FILE))           # fills rfi.FUNC_META

# ─── Helpers ────────────────────────────────────────────────────────────── #
def safe_fname(s: str) -> str:
    return re.sub(r"[^0-9A-Za-z_\-]", "_", s)[:120] + ".txt"

def save_prompt(fn_id: str, prompt: str) -> pathlib.Path:
    p = PROMPT_DIR / safe_fname(fn_id)
    p.write_text(prompt)
    return p

def build_prompt(mod_path, fn_label, callers, callees, code) -> str:
    mod_summary = MOD_SUMS.get(mod_path, "(module summary missing)")
    callers_str = ", ".join(callers) if callers else "(root)"
    callees_str = ", ".join(callees) if callees else "(leaf)"

    return textwrap.dedent(f"""
        Repository overview:
        {REPO_SUM}

        Module summary ({mod_path}):
        {mod_summary}

        Function under review: {fn_label}
        Callers: {callers_str}
        Callees: {callees_str}

        Source (±{CTX_LINES} lines):
        ----------------------------
        {code}

        In ONE concise sentence, describe the function’s role within this module.
    """).strip()

import json, datetime

def ask_gemini(fn_id: str, prompt: str) -> str:
    client = genai.Client(api_key=API_KEY)
    rsp = client.models.generate_content(
        model=MODEL_ID,
        contents=prompt,
        config=GenerateContentConfig(
            temperature=0.2,
            top_p=0.95,
            top_k=20,
            max_output_tokens=8192,
        ),
    )

    # Extract any text fragments
    try:
        parts = rsp.candidates[0].content.parts
        out   = " ".join(p.text for p in parts if getattr(p, "text", None)).strip()
    except Exception:
        out = ""

    if not out:
        ts   = datetime.datetime.now(datetime.UTC).strftime("%Y%m%d_%H%M%S")
        base = DEBUG_DIR / f"{safe_fname(fn_id)}_{ts}"

        # save prompt
        (base.with_suffix(".prompt.txt")).write_text(prompt)

        # serialise protobuf response safely
        raw_json = json.dumps(rsp.model_dump(), indent=2)
        (base.with_suffix(".gemini.json")).write_text(raw_json)

        print(f"🚨 Gemini empty for {fn_id}. Debug saved under {base.name}.*")
        raise RuntimeError(f"Gemini returned empty output for {fn_id}")

    return out


# ─── Main loop ──────────────────────────────────────────────────────────── #
if DRY_RUN:
    print("🔹 DRY-RUN (prompts only, no API calls)\n")

for mod_path, mod_data in flows.items():
    ranked = mod_data["ranked_trunks"][:TOP_K]

    # quick lookup for SCC members in this module
    scc_map = mod_data.get("scc_members", {})

    for fn_id, _score in ranked:
        if llm_cache.has(fn_id):
            continue

        # ── Handle SCC nodes ──────────────────────────────────────────── #
        if fn_id.startswith("SCC::"):
            members = scc_map.get(fn_id, [])
            if not members:
                llm_cache.put(fn_id, "(empty SCC)", level="trunk")
                continue

            repr_id = members[0]                       # first member for code
            _, code = rfi.snippet(repr_id, ctx=CTX_LINES)

            callers, callees = [], []
            for m in members:
                meta = callgraph.get(m, {})
                callers += meta.get("callers", [])
                callees += meta.get("callees", [])
            callers, callees = sorted(set(callers)), sorted(set(callees))

            fn_label = f"{fn_id} (SCC, repr {repr_id})"
        else:
            # ── Normal single function ──────────────────────────────── #
            meta = callgraph.get(fn_id, {})
            callers = meta.get("callers", [])
            callees = meta.get("callees", [])
            _, code = rfi.snippet(fn_id, ctx=CTX_LINES)
            fn_label = fn_id

        prompt = build_prompt(mod_path, fn_label, callers, callees, code)
        p_file = save_prompt(fn_id, prompt)
        print(f"📄 prompt → {p_file}")

        if DRY_RUN:
            llm_cache.put(fn_id, "(TODO trunk annotation)", level="trunk")
            continue

        try:
            sentence = ask_gemini(fn_id, prompt)
        except Exception as exc:
            print(f"⚠️  Gemini error for {fn_id}: {exc}")
            sentence = "(API error)"
        llm_cache.put(fn_id, sentence, level="trunk")
        print(f"✅ cached trunk annotation for {fn_id}")
