#!/usr/bin/env python3
"""
Tiny disk-backed cache for module annotations.
"""
import json, pathlib

ANNOT_PATH = pathlib.Path("/output/module_annotations.json")
ANNOT_PATH.parent.mkdir(parents=True, exist_ok=True)   # ensure /output exists
_mem = json.loads(ANNOT_PATH.read_text()) if ANNOT_PATH.exists() else {}


# ---------------- public API ---------------- #

def has(fn_id: str) -> bool:
    return fn_id in _mem


def get(fn_id: str) -> str:
    return _mem[fn_id]["text"]


def put(fn_id: str, text: str, level: str) -> None:
    """
    level = "trunk" | "leaf" (future phases)
    """
    _mem[fn_id] = {"text": text, "level": level}
    ANNOT_PATH.write_text(json.dumps(_mem, indent=2))
