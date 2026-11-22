#!/usr/bin/env python3
"""Check and repair the hunk line counts of a unified diff (patch -p1 files).

`patch` rejects a file whose @@ headers disagree with the body, which happens
when a hunk is edited by hand. This recomputes every header from the body and
rewrites the file when they differ.

    python3 tools/fix_patch_hunks.py FILE [--write]

Without --write it only reports the differences.

The body of a hunk ends at the next file header: a "--- " line directly
followed by a "+++ " line (or the other way round). A line inside a hunk may
well read "+++ text" -- that is an added line whose content starts with "++ " --
and it is not a header, because no partner line follows it.
"""
import re
import sys

HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(.*)$")


def is_file_header(lines, i):
    """True when lines[i] and lines[i+1] are the '--- '/'+++ ' pair of a file header."""
    if i + 1 >= len(lines):
        return False
    a, b = lines[i], lines[i + 1]
    return (a.startswith("--- ") and b.startswith("+++ ")) or (a.startswith("+++ ") and b.startswith("--- "))


def main() -> int:
    path = sys.argv[1]
    write = "--write" in sys.argv[2:]
    text = open(path, encoding="utf8", newline="").read()
    if text.endswith("\n"):
        text = text[:-1]
    lines = text.replace("\r\n", "\n").split("\n")
    out = []
    i = 0
    fixed = 0
    while i < len(lines):
        line = lines[i]
        m = HUNK.match(line)
        if not m:
            out.append(line)
            i += 1
            continue
        old_start = int(m.group(1))
        old_len = int(m.group(2)) if m.group(2) is not None else 1
        new_start = int(m.group(3))
        new_len = int(m.group(4)) if m.group(4) is not None else 1
        tail = m.group(5)
        body = []
        ctx = add = dele = 0
        i += 1
        while i < len(lines):
            b = lines[i]
            if is_file_header(lines, i):
                break
            if b.startswith("\\"):
                body.append(b)              # "\ No newline at end of file": no line of the file
                i += 1
                continue
            if b.startswith("-"):
                dele += 1
            elif b.startswith("+"):
                add += 1
            elif b.startswith(" ") or b == "":
                ctx += 1
            else:
                break
            body.append(b)
            i += 1
        body_old, body_new = ctx + dele, ctx + add
        old_part = f"-{old_start}" + (f",{old_len}" if old_len != 1 else "")
        new_part = f"+{new_start}" + (f",{body_new}" if body_new != 1 else "")
        if body_old != old_len or body_new != new_len:
            fixed += 1
            print(f"hunk {old_part}: header -{old_len}/+{new_len}, body -{body_old}/+{body_new}")
        out.append(f"@@ {old_part} {new_part} @@{tail}")
        out.extend(body)
    if fixed and write:
        open(path, "w", encoding="utf8", newline="\n").write("\n".join(out) + "\n")
        print(f"rewrote {fixed} hunk header(s) in {path}")
    elif fixed:
        print(f"{fixed} hunk header(s) need fixing (use --write)")
    else:
        print("all hunk headers match")
    return 0


if __name__ == "__main__":
    sys.exit(main())
