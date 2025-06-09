#!/usr/bin/env bash
set -euo pipefail

mkdir -p /output

python3 /extract_functions_lsp.py          --out /output/functions.json
python3 /extract_callgraph_lsp.py          --out /output/callgraph.json
python3 /make_callgraph_bidirectional.py   --functions /output/functions.json \
                                           --callgraph /output/callgraph.json \
                                           --out /output/bidirectional_callgraph.json
python3 /classify_nodes.py                 --input  /output/bidirectional_callgraph.json \
                                           --output /output/classified_callgraph.json
python3 /split_by_module.py                --input  /output/classified_callgraph.json \
                                           --out-subgraphs /output/module_subgraphs.json \
                                           --out-deps      /output/module_dependencies.json
python3 /extract_flows.py                  --input  /output/module_subgraphs.json \
                                           --output /output/module_flows.json
python3 /rank_trunks.py                    --input  /output/module_flows.json \
                                           --output /output/module_flows_ranked.json \
                                           --top 15 

echo "Pipeline finished. Outputs are in /output"
