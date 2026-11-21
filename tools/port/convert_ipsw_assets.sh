#!/bin/bash
# Convert the extracted raw IPSW assets into the two artifacts build_boot.sh consumes:
#   $OUT/d22ap.adt              (from Firmware/all_flash/DeviceTree.d22ap.im4p)
#   $OUT/kernelcache.thin.macho (from kernelcache.release.iphone10b, IM4P+bvx2)
#
# Both im4p payloads are Apple's bvx2 (LZMA2 variant); the stock Python lzma module
# cannot decode them, so this needs the `ipsw` CLI (blacktop/ipsw). It accepts either
# a Linux `ipsw` on PATH or a Windows ipsw.exe invoked from WSL via IPSW_BIN.
#
# Usage (from WSL):
#   IPSW_DIR=/opt/work/ipsw OUT=/opt/work/ipsw/ext \
#     IPSW_BIN=/mnt/c/.../ipsw.exe bash tools/port/convert_ipsw_assets.sh
set -euo pipefail

IPSW_DIR=${IPSW_DIR:-/opt/work/ipsw}
OUT=${OUT:-$IPSW_DIR/ext}
# Prefer explicit IPSW_BIN, else `ipsw` on PATH.
if [ -n "${IPSW_BIN:-}" ]; then
	IPSW="$IPSW_BIN"
elif command -v ipsw >/dev/null 2>&1; then
	IPSW=$(command -v ipsw)
else
	echo "ERROR: ipsw CLI not found. Set IPSW_BIN=... or install blacktop/ipsw." >&2
	exit 1
fi

mkdir -p "$OUT"
echo "== ipsw: $($IPSW version 2>&1 | head -1)"
echo "== source: $IPSW_DIR"

# A Windows ipsw.exe called from WSL cannot parse POSIX paths (/opt/... becomes \opt\...).
# Convert every path we hand to it via wslpath -w when IPSW_BIN is a Windows exe.
to_ipsw_path() {
	case "$IPSW" in
		*.exe) wslpath -w "$1" ;;
		*)     printf '%s' "$1" ;;
	esac
}

# --- 1. DeviceTree.d22ap.im4p -> d22ap.adt ---
DT="$IPSW_DIR/Firmware/all_flash/DeviceTree.d22ap.im4p"
if [ ! -f "$DT" ]; then echo "ERROR: missing $DT" >&2; exit 1; fi
echo "== extracting DeviceTree -> d22ap.adt"
"$IPSW" img4 im4p extract "$(to_ipsw_path "$DT")" --output "$(to_ipsw_path "$OUT/d22ap.adt")"

# --- 2. kernelcache.release.* -> kernelcache.thin.macho ---
# The IM4P payload (bvx2) decompresses to a fat Mach-O containing the arm64e slice.
# `img4 im4p extract` handles this directly and avoids re-reading the 5.8 GB IPSW.
KC=$(ls "$IPSW_DIR"/kernelcache.release.* 2>/dev/null | head -1)
if [ ! -f "$KC" ]; then echo "ERROR: missing kernelcache in $IPSW_DIR" >&2; exit 1; fi
echo "== extracting kernelcache -> kernelcache.thin.macho"
"$IPSW" img4 im4p extract "$(to_ipsw_path "$KC")" --output "$(to_ipsw_path "$OUT/kernelcache.thin.macho")"

echo "== results =="
ls -lh "$OUT"
# Sanity: d22ap.adt is an Apple DeviceTree ('dtre' payload), thin macho starts with MH_MAGIC_64.
python3 - "$OUT" <<'PY'
import sys, os, pathlib
out = pathlib.Path(sys.argv[1])
adt = out/'d22ap.adt'; kc = out/'kernelcache.thin.macho'
defHead = lambda p: open(p,'rb').read(16).hex(' ') if p.exists() else '(missing)'
print('d22ap.adt head :', defHead(adt))
print('thin macho head:', defHead(kc))
# Search for a Mach-O 64 magic anywhere (kernelcache may carry a small header).
ok = False
if kc.exists():
    b = kc.read_bytes()
    for m in (b'\xcf\xfa\xed\xfe', b'\xfe\xed\xfa\xcf'):
        if m in b[:0x1000]:
            print('thin macho: MH_MAGIC_64 @', hex(b.find(m))); ok = True; break
if not ok: print('WARN: no Mach-O magic found in kernelcache.thin.macho')
PY
