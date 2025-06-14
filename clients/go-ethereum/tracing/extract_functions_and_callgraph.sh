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

echo "▶ Phase 2 – Split by module"
python3 /split_by_module.py \
        --input         /output/classified_callgraph.json \
        --out-subgraphs /output/module_subgraphs.json \
        --out-deps      /output/module_dependencies.json

echo "▶ Phase 3 – Extract flows + rank trunks"
python3 /extract_flows.py \
        --input  /output/module_subgraphs.json \
        --output /output/module_flows.json

python3 /rank_trunks.py \
        --input  /output/module_flows.json \
        --output /output/module_flows_ranked.json \
        --top    "${TOP_TRUNKS}"

echo "▶ Phase 4-M0 – Repo summary (Gemini)"
python3 /annotate_repo.py

echo "▶ Phase 4-M1 – Module summaries (Gemini)"
python3 /annotate_modules.py

echo "▶ Phase 4-M2 – Trunk summaries within modules (Gemini)"
python3 /annotate_trunks.py

echo "▶ Phase 4-M3 – Leaf summaries within modules (Gemini)"
python3 /annotate_leaves.py

echo "✅ Pipeline finished. All artefacts are under /output"
printf "   USE_LLM=%s  |  GEMINI_API_KEY=%s\n" "$USE_LLM" "${GEMINI_API_KEY:+***}"
