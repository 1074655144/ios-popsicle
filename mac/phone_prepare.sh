#!/bin/bash
# Put the iOS root on an Android phone in two PINNED files under /data/local/tmp.
# No partitions, boot images or Android system files are changed.
#
#   IOS_DEVICE=<codename> IOS_EXTENTS_DIR=device/<codename>/extents \
#   ADB_BIN=<adb> bash mac/phone_prepare.sh IMAGE [--yes]
#
# Files on the phone:
#   /data/local/tmp/pinwrite       helper (also copied to pinfile for log tools)
#   /data/local/tmp/iosroot.img   16 GiB pinned; HFS+ root image lives here
#   /data/local/tmp/ioslog.img    8 MiB pinned; kernel ring log (patch 0129)
#
# Without --yes this only checks and prints what would happen. The extents JSON
# files are real-time device data: keep them in device/<codename>/extents, which
# .gitignore excludes; do not commit them.
#
# Undo: adb shell su -c 'rm -f /data/local/tmp/iosroot.img /data/local/tmp/ioslog.img /data/local/tmp/iosroot.src.img /data/local/tmp/pinwrite /data/local/tmp/pinfile'
set -euo pipefail

IMG=${1:?image}
YES=${2:-}
M=$(cd "$(dirname "$0")" && pwd)
SRC=$M/..
DEVICE=${IOS_DEVICE:-popsicle}
EXDIR=${IOS_EXTENTS_DIR:-$M/extents}
ADB_BIN=${ADB_BIN:-adb}
HOST_PINWRITE=${PINWRITE_BIN:-$SRC/tools/pinfile/pinwrite}
P=/data/local/tmp/pinwrite
PF=/data/local/tmp/pinfile
ROOTF=/data/local/tmp/iosroot.img
LOGF=/data/local/tmp/ioslog.img
SRCIMG=/data/local/tmp/iosroot.src.img
ROOT_SIZE=17179869184
LOG_MB=8

su() { "$ADB_BIN" shell "su -c '$*'" | tr -d '\r'; }

echo "== checks ($DEVICE, extents -> $EXDIR)"
[[ $("$ADB_BIN" shell getprop ro.product.device | tr -d '\r') == "$DEVICE" ]] || { echo "no $DEVICE on adb"; exit 1; }
[[ $(su id -u) == 0 ]] || { echo "no root on the phone"; exit 1; }
[[ -f $HOST_PINWRITE ]] || { echo "missing $HOST_PINWRITE (run tools/pinfile/build_pinwrite.sh)"; exit 1; }

size=$(wc -c < "$IMG" | tr -d ' ')
[[ $size == $ROOT_SIZE ]] || { echo "image is $size bytes, want $ROOT_SIZE"; exit 1; }
[[ $(dd if="$IMG" bs=1 skip=1024 count=2 2>/dev/null) == HX ]] || { echo "image has no HFSX signature"; exit 1; }
free_kb=$("$ADB_BIN" shell df -k /data | tail -1 | awk '{print $4}' | tr -d '\r')
echo "free on /data: $((free_kb / 1048576)) GiB"
# Room for the pinned root, the temporary source image and the log.
[[ $free_kb -gt $((34 * 1048576)) ]] || { echo "need 34 GiB free on /data"; exit 1; }
for f in $ROOTF $LOGF $SRCIMG; do
  [[ -z $(su "ls $f 2>/dev/null") ]] || { echo "$f already exists: not touching it"; exit 1; }
done
echo "would: push pinwrite, create $ROOTF (16384 MiB) and $LOGF (${LOG_MB} MiB) pinned,"
echo "       rawwrite the image into $ROOTF's blocks, verify the raw hash, then save extents."
[[ $YES == --yes ]] || { echo "checked only; --yes does it"; exit 0; }

echo "== pinwrite"
"$ADB_BIN" push "$HOST_PINWRITE" "$P" >/dev/null
su "chmod 0755 $P; cp -f $P $PF; chmod 0755 $PF"

echo "== pinned files"
su "$P create $ROOTF 16384"
su "$P create $LOGF $LOG_MB"
su "$P status $ROOTF"
su "$P status $LOGF"

echo "== image -> phone (16 GiB)"
"$ADB_BIN" push "$IMG" "$SRCIMG" >/dev/null
DEV=$(su "readlink -f /dev/block/by-name/userdata")
echo "userdata is $DEV"
su "cat $SRCIMG | $P rawwrite $ROOTF $DEV"
su "rm -f $SRCIMG"

echo "== verify (SHA-256 of the phone's raw blocks)"
if command -v sha256sum >/dev/null; then HASH=sha256sum; else HASH='shasum -a 256'; fi
mac=$($HASH "$IMG" | awk '{print $1}')
phone=$("$ADB_BIN" exec-out su -c "$P rawreadat $ROOTF $DEV 0 $ROOT_SIZE 2>/dev/null" | $HASH | awk '{print $1}')
echo "host  $mac"
echo "phone $phone"
[[ $mac == $phone ]] || { echo "MISMATCH: do not boot"; exit 1; }

echo "== extents (device-specific, local only)"
mkdir -p "$EXDIR"
su "$P extents $ROOTF --json" > "$EXDIR/iosroot.json"
su "$P extents $LOGF --json" > "$EXDIR/ioslog.json"
echo "iOS root pinned and verified; never commit $EXDIR"
