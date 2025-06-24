# resolve.py
import json
from pathlib import Path

FUNC_META = None          # loaded once
CODE_CACHE = {}           # tiny LRU is fine

def load_meta(func_json="functions.json"):
    global FUNC_META
    if FUNC_META is None:
        with open(func_json) as f:
            data = json.load(f)
        FUNC_META = {fn["name"]: fn for fn in data}

def snippet(func_id, ctx=3):
    """
    Return (file_path, code_str) for `func_id`, including ±ctx lines of padding.
    """
    meta = FUNC_META[func_id]
    fpath = Path(meta["file"]).resolve()
    if fpath not in CODE_CACHE:
        CODE_CACHE[fpath] = fpath.read_text().splitlines()

    lines = CODE_CACHE[fpath]
    s = max(0, meta["range"]["start"]["line"] - ctx)
    e = meta["range"]["end"]["line"] + ctx
    code = "\n".join(f"{i+1:>5} {lines[i]}"
                     for i in range(s, min(e, len(lines))))
    return str(fpath), code
