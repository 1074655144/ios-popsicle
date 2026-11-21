#!/bin/bash
# Collect a NEW board's hardware facts, read-only, over adb. For porting ios-popsicle
# to e.g. byron (Xiaomi 17 Max). Everything lands on the HOST in device/<board>/live/.
#
#   bash tools/port/collect_board.sh --device byron [--out DIR] [--adb PATH] [--adb-wrap CMD]
#
# --adb-wrap CMD runs "<CMD> <adb> ..." instead of "<adb> ...". Useful for
# multi-device setups ("--adb '/path/adb -s SERIAL'" needs no wrap; the wrap is
# for interpreters, e.g. "--adb-wrap bash" with a mock script) and for tests.
#
# SAFETY CONTRACT (do not weaken):
#   * every phone-side command is a read: getprop / cat / dd if= / ls / find / dmsetup table
#   * output redirection (>) writes to the HOST, never to the phone
#   * NO fastboot, NO flash, NO setprop, NO rm/mv/mkdir on the phone, NO mount -o rw
#   * it does NOT unlock the bootloader, does NOT create pinned files, does NOT
#     write a single block of any partition
# The GPT header is read with `dd if=` only; userdata stays untouched.
#
# After this, run: python3 tools/port/gen_byron_config.py --live device/byron/live
set -euo pipefail

DEVICE=byron
OUT=""
ADB=${ADB_BIN:-adb}
WRAP=${ADB_WRAP:-}
while [ $# -gt 0 ]; do
	case $1 in
		--device) DEVICE=$2; shift 2 ;;
		--out) OUT=$2; shift 2 ;;
		--adb) ADB=$2; shift 2 ;;
		--adb-wrap) WRAP=$2; shift 2 ;;
		*) echo "unknown option: $1" >&2; exit 2 ;;
	esac
done
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
[ -n "$OUT" ] || OUT="$ROOT/device/$DEVICE/live"
mkdir -p "$OUT"

run_adb() {
	if [ -n "$WRAP" ]; then "$WRAP" "$ADB" "$@"; else "$ADB" "$@"; fi
}
# phone-side read, text output -> host file
grab() { # grab NAME "phone command"
	local name=$1; shift
	{ run_adb shell "su -c '$*'" 2>/dev/null || true; } | tr -d '\r' > "$OUT/$name"
}
# phone-side read, binary output -> host file (adb exec-out, no CRLF translation)
grabbin() { # grabbin NAME "phone command"
	local name=$1; shift
	run_adb exec-out "su -c '$*'" > "$OUT/$name" 2>/dev/null || : > "$OUT/$name"
}

echo "== collect $DEVICE -> $OUT (read-only)"
echo "device=$DEVICE" > "$OUT/meta.txt"
echo "collected_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$OUT/meta.txt"
echo "adb=$ADB" >> "$OUT/meta.txt"
echo "serial=$(run_adb get-serialno 2>/dev/null | tr -d '\r' | head -1)" >> "$OUT/meta.txt"

# --- identity / software -------------------------------------------------
grab props.txt            'getprop'
grab cpuinfo.txt          'cat /proc/cpuinfo'
grab mounts.txt           'cat /proc/mounts'
grab cmdline.txt          'cat /proc/cmdline'
grab kernel_version.txt   'uname -a'

echo "== identity: $(
	grep -E '^\[ro\.product\.device\]|^\[ro\.product\.model\]|^\[ro\.boot\.slot_suffix\]' "$OUT/props.txt" | tr '\n' ' ' || true
)"

# --- live FDT (the single most valuable artifact) ------------------------
grabbin fdt.dtb           'cat /sys/firmware/fdt'
[ -s "$OUT/fdt.dtb" ] || echo "NOTE: /sys/firmware/fdt unavailable; use DTBO from the fastboot ROM instead" >> "$OUT/meta.txt"

# --- input: which touch chip drives the MAIN panel ------------------------
grab input_devices.txt    'cat /proc/bus/input/devices'
grab getevent_p.txt       'getevent -p'
grab interrupts_1.txt     'cat /proc/interrupts'
if [ "${COLLECT_NO_SLEEP:-}" != 1 ]; then
	echo ">> 请在这 2 秒里只触摸主屏（用来判断哪个 IRQ 在涨）" >&2
	sleep 2
fi
grab interrupts_2.txt     'cat /proc/interrupts'
grab spi_devices.txt      'find /sys/bus/spi/devices -maxdepth 2 -type f -name modalias -o -name uevent'
grab gpio_keys.txt        'for f in /sys/firmware/devicetree/base/gpio-keys/*; do echo --- $f; cat $f 2>/dev/null; done'

# --- storage: dm-default-key mapping + GPT -------------------------------
grab dm_table.txt         'dmsetup table'
# Some MIUI builds ship no dmsetup binary; the same mapping is still in sysfs.
grab dm_sysfs.txt         'for d in /sys/block/dm-*; do n=$(cat "$d/dm/name" 2>/dev/null); s=$(cat "$d/size" 2>/dev/null); sl=$(ls "$d/slaves" 2>/dev/null | xargs echo 2>/dev/null); echo "$d name=$n size=$s slaves=$sl"; done'
grab userdata_sector.txt  'u=$(basename $(readlink -f /dev/block/by-name/userdata 2>/dev/null)); echo userdata_dev=$u; echo start=$(cat /sys/class/block/$u/start 2>/dev/null); echo size=$(cat /sys/class/block/$u/size 2>/dev/null); for d in /sys/block/dm-*; do [ "$(cat $d/dm/name 2>/dev/null)" = userdata ] && echo dm_size=$(cat $d/size 2>/dev/null) dm_slaves=$(ls $d/slaves 2>/dev/null | xargs echo 2>/dev/null); done'
grab by_name.txt          'ls -l /dev/block/by-name/'
grab block_list.txt       'ls -l /dev/block/'
# GPT lives at LBA0 of the UFS LUN, not of the userdata partition. Try the
# usual whole-LUN nodes; a failed read just yields an empty file.
grabbin gpt.bin           'dd if=/dev/block/sda bs=4096 count=64 2>/dev/null'
[ -s "$OUT/gpt.bin" ] || grabbin gpt.bin 'dd if=/dev/block/sdb bs=4096 count=64 2>/dev/null'

# --- board-specific vendor data ------------------------------------------
grab thermal.txt          'cat /data/vendor/thermal/decrypt.txt'
grab firmware_list.txt    'find /vendor/firmware_mnt -maxdepth 4 -type f'
grab power_supply.txt     'for f in /sys/class/power_supply/*/uevent; do echo --- $f; cat $f; done'
grab display_sysfs.txt    'find /sys/class/drm -maxdepth 2 2>/dev/null | head -80'
grab battery_nodes.txt    'find /sys/class/power_supply -maxdepth 2 -type f -name "capacity*" -o -name "charge*"'

cat > "$OUT/README.txt" <<'EOF'
Read-only board capture for ios-popsicle porting.

Files here are DEVICE DATA: do not commit (upstream .gitignore has /device/*).
Feed them to:  python3 tools/port/gen_byron_config.py --live DIR

Still needs a HUMAN (cannot be automated over adb):
  1. shim/hello probe  -> real framebuffer width/height/stride/format from SSPP
     registers, 16K-page support, and the address ABL loads the payload at.
     Reading the MDSS top-level registers while clocks are off can reset the SoC:
     read only the SSPP sub-blocks (see device/DT_FINDINGS.md).
  2. TLMM REAL base    -> upstream's DT says 0x0f000000 but the hardware is
     0x0f100000 on SM8850. Verify with a safe GPIO read before trusting either.
  3. Touch the main panel while interrupts_1/2 were captured, and press each
     physical key once, to confirm IRQ/GPIO assignments.
  4. Unpack the official factory ROM off the phone and run analyze_firmware.py
     on its DTBO; that covers everything the live FDT omits.
EOF

echo "== done: $(find "$OUT" -type f | wc -l | tr -d ' ') files, $(du -sh "$OUT" | cut -f1)"
echo "== next: python3 tools/port/analyze_firmware.py --dtb <ROM dtbo>/*.dtb --device $DEVICE"
echo "         python3 tools/port/gen_byron_config.py --live $OUT"
