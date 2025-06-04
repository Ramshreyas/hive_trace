#!/usr/bin/env python3
import argparse
import os
import re
import sys
from pathlib import Path

def discover_packages(module_root: Path):
    """
    Scan all subfolders under module_root for .go files and return {pkg_name: [file_paths]}.
    pkg_name is taken from the 'package' declaration in .go files.
    """
    mapping = {}
    for dirpath, dirs, files in os.walk(module_root):
        # Skip vendor and hidden dirs
        parts = Path(dirpath).parts
        if "vendor" in parts or any(p.startswith('.') for p in parts):
            continue
        go_files = [f for f in files if f.endswith(".go") and not f.endswith("_test.go")]
        if not go_files:
            continue
        # Find package name from the first .go file
        pkg_name = None
        for f in go_files:
            with open(os.path.join(dirpath, f), encoding="utf-8") as fh:
                for line in fh:
                    m = re.match(r'^\s*package\s+([A-Za-z0-9_]+)', line)
                    if m:
                        pkg_name = m.group(1)
                        break
            if pkg_name:
                break
        if pkg_name:
            mapping.setdefault(pkg_name, []).extend([Path(dirpath) / f for f in go_files])
    return mapping

def find_functions(go_path: Path):
    """Return list of (line_no, func_name) for each func in this .go file."""
    fns = []
    pattern = re.compile(r'^\s*func\s+(?:\([^)]+\)\s*)?([A-Za-z0-9_]+)')
    with go_path.open(encoding="utf-8") as f:
        for i, line in enumerate(f, start=1):
            m = pattern.match(line)
            if m:
                fns.append((i, m.group(1)))
    return fns

def gen_breakpoints(pkg_files: dict, out_path: Path, root: Path):
    """Write breakpoints + commands blocks to out_path for each package in pkg_files."""
    with out_path.open("w", encoding="utf-8") as out:
        for pkg_name, files in pkg_files.items():
            out.write(f"\n# ---- breakpoints for package: {pkg_name} ----\n")
            for go_file in sorted(files):
                rel = go_file.relative_to(root)
                for line_no, fn in find_functions(go_file):
                    out.write(f"break {rel}:{line_no}\n")
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
                    out.write("  end\n")
                    out.write("end\n\n")
    print(f"Generated {out_path}")

def main():
    parser = argparse.ArgumentParser(
        description="Generate a GDB breakpoints.gdb for specified Go packages"
    )
    parser.add_argument(
        '--module-root', '-r',
        type=Path,
        default=Path("."),
        help="Go module root folder (default: .)"
    )
    parser.add_argument(
        '-f', '--file',
        type=Path,
        required=True,
        help="file with one Go package name per line, or 'all' to include all packages"
    )
    parser.add_argument(
        '-o', '--out',
        type=Path,
        default=Path("breakpoints.gdb"),
        help="output GDB script path"
    )
    args = parser.parse_args()

    all_pkgs = discover_packages(args.module_root)

    # Support 'all' as a special value
    if args.file.name.lower() == "all" or (args.file.is_file() and args.file.read_text().strip().lower() == "all"):
        selected = all_pkgs
    else:
        pkg_names = [l.strip() for l in args.file.read_text().splitlines() if l.strip()]
        selected = {}
        for name in pkg_names:
            if name not in all_pkgs:
                print(f"Warning: package '{name}' not found under {args.module_root}")
            else:
                selected[name] = all_pkgs[name]

    if not selected:
        print("No valid packages found; exiting.")
        sys.exit(1)

    gen_breakpoints(selected, args.out, args.module_root)

if __name__ == '__main__':
    main()