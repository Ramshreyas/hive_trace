#!/usr/bin/env bash
set -euo pipefail

# ---------------------------------------------------------------------------
# Environment: you can flip these before running the script
# ---------------------------------------------------------------------------
: "${USE_LLM:=0}"                     # 0 = prompts only, 1 = call Gemini
: "${GEMINI_API_KEY:=}"               # export this before running if USE_LLM=1
TOP_TRUNKS=15                         # trunks per module for ranking
# ---------------------------------------------------------------------------

mkdir -p /output

echo "▶ Phase 0 – Functions + caller-only call-graph (LSP)"
python3 /extract_functions_lsp.py  --out /output/functions.json
python3 /extract_callgraph_lsp.py  --out /output/callgraph.json

echo "▶ Phase 0b – Make call-graph bidirectional"
python3 /make_callgraph_bidirectional.py \
        --functions /output/functions.json \
        --callgraph /output/callgraph.json \
        --out       /output/bidirectional_callgraph.json

echo "▶ Phase 1 – Node classification"
python3 /classify_nodes.py \
        --input  /output/bidirectional_callgraph.json \
        --output /output/classified_callgraph.json

echo "▶ Phase 4-M0 – Repo summary (Gemini)"
python3 /annotate_repo.py

echo "▶ Phase 4-M2 – Generate Breakpoints (Gemini)"
python3 /gen_breakpoints.py \
        --callgraph /output/classified_callgraph.json \
        --objective-file /objective.txt \
        --context-file /context.txt \
        --n 10 --depth 100 --max-lines 40 \
        --out-gdb /output/eip_breakpoints.gdb

echo "✅ Pipeline finished. All artefacts are under /output"
printf "   USE_LLM=%s  |  GEMINI_API_KEY=%s\n" "$USE_LLM" "${GEMINI_API_KEY:+***}"
