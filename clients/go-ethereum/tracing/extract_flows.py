#!/usr/bin/env python3
"""
extract_flows.py  – Phase-3: per-module root→leaf flows
"""

import json
import argparse
from pathlib import Path
from collections import defaultdict, deque

# ---------- Tarjan SCC ----------------------------------------------------- #
def tarjan_scc(nodes, adj):
    index = 0
    idx, low = {}, {}
    stack, onstk = [], set()
    sccs = []

    def strongconnect(v):
        nonlocal index
        idx[v] = low[v] = index; index += 1
        stack.append(v); onstk.add(v)
        for w in adj.get(v, ()):
            if w not in idx:
                strongconnect(w)
                low[v] = min(low[v], low[w])
            elif w in onstk:
                low[v] = min(low[v], idx[w])
        if low[v] == idx[v]:
            comp = set()
            while True:
                w = stack.pop(); onstk.remove(w); comp.add(w)
                if w == v: break
            sccs.append(comp)

    for v in nodes:
        if v not in idx:
            strongconnect(v)
    return sccs


def condense_scc(nodes, adj):
    sccs = tarjan_scc(nodes, adj)
    idmap, dag_members = {}, {}
    for i, comp in enumerate(sccs):
        lbl = f"SCC::{i}" if len(comp) > 1 else next(iter(comp))
        dag_members[lbl] = comp
        for v in comp: idmap[v] = lbl

    dag_adj = defaultdict(set)
    for u in nodes:
        for v in adj.get(u, ()):
            a, b = idmap[u], idmap[v]
            if a != b: dag_adj[a].add(b)
    return dag_adj, dag_members


# ---------- DAG utilities -------------------------------------------------- #
def enumerate_paths(roots, leaves, dag_adj):
    paths = []
    def dfs(cur, path):
        if cur in leaves:
            paths.append(path)
            return
        for nxt in dag_adj.get(cur, ()):
            dfs(nxt, path + [nxt])
    for r in roots:
        dfs(r, [r])
    return paths


def compute_trunk_scores(dag_adj, roots, leaves):
    cache = {}
    def leaves_count(u):
        if u in cache: return cache[u]
        if u in leaves: cache[u] = 1
        else:
            cache[u] = sum(leaves_count(v) for v in dag_adj.get(u, ()))
        return cache[u]

    depth = {}
    q = deque((r, 0) for r in roots)
    while q:
        u, d = q.popleft()
        if u in depth: continue
        depth[u] = d
        for v in dag_adj.get(u, ()): q.append((v, d + 1))

    return {n: leaves_count(n) / (depth.get(n, 0) + 1) for n in dag_adj}


# ---------- per-module processing ----------------------------------------- #
def process_module(mod, mod_data):
    funcs = mod_data["functions"]
    edges = {tuple(t) for t in mod_data["internal_edges"]}
    adj   = defaultdict(set)
    for u, v in edges: adj[u].add(v)

    # 1) collapse cycles
    dag_adj, dag_members = condense_scc(funcs, adj)
    dag_nodes = list(dag_members.keys())               # <-- fixed line

    # 2) roots & leaves
    indeg = {n: 0 for n in dag_nodes}
    for u, outs in dag_adj.items():
        for v in outs: indeg[v] += 1
    roots  = {n for n in dag_nodes if indeg[n] == 0}
    leaves = {n for n in dag_nodes if not dag_adj.get(n)}

    # 3) paths and scores
    paths  = enumerate_paths(roots, leaves, dag_adj)
    scores = compute_trunk_scores(dag_adj, roots, leaves)

    return {
        "roots":        sorted(roots),
        "leaves":       sorted(leaves),
        "paths":        paths,
        "trunk_scores": scores,
        "scc_members":  {k: sorted(v) for k, v in dag_members.items()
                         if k.startswith("SCC::")}
    }


# ---------- main ----------------------------------------------------------- #
def main(inp: Path, outp: Path):
    modules = json.loads(inp.read_text())
    flows = {m: process_module(m, d) for m, d in modules.items()}
    outp.write_text(json.dumps(flows, indent=2))
    print(f"✓ wrote flows for {len(flows):,} modules → {outp}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Phase-3: extract module flows")
    ap.add_argument("--input", "-i", default="module_subgraphs.json",
                    type=Path, help="Phase-2 output")
    ap.add_argument("--output", "-o", default="module_flows.json",
                    type=Path, help="Destination file")
    args = ap.parse_args()
    main(args.input, args.output)
