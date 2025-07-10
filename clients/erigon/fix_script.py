#!/usr/bin/env python3
"""
Interleave a fixed GDB “commands … end” block after every
`break <file>:<line>` line in an input file.

Usage
-----
python gen_breakpoint_commands.py input.txt output.txt
"""

import argparse
from pathlib import Path
import sys

# --------------------------------------------------------------------------- #
# Constant block to insert after each `break ...` line (including blank lines)
# --------------------------------------------------------------------------- #
TEMPLATE = """commands
  silent
  python
import gdb
# remember the frame we hit
start_frame = gdb.selected_frame().name()
# keep stepping until we leave that frame
while gdb.selected_frame().name() == start_frame:
    gdb.execute('next')
    gdb.execute('info line *$pc')
# once we’ve left, resume normally
gdb.execute('continue')
  end
end

"""

HEADER = "# ---- auto-generated breakpoints ----\n"


def process(src: Path, dst: Path) -> None:
    """Read *src* and write the transformed text to *dst*."""
    with src.open("r", encoding="utf-8") as fin, dst.open(
        "w", encoding="utf-8"
    ) as fout:
        wrote_header = False

        for raw in fin:
            line = raw.rstrip("\n")

            # Copy any original pre-existing comment line exactly once,
            # but upgrade it to the fancy header that the target format uses.
            if not wrote_header and line.lstrip().startswith("#"):
                fout.write(HEADER)
                wrote_header = True
                continue

            # For every breakpoint directive, write it plus the template.
            if line.startswith("break "):
                if not wrote_header:
                    # No header seen yet (file started directly with 'break …')
                    fout.write(HEADER)
                    wrote_header = True

                fout.write(f"{line}\n")
                fout.write(TEMPLATE)
            else:
                # Any other lines are copied verbatim.
                fout.write(f"{line}\n")


def cli(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(
        description="Interleave a GDB command block after every breakpoint line."
    )
    parser.add_argument("input", type=Path, help="Input breakpoint list")
    parser.add_argument("output", type=Path, help="Output file with commands")
    args = parser.parse_args(argv)

    try:
        process(args.input, args.output)
    except Exception as exc:  # noqa: BLE001
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    cli(sys.argv[1:])
