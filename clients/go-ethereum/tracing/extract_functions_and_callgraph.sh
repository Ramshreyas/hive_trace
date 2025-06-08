#!/bin/bash
set -e
python3 /extract_functions_lsp.py
python3 /extract_callgraph_lsp.py
