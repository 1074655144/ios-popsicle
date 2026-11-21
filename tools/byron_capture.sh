#!/bin/bash
# One-shot read-only capture after a byron iOS boot, once the phone is back in Android.
#
#   tools/byron_capture.sh NAME [MINUTES]
#
# NAME names the run. MINUTES (default 20) limits the unified-log trace files
# copied by ioslog_fetch.py. Everything is written outside the repo, under
# $WSL_ROOT$WSL_WORK/captures/NAME by default.
#
# It fetches:
#   - the pinned PANDORLG kernel ring, decoded with tools/pandora_log.py
#   - the iOS unified log archive, parsed with unifiedlog_iterator
#   - in-kernel screenshots from /private/var/tmp, converted to PNG
#   - a summary.txt of the markers that matter for the current white-Apple-Logo work
#
# No writes to the phone, no rawwrite, no partition/AVB changes.
set -euo pipefail
export MSYS_NO_PATHCONV=1

NAME=${1:?usage: tools/byron_capture.sh NAME [MINUTES]}
MINUTES=${2:-20}
ROOT=$(cd "$(dirname "$0")/.." && pwd)
# python3 is a Windows build here; give it native paths, not Git Bash /c/... paths.
winp() { cygpath -w "$1" 2>/dev/null || echo "$1"; }
PANDORA_LOG=$(winp "$ROOT/tools/pandora_log.py")
IOSLOG_FETCH=$(winp "$ROOT/tools/ioslog_fetch.py")
SHOT_FETCH=$(winp "$ROOT/tools/shot_fetch.py")
ADB=${ADB:-/d/Android/platform-tools/adb.exe}
WSL_ROOT=${WSL_ROOT:-'//wsl$/Ubuntu-24.04'}
WSL_DISTRO=${WSL_DISTRO:-Ubuntu-24.04}
WSL_WORK=${WSL_WORK:-/opt/work}
OUT=${OUT:-$WSL_ROOT$WSL_WORK/captures/$NAME}
PHONE_PINFILE=${PINFILE:-/data/local/tmp/pinfile}
PHONE_LOG=${IOSLOG:-/data/local/tmp/ioslog.img}
PHONE_IMG=${IOS_IMG:-/data/local/tmp/iosroot.img}

mkdir -p "$OUT/shots"

state=$("$ADB" shell getprop sys.boot_completed 2>/dev/null | tr -d '\r' || true)
if [[ $state != 1 ]]; then
  echo "phone is not back in Android (sys.boot_completed=$state); do not run capture yet" >&2
  exit 3
fi

missing=$("$ADB" shell "su -c 'for f in $PHONE_PINFILE $PHONE_LOG $PHONE_IMG; do [ -e \"\$f\" ] || echo \$f; done'" 2>/dev/null | tr -d '\r' || true)
if [[ -n $missing ]]; then
  echo "missing phone-side files: $missing" >&2
  exit 4
fi

DEV=$("$ADB" shell "su -c 'readlink -f /dev/block/by-name/userdata'" 2>/dev/null | tr -d '\r')
[[ $DEV == /dev/* ]] || { echo "bad userdata device: $DEV" >&2; exit 5; }
echo "[1/4] kernel ring -> $OUT/kernel_ring.raw"
# pinfile exposes rawreadat PATH DEV OFF LEN (no whole-file rawread). The log is
# an 8 MiB pinned file; read it from offset 0. Override IOSLOG_LEN if resized.
IOSLOG_LEN=${IOSLOG_LEN:-8388608}
"$ADB" exec-out su -c "$PHONE_PINFILE rawreadat $PHONE_LOG $DEV 0 $IOSLOG_LEN 2>/dev/null" > "$OUT/kernel_ring.raw"
python3 "$PANDORA_LOG" "$OUT/kernel_ring.raw" "$OUT/kernel_ring.txt"

echo "[2/4] unified log archive -> $WSL_WORK/la_$NAME and ul_$NAME.jsonl"
ADB=$ADB WSL_ROOT=$WSL_ROOT WSL_DISTRO=$WSL_DISTRO WSL_WORK=$WSL_WORK \
  python3 "$IOSLOG_FETCH" "$NAME" --minutes "$MINUTES" --parse

echo "[3/4] screenshots -> $OUT/shots"
ADB=$ADB WSL_ROOT=$WSL_ROOT WSL_DISTRO=$WSL_DISTRO WSL_WORK=$WSL_WORK \
  python3 "$SHOT_FETCH" "$OUT/shots"

echo "[4/4] summary -> $OUT/summary.txt"
LOG=$OUT/kernel_ring.txt
UL=$WSL_ROOT$WSL_WORK/ul_${NAME}.jsonl
{
  echo "# byron capture $NAME ($(date -u +%Y-%m-%dT%H:%M:%SZ))"
  echo
  echo "## key events"
  grep -nE 'Cache sent to launchd successfully|UMD_INIT: failed to read nextsession dict|UMD_INIT: FAILED to Set Foreground ID|exec SpringBoard|exec backboardd|exec loginwindow|exec DumpPanic|CRASH driverkitd|exec vktest|exec mtltest|PANDORA GPU|PANDORA FILES|PANDORA SHOT|MTLTEST:|VKTEST:|AGXAccelerator|IOAcceleratorES|NativeAdrenoMetal|panic\(|FATAL KEYBAG ERROR|SWEET AMFI.*(launchd_cache_loader|NativeAdrenoMetal)' "$LOG" | head -250 || true
  echo
  echo "## counts"
  for pat in \
    'AGXAccelerator.*found' \
    'AGXAccelerator.*none' \
    'IOAcceleratorES.*found' \
    'IOAcceleratorES.*none' \
    'PANDORA GPU UC: (AGX|client|open)' \
    'NativeAdrenoMetal' \
    'exec loginwindow' \
    'exec DumpPanic' \
    'panic\(' \
    'CRASH driverkitd' \
    'PANDORA SHOT'
  do
    n=$(grep -cE "$pat" "$LOG" || true)
    printf '%-45s %s\n' "$pat" "${n:-0}"
  done
  echo
  echo "## unified log markers"
  if [[ -f $UL ]]; then
    grep -aE 'NativeAdrenoMetal|AGXAccelerator|IOAcceleratorES|loginwindow|SpringBoard|backboardd' "$UL" | head -120 || true
  else
    echo "missing: $UL"
  fi
  echo
  echo "## files"
  ls -la "$OUT" "$OUT/shots" | head -80 || true
} > "$OUT/summary.txt"

echo "done: $OUT/summary.txt"
