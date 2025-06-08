#!/usr/bin/env python3
"""
rank_trunks.py  – Phase-4A
-------------------------------------------
• Reads  module_flows.json   (Phase-3 output)
• Adds   ranked_trunks       (top-K by score)
• Writes module_flows_ranked.json
"""

import json
import argparse
from pathlib import Path

TOP_K = 10          # change as you like

def main(inp: Path, outp: Path, k: int):
    flows = json.loads(inp.read_text())

    for mod, data in flows.items():
        ranked = sorted(data["trunk_scores"].items(),
                        key=lambda kv: kv[1], reverse=True)[:k]
        data["ranked_trunks"] = ranked      # list[ [trunk_id, score] , … ]

    outp.write_text(json.dumps(flows, indent=2))
    print(f"✓ added ranked_trunks (top {k}) for {len(flows):,} modules → {outp}")

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Phase-4A: rank module trunks")
    ap.add_argument("--input",  "-i", default="module_flows.json", type=Path)
    ap.add_argument("--output", "-o", default="module_flows_ranked.json", type=Path)
    ap.add_argument("--top",    "-k", default=TOP_K, type=int, help="how many trunks per module")
    args = ap.parse_args()
    main(args.input, args.output, args.top)
