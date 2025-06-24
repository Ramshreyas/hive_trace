#!/usr/bin/env python3
"""
classify_nodes.py  – Phase-1 of the pipeline
"""

import json
import argparse
from pathlib import Path


def classify(meta):
    indeg  = len(meta["callers"])
    outdeg = len(meta["callees"])
    if   indeg == 0 and outdeg == 0: return "orphan"
    elif indeg == 0:                 return "root"
    elif outdeg == 0:                return "leaf"
    else:                            return "trunk"


def main(inp: Path, out: Path):
    graph = json.loads(inp.read_text())

    for meta in graph.values():
        meta["node_type"] = classify(meta)

    out.write_text(json.dumps(graph, indent=2))

    counts = {}
    for m in graph.values():
        counts[m["node_type"]] = counts.get(m["node_type"], 0) + 1
    print(f"✓ wrote {out}.  Counts: {counts}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Classify call-graph nodes.")
    parser.add_argument("--input", "-i",
                        default="bidirectional_callgraph.json", type=Path,
                        help="Bidirectional call-graph from Phase-0")
    parser.add_argument("--output", "-o",
                        default="classified_callgraph.json",   type=Path,
                        help="Destination JSON")
    args = parser.parse_args()

    main(args.input, args.output)
