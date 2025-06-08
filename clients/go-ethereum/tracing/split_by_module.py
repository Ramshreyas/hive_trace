#!/usr/bin/env python3
"""
split_modules.py  – Phase-2 of the call-graph pipeline
-----------------------------------------------------

Goal
----
Break the classified, bidirectional call-graph into per-module
sub-graphs and record every call that crosses a module boundary.

Input (default):   classified_callgraph.json
Outputs (default):
    • module_subgraphs.json     – one small graph per module
    • module_dependencies.json  – list of cross-module call counts
"""

import json
import argparse
from pathlib import Path
from collections import defaultdict, Counter


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def get_module(meta: dict) -> str:
    """
    Return the module / package / crate identifier for a function.
    Falls back to 'pkg' for backward compatibility.
    """
    return meta.get("module") or meta.get("pkg") or "(unknown)"


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #

def main(inp: Path, out_sub: Path, out_deps: Path) -> None:
    graph = json.loads(inp.read_text())

    module_funcs  = defaultdict(set)    # module → {func ids}
    module_edges  = defaultdict(list)   # module → [(caller, callee)]
    dep_counts    = Counter()           # (from_mod, to_mod) → n

    for caller_id, meta in graph.items():
        caller_mod = get_module(meta)
        module_funcs[caller_mod].add(caller_id)

        for callee_id in meta["callees"]:
            callee_meta = graph.get(callee_id)
            if not callee_meta:             # defensive: callee missing
                continue
            callee_mod = get_module(callee_meta)

            if caller_mod == callee_mod:
                module_edges[caller_mod].append((caller_id, callee_id))
            else:
                dep_counts[(caller_mod, callee_mod)] += 1

    # ------------------------- serialise per-module sub-graphs
    subgraphs = {
        mod: {
            "functions":      sorted(funcs),
            "internal_edges": sorted(edges)
        }
        for mod, funcs in module_funcs.items()
        for edges in [module_edges[mod]]        # small trick to re-use edges
    }
    out_sub.write_text(json.dumps(subgraphs, indent=2))

    # ------------------------- serialise boundary calls
    deps_serialised = [
        {"from_module": a, "to_module": b, "count": n}
        for (a, b), n in dep_counts.most_common()
    ]
    out_deps.write_text(json.dumps(deps_serialised, indent=2))

    # ------------------------- summary
    print(
        f"✓ wrote {len(subgraphs):,} module sub-graphs → {out_sub}\n"
        f"✓ wrote {len(deps_serialised):,} cross-module edges → {out_deps}"
    )


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Phase-2: split graph by module")
    parser.add_argument(
        "--input", "-i",
        default="classified_callgraph.json",
        type=Path,
        help="Classified bidirectional call-graph (Phase-1 output)"
    )
    parser.add_argument(
        "--out-subgraphs", "-s",
        default="module_subgraphs.json",
        type=Path,
        help="Destination JSON containing per-module sub-graphs"
    )
    parser.add_argument(
        "--out-deps", "-d",
        default="module_dependencies.json",
        type=Path,
        help="Destination JSON listing cross-module call counts"
    )
    args = parser.parse_args()

    main(args.input, args.out_subgraphs, args.out_deps)
