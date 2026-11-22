#!/bin/bash
# One-command RAM boot of the verified "desktop + USB console + hardware scanout" image.
# Derived from the already-booting ampfix1 payload by changing ONLY the boot-args;
# the kernel, ADT and pinned extents are byte-identical to ampfix1.
#
# Verified boot-args:
#   pandora_usb=2 qcom-usb-debug=1   -> CDC ACM console on COMx (VID_1209/PID_316D)
#   pandora_gpu=15 pandora_gpu_metal=1 -> Metal up and DPU hardware scanout
#      (usbdbg1: scanout off, 600 CPU copies = flower screen;
#       gpu15dbg: scanout on, 600 frames scanned out, 0 copied, 0 faults)
#
# Usage: tools/boot_desktop_diag.sh [--dry-run] [--no-reboot]
#   --dry-run  : rebuild payload/loader but do NOT reboot the phone.
#   --no-reboot: also drop pandora_reboot_after so Setup Assistant is not cut off.
# Requires WSL Ubuntu-24.04 (cross toolchain) and adb/fastboot on PATH or via ADB/FB.
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
ADB=${ADB:-adb}
FB=${FB:-fastboot}
DRY=0
NOREBOOT=0
for opt in "$@"; do
    case "$opt" in
        --dry-run) DRY=1 ;;
        --no-reboot) NOREBOOT=1 ;;
        *) echo "unknown option: $opt" >&2; exit 2 ;;
    esac
done

OUT=shim/loader/desktop
PAYLOAD_ARGS=(--level 2 --drop-autoswipe \
    --extra 'pandora_gpu=15 pandora_gpu_metal=1')
[ "$NOREBOOT" = 1 ] && PAYLOAD_ARGS+=(--drop-reboot-after)
# 1. Derive the payload: same kernel/ADT as ampfix1, USB console + GPU scanout args.
python3 "$ROOT/tools/usb_diag_payload.py" \
    "$ROOT/shim/loader/ampfix1/payload.bin" "$ROOT/$OUT" \
    "${PAYLOAD_ARGS[@]}"

# 2. Link the loader in WSL (full rebuild: never use loader_repack.py; _payload_end must match).
WSL_REPO=$(echo "/$ROOT" | sed -E 's#^/([A-Za-z]):/#/mnt/\1/#')
wsl -d Ubuntu-24.04 -u root -- bash -c \
    "cd '$WSL_REPO/shim/loader' && OUT=$(basename "$OUT") bash build_wsl.sh" | tail -3

if [ "$DRY" = 1 ]; then
    echo "dry run: image built, phone untouched"
    exit 0
fi

# 3. RAM boot only: no flash, no unlock, no AVB change.
"$ADB" reboot bootloader
for _ in $(seq 1 30); do sleep 2; "$FB" devices 2>&1 | grep -q fastboot && break; done
prod=$("$FB" getvar product 2>&1 | sed -n 's/^product: //p' | tr -d '\r')
case "$prod" in byron|pandora) ;; *) echo "wrong product: $prod"; exit 1 ;; esac
"$FB" boot "$(cygpath -w "$ROOT/shim/loader/wsl-out/loader-boot.img")"
echo "booted $(sha256sum "$ROOT/shim/loader/wsl-out/loader-boot.img" | cut -c1-16) at $(date +%H:%M:%S)"
echo "console: powershell -File tools/usbserial_capture2.ps1 -Out <capture> -Seconds 420"
