#!/usr/bin/env python3
import argparse
import os
import re
import toml
from pathlib import Path

ROOT = Path(__file__).parent
CRATES_ROOT = ROOT / "crates"

def discover_crates():
    """Scan all subfolders under ./crates for Cargo.toml and return {pkg_name: dir_path}."""
    mapping = {}
    for cargo_toml in CRATES_ROOT.rglob("Cargo.toml"):
        try:
            data = toml.load(cargo_toml)
            pkg = data.get("package", {}).get("name")
            if pkg:
                mapping[pkg] = cargo_toml.parent
        except Exception:
            continue
    return mapping

def find_functions(rs_path):
    """Return list of (line_no, signature) for each fn in this .rs file."""
    fns = []
    pattern = re.compile(r'^\s*(?:pub\s+)?fn\s+([a-zA-Z0-9_]+)')
    with open(rs_path, encoding="utf-8") as f:
        for i, line in enumerate(f, start=1):
            m = pattern.match(line)
            if m:
                fns.append((i, m.group(1)))
    return fns

def gen_breakpoints(crate_dirs, out_path):
    """Write all break/commands blocks to out_path for each crate_dir in crate_dirs."""
    with open(out_path, "w") as out:
        for crate_name, crate_dir in crate_dirs.items():
            src_root = crate_dir / "src"
            if not src_root.exists(): 
                continue
            out.write(f"\n# ---- breakpoints for crate: {crate_name} ----\n")
            for rs in sorted(src_root.rglob("*.rs")):
                rel = rs.relative_to(ROOT)
                for line_no, fn in find_functions(rs):
                    out.write(f"break {rel}:{line_no}   # fn {fn}\n")
                    out.write("commands\n")
                    out.write("  silent\n")
                    out.write("  info line *$pc\n")
                    out.write("  continue\n")
                    out.write("end\n\n")
    print(f"Generated {out_path}")

def main():
    p = argparse.ArgumentParser(
        description="Generate breakpoints.gdb for specified Rust crates")
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "-f", "--file", help="file with one crate name per line")
    group.add_argument(
        "crates", nargs="*", help="crate names to include")
    p.add_argument(
        "-o", "--out", default="breakpoints.gdb",
        help="path to write the GDB script (default: breakpoints.gdb)")
    args = p.parse_args()

    all_crates = discover_crates()
    if args.file:
        names = [l.strip() for l in open(args.file) if l.strip()]
    else:
        names = args.crates

    # build a dict of requested crates -> their paths
    selected = {}
    for name in names:
        if name not in all_crates:
            print(f"Warning: crate {name!r} not found under {CRATES_ROOT}")
        else:
            selected[name] = all_crates[name]

    if not selected:
        print("No valid crates found; exiting.")
        return

    gen_breakpoints(selected, args.out)

if __name__ == "__main__":
    main()
