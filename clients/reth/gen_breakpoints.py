#!/usr/bin/env python3
import argparse
import os
import re
import sys
import toml
from pathlib import Path


def discover_crates(crates_root: Path):
    """Scan all subfolders under crates_root for Cargo.toml and return {pkg_name: dir_path}."""
    mapping = {}
    for cargo_toml in crates_root.rglob("Cargo.toml"):
        try:
            data = toml.load(cargo_toml)
            pkg = data.get("package", {}).get("name")
            if pkg:
                mapping[pkg] = cargo_toml.parent
        except Exception:
            continue
    return mapping


def find_functions(rs_path: Path):
    """Return list of (line_no, fn_name) for each fn in this .rs file."""
    fns = []
    pattern = re.compile(r'^\s*(?:pub\s+)?fn\s+([A-Za-z0-9_]+)')
    with rs_path.open(encoding="utf-8") as f:
        for i, line in enumerate(f, start=1):
            m = pattern.match(line)
            if m:
                fns.append((i, m.group(1)))
    return fns


def gen_breakpoints(crate_dirs: dict, out_path: Path, root: Path):
    """Write breakpoints + commands blocks to out_path for each crate in crate_dirs."""
    with out_path.open("w", encoding="utf-8") as out:
        for crate_name, crate_dir in crate_dirs.items():
            src_root = crate_dir / "src"
            if not src_root.exists():
                continue

            out.write(f"\n# ---- breakpoints for crate: {crate_name} ----\n")
            for rs in sorted(src_root.rglob("*.rs")):
                rel = rs.relative_to(root)
                for line_no, fn in find_functions(rs):
                    # 1) set a line-based breakpoint
                    out.write(f"break {rel}:{line_no}\n")
                    # 2) attach commands
                    out.write("commands\n")
                    out.write("  silent\n")
                    out.write("  python\n")
                    out.write("import gdb\n")
                    out.write("# remember the frame we hit\n")
                    out.write("start_frame = gdb.selected_frame().name()\n")
                    out.write("# keep stepping until we leave that frame\n")
                    out.write("while gdb.selected_frame().name() == start_frame:\n")
                    out.write("    gdb.execute('next')\n")
                    out.write("    gdb.execute('info line *$pc')\n")
                    out.write("# once we’ve left, resume normally\n")
                    out.write("gdb.execute('continue')\n")
                    out.write("  end\n")   # end of python block
                    out.write("end\n\n")    # end of commands
    print(f"Generated {out_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Generate a GDB breakpoints.gdb for specified Rust crates"
    )
    parser.add_argument(
        '--crates-root', '-r',
        type=Path,
        default=Path("./crates"),
        help="root folder under which to discover crates (default: ./crates)"
    )
    parser.add_argument(
        '-f', '--file',
        type=Path,
        help="file with one crate name per line"
    )
    parser.add_argument(
        'crates',
        nargs='*',
        help="crate names to include (if -f/--file not used)"
    )
    parser.add_argument(
        '-o', '--out',
        type=Path,
        default=Path("breakpoints.gdb"),
        help="output GDB script path"
    )
    args = parser.parse_args()

    # enforce mutual exclusion manually
    if args.file and args.crates:
        parser.error("cannot specify both --file and crate names")
    if not args.file and not args.crates:
        parser.error("must specify either --file or at least one crate name")

    # build list of names
    if args.file:
        names = [l.strip() for l in args.file.read_text().splitlines() if l.strip()]
    else:
        names = args.crates

    all_crates = discover_crates(args.crates_root)
    selected = {}
    for name in names:
        if name not in all_crates:
            print(f"Warning: crate '{name}' not found under {args.crates_root}")
        else:
            selected[name] = all_crates[name]

    if not selected:
        print("No valid crates found; exiting.")
        sys.exit(1)

    # root is parent of crates root
    project_root = args.crates_root.parent
    gen_breakpoints(selected, args.out, project_root)

if __name__ == '__main__':
    main()
