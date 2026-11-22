#!/usr/bin/env python3
"""Verify a unified diff applies cleanly, without the files it was made for.

The hunks of a diff carry the context lines of the file they were taken from.
This rebuilds an approximation of each original file from those context lines
and runs `patch --dry-run` on it, so a hand-edited hunk is caught before it
reaches a build.

    python3 tools/verify_patch.py FILE.patch

Exit code 0 when every hunk applies, 1 otherwise.
"""
import os
import shutil
import subprocess
import sys
import tempfile


def main() -> int:
    path = sys.argv[1]
    text = open(path, encoding="utf8", newline="").read()
    if text.endswith("\n"):
        text = text[:-1]
    lines = text.replace("\r\n", "\n").split("\n")
    root = tempfile.mkdtemp(prefix="patchcheck.")
    try:
        # Rebuild each target file from the context and deleted lines.
        current = None
        originals = {}
        i = 0
        while i < len(lines):
            line = lines[i]
            if line.startswith("--- "):
                name = line[4:].split("\t")[0].strip()
                if name.startswith(("a/", "b/")):
                    name = name[2:]
                current = name
                originals.setdefault(current, [])
                i += 1
                continue
            if line.startswith("+++ "):
                i += 1
                continue
            if line.startswith((" ", "-")) and current is not None:
                originals[current].append(line[1:])
            elif line.startswith("+") or line.startswith("\\"):
                pass
            i += 1
        for name, body in originals.items():
            path_on_disk = os.path.join(root, name)
            os.makedirs(os.path.dirname(path_on_disk), exist_ok=True)
            with open(path_on_disk, "w", encoding="utf8", newline="") as f:
                f.write("\n".join(body) + "\n")
        # Every file the diff names must exist for the dry run to work.
        r = subprocess.run(
            ["patch", "--dry-run", "--fuzz=0", "-p1", "-d", root, "-i", os.path.abspath(path)],
            capture_output=True, text=True,
        )
        sys.stdout.write(r.stdout)
        sys.stderr.write(r.stderr)
        bad = [l for l in r.stdout.split("\n") if "malformed" in l or "FAILED" in l]
        if r.returncode != 0 or bad:
            print("VERIFY: FAILED")
            return 1
        print("VERIFY: all hunks apply")
        return 0
    finally:
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
