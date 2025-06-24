#!/usr/bin/env python3
"""
bidirectional_callgraph.py

Turn an LSP caller-only call-graph into a bi-directional call-graph.

Expected input files
--------------------
functions.json     # list[dict] from LSP: name / file / range:{start:{line}, end:{line}}
caller_only.json   # dict[str, list[{file, line}]]  – callee → list of call-sites

Output
------
bidirectional_callgraph.json
"""

import json
import argparse
from pathlib import Path
from collections import defaultdict
from bisect import bisect_left

# ---------- helpers --------------------------------------------------------- #

class IntervalIndex:
    """
    Per-file interval index:   line ∈ [start, end]  →  function_id
    Implemented with two parallel sorted lists (start_lines, entries)
    for O(log N) lookup via bisect.
    """
    def __init__(self):
        self.starts = []       # sorted list of start lines
        self.entries = []      # (end_line, func_id)

    def add(self, start: int, end: int, func_id: str):
        idx = bisect_left(self.starts, start)
        self.starts.insert(idx, start)
        self.entries.insert(idx, (end, func_id))

    def query(self, line: int):
        """
        Return func_id whose interval contains `line`, or None.
        """
        idx = bisect_left(self.starts, line)
        if idx == len(self.starts):
            idx -= 1
        # If bisect lands in the middle of an earlier start, step back one.
        if idx > 0 and self.starts[idx] > line:
            idx -= 1
        if idx >= 0:
            end, fid = self.entries[idx]
            if self.starts[idx] <= line <= end:
                return fid
        return None

# ---------- main ------------------------------------------------------------ #

def build_interval_indices(functions):
    """
    Return {file_path: IntervalIndex}  built from the raw function list.
    """
    per_file = defaultdict(IntervalIndex)
    for fn in functions:
        file_path = fn["file"]
        start_line = fn["range"]["start"]["line"]
        end_line   = fn["range"]["end"]["line"]
        per_file[file_path].add(start_line, end_line, fn["name"])
    return per_file


def main(fun_file: Path, cg_file: Path, out_file: Path):
    # ------------------------------------------------------------------ load
    functions = json.loads(fun_file.read_text())
    caller_only = json.loads(cg_file.read_text())

    # ---------------------------------------------------------------- indices
    interval_idx = build_interval_indices(functions)

    # master record for every function we know about
    func_meta = {
        fn["name"]: {
            "id":        fn["name"],
            "pkg":       str(Path(fn["file"]).parent),      # simple heuristic
            "file":      fn["file"],
            "range":     fn["range"],
            "callers":   set(),                             # to be filled
            "callees":   set(),                             # to be filled
        }
        for fn in functions
    }

    # -------------------------------------------------------------- add edges
    missing_sites = 0
    for callee, sites in caller_only.items():
        # ensure the callee is in the meta dict even if not in the function list
        if callee not in func_meta:
            func_meta[callee] = {
                "id": callee,
                "pkg": None,
                "file": None,
                "range": None,
                "callers": set(),
                "callees": set(),
            }

        for site in sites:
            fpath = site["file"]
            line  = site["line"]
            caller = interval_idx[fpath].query(line) if fpath in interval_idx else None

            if not caller:
                missing_sites += 1
                continue  # could not map call-site to a function

            # record caller → callee and callee ← caller
            func_meta[caller]["callees"].add(callee)
            func_meta[callee]["callers"].add(caller)

    # -------------------------------------------------------------- serialise
    # convert sets → sorted lists for JSON friendliness
    serialisable = {
        fid: {
            **meta,
            "callers": sorted(meta["callers"]),
            "callees": sorted(meta["callees"]),
        }
        for fid, meta in func_meta.items()
    }
    out_file.write_text(json.dumps(serialisable, indent=2))
    print(
        f"✓ wrote {len(serialisable):,} functions to {out_file}. "
        f"Unmatched call-sites: {missing_sites}"
    )


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Convert caller-only call-graph to bi-directional form.")
    ap.add_argument("--functions", default="functions.json", type=Path, help="Function list JSON")
    ap.add_argument("--callgraph", default="caller_only.json", type=Path,   help="Caller-only call-graph JSON")
    ap.add_argument("--out",       default="bidirectional_callgraph.json",  type=Path, help="Output JSON")
    args = ap.parse_args()

    main(args.functions, args.callgraph, args.out)
