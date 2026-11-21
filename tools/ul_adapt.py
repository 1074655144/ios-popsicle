#!/usr/bin/env python3
"""Adapt an iOS 16+ "migrated" unified-log archive to the classic layout the
mandiant/macos-UnifiedLogs parser expects.

  ul_adapt.py SRC_DIR DST_DIR

iOS 15+ moved diagnostics trace files into two-hex-digit buckets with bare UUID
names (and dropped the .tracev3 suffix).  LogarchiveProvider.collect_tracev3_paths
only looks in Persist/ Special/ Signpost/ HighVolume/ for files ending in
".tracev3", so parsing such an archive fails with "no tracev3 files found".

This script hardlinks (falls back to copy) every tracev3-classified file into
DST_DIR/Persist/<name>.tracev3 and hardlinks the support files that already
match the classic layout (timesync/, dsc/, version.plist, ...) unchanged.  No
phone data is copied into the repo; everything stays under the WSL work dir.

Classification is by file magic, not by name:
  tag 0x1000 (le 00 10 00 00) -> tracev3 -> Persist/<name>.tracev3
  tag 0x600b / 0x600d         -> tracev3 -> Persist/<name>.tracev3
  0x66778899 (le 99 88 77 66) -> uuidtext -> <hex-bucket>/<name> (kept as-is)
  0x64736368 (le 68 63 73 64) -> dsc      -> dsc/<name>
  0x0000bbb0                  -> timesync -> timesync/<name>

IMPORTANT: in the byron captures (fix13/14/15) the diagnostics archive contains
ONLY uuidtext + dsc + timesync -- there are NO tracev3 log files.  The
ioslog_fetch.py --minutes filter drops them (they carry HFS mtimes outside the
window), so unified-log parsing yields zero entries no matter how the layout is
adapted.  That is a fetch-side limitation, documented in LIVE_BRINGUP_STATUS.md.
"""
import argparse
import os
import shutil
import struct
import sys

# tracev3 top-level chunk tags (first 4 bytes, little-endian u32)
TRACE_TAGS = {0x1000, 0x600B, 0x600D}
UUIDTEXT_MAGIC = 0x66778899
DSC_MAGIC_LE = 0x64736368


def link_or_copy(src, dst):
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    if os.path.exists(dst) and os.path.getsize(dst) == os.path.getsize(src):
        return
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)


def classify(path):
    with open(path, "rb") as f:
        head = f.read(8)
    if len(head) < 4:
        return "other"
    tag = struct.unpack_from("<I", head, 0)[0]
    if tag in TRACE_TAGS:
        return "tracev3"
    if tag == DSC_MAGIC_LE:
        return "dsc"
    if tag == UUIDTEXT_MAGIC:
        return "uuidtext"
    return "other"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("dst")
    a = ap.parse_args()
    src, dst = os.path.abspath(a.src), os.path.abspath(a.dst)
    if not os.path.isdir(src):
        raise SystemExit(f"no such archive dir: {src}")
    os.makedirs(dst, exist_ok=True)

    ntrace = ndsc = nother = 0
    for root, dirs, files in os.walk(src):
        rel = os.path.relpath(root, src)
        for fn in files:
            sp = os.path.join(root, fn)
            kind = classify(sp)
            if kind == "tracev3":
                # Only the top-level trace files in hex buckets; skip any that
                # are already in a classic Persist/ dir from a prior adapt.
                name = fn if fn.endswith(".tracev3") else fn + ".tracev3"
                link_or_copy(sp, os.path.join(dst, "Persist", name))
                ntrace += 1
            elif kind == "dsc":
                link_or_copy(sp, os.path.join(dst, "dsc", fn))
                ndsc += 1
            else:
                # timesync/, uuidtext hex buckets, version.plist, logd.* etc.
                if rel == ".":
                    # top-level support files that belong at archive root
                    if fn in ("version.plist", "logd.0.log") or fn.endswith(".statistics.0.txt") or fn.endswith(".statistics.0.jsonl") or fn.endswith(".migrated"):
                        link_or_copy(sp, os.path.join(dst, fn))
                elif rel.startswith("timesync") or rel.startswith("dsc"):
                    link_or_copy(sp, os.path.join(dst, rel, fn))
                else:
                    # uuidtext buckets (hex dir / 30-hex-char name)
                    link_or_copy(sp, os.path.join(dst, rel, fn))
                nother += 1

    print(f"adapted {src} -> {dst}: {ntrace} tracev3, {ndsc} dsc, {nother} other")


if __name__ == "__main__":
    main()
