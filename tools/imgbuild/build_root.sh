#!/bin/bash
# Build a SWEET iOS root image from the three cryptex DMGs of YOUR IPSW.
# Runs entirely on the computer; no phone partitions are touched.
#
# Strategy: apfs-fuse -> local staging dir (fast RW, run tweaks here) -> tar ->
#           guestfish tar-in into a NON-journaled HFS+ image. (Journaled HFS+
#           is read-only under the Linux hfsplus driver.)
#
# Environment overrides:
#   APFS        path to apfs-fuse binary
#   IPSW_DIR    directory holding the extracted cryptex DMGs
#   IPSW_ASSETS sourceable env from tools/port/discover_ipsw_assets.py
#   CRYPTEX_DMGS="OS.dmg SystemOS.dmg AppOS.dmg"
#   OUT, SIZE, WORK, STAGE, LOG, TARBALL, TWEAKS
set -euo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
APFS=${APFS:-/opt/work/tools/apfs-fuse-src/build/apfs-fuse}
IPSW_DIR=${IPSW_DIR:-/opt/work/ipsw}
OUT=${OUT:-/opt/work/iosroot.img}
SIZE=${SIZE:-16G}
WORK=${WORK:-/opt/work/imgbuild_work}
STAGE=${STAGE:-/opt/work/img_stage}
LOG=${LOG:-/opt/work/imgbuild.log}
TARBALL=${TARBALL:-/opt/work/iosroot_stage.tar}
TWEAKS=${TWEAKS:-$HERE/sweet-root-tweaks.py}

# Build-specific DMG names come from BuildManifest.plist. The fallback is the
# project-native iOS 16.7.16 (20H392) triple; never guess names for a new IPSW.
if [[ -n ${IPSW_ASSETS:-} && -f $IPSW_ASSETS ]]; then
  # shellcheck disable=SC1090
  . "$IPSW_ASSETS"
fi
read -r -a DMGS <<< "${CRYPTEX_DMGS:-087-86698-044.dmg 087-86593-047.dmg 087-86715-047.dmg}"
[[ ${#DMGS[@]} -eq 3 ]] || { echo "expected 3 cryptex DMGs, got ${#DMGS[@]}" >&2; exit 2; }

say(){ echo "[$(date +%H:%M:%S)] $*" | tee -a "$LOG"; }
: > "$LOG"
say "=== build_root.sh start (local stage + tar-in) ==="
[[ $(id -u) -eq 0 ]] || { say "ERROR: must run as root"; exit 1; }
for t in "$APFS" /usr/sbin/mkfs.hfsplus /usr/sbin/fsck.hfsplus /usr/bin/rsync /usr/bin/guestfish /usr/bin/tar; do
  [[ -x $t ]] || { say "MISSING $t"; exit 1; }
done
for d in "${DMGS[@]}"; do
  [[ -f $IPSW_DIR/$d ]] || { say "MISSING $IPSW_DIR/$d (run tools/port/discover_ipsw_assets.py first)"; exit 2; }
done
[[ -f $TWEAKS ]] || { say "MISSING $TWEAKS"; exit 2; }

# Clean stale mounts from an interrupted run.
for m in os sysos appos root; do
  mountpoint -q "$WORK/$m" 2>/dev/null && fusermount -u "$WORK/$m" 2>/dev/null || true
done
rm -rf "$WORK" "$STAGE"
mkdir -p "$WORK"/{os,sysos,appos} "$STAGE/root"
trap 'for m in os sysos appos; do mountpoint -q "$WORK/$m" 2>/dev/null && fusermount -u "$WORK/$m" 2>/dev/null || true; done' EXIT

apfs_mount(){
  local dmg=$1 name=$2
  ln -sf "$dmg" "$WORK/$name.dmg"
  say "mount $name: $(basename "$dmg")"
  "$APFS" "$WORK/$name.dmg" "$WORK/$name" >>"$LOG" 2>&1 &
  sleep 7
  mountpoint -q "$WORK/$name" || { say "FAIL mount $name"; tail -20 "$LOG"; exit 2; }
}
apfs_mount "$IPSW_DIR/${DMGS[0]}" os
apfs_mount "$IPSW_DIR/${DMGS[1]}" sysos
apfs_mount "$IPSW_DIR/${DMGS[2]}" appos

R=$STAGE/root
copy(){
  mkdir -p "$2"
  say "rsync $1 (started)"
  rsync -aH --numeric-ids "$1/" "$2/" >>"$LOG" 2>&1 || { say "FAIL rsync $1"; tail -20 "$LOG"; exit 5; }
  say "rsync $1 (done)"
}
copy "$WORK/os/root" "$R"
copy "$WORK/sysos/root" "$R/private/preboot/Cryptexes/OS"
copy "$WORK/appos/root" "$R/private/preboot/Cryptexes/App"

say "hardlink shared cache + cryptex files"
dsc=private/preboot/Cryptexes/OS/System/Library/Caches/com.apple.dyld
mkdir -p "$R/System/Library/Caches/com.apple.dyld"
for f in "$R/$dsc"/*; do ln "$f" "$R/System/Library/Caches/com.apple.dyld/${f##*/}" 2>/dev/null || true; done
for c in OS App; do
  (cd "$R/private/preboot/Cryptexes/$c" && find . ! -type d ! -path "./System/Library/Caches/com.apple.dyld/*" 2>/dev/null) | while IFS= read -r f; do
    f=${f#./}
    if [[ ! -e $R/$f && ! -L $R/$f ]]; then
      mkdir -p "$R/$(dirname "$f")"
      src="$R/private/preboot/Cryptexes/$c/$f"
      if [[ -L $src ]]; then cp -P "$src" "$R/$f"; else ln "$src" "$R/$f" 2>/dev/null || cp -a "$src" "$R/$f"; fi
    fi
  done
done

say "log stores + system keybag"
db="$R/private/var/db"
install -d -o 272 -g 272 -m 0751 "$db/diagnostics"
install -d -o 272 -g 272 -m 0755 "$db/uuidtext" "$db/diagnostics/timesync"
for d in diagnostics uuidtext diagnostics/timesync; do
  install -o 272 -g 272 -m 0644 /dev/null "$db/$d/.migrated"
done
# no-effaceable-storage: keybagd parses systembag.kb as a PLAIN PLIST.
# Bare KeyBagKeys text caused: Could not create dictionary from stream ->
# FATAL KEYBAG ERROR -> reboot. Keep the binary plist and 0777 directory.
install -d -m 0777 -o 0 -g 0 "$R/private/var/keybags"
python3 -c 'import plistlib,sys; plistlib.dump({"KeyBagKeys": b"SWEET"}, open(sys.argv[1], "wb"), fmt=plistlib.FMT_BINARY)' "$R/private/var/keybags/systembag.kb"
chown 0:0 "$R/private/var/keybags/systembag.kb"
chmod 0600 "$R/private/var/keybags/systembag.kb"

say "apply sweet-root-tweaks"
python3 "$TWEAKS" "$R" >>"$LOG" 2>&1 || { say "FAIL tweaks"; tail -20 "$LOG"; exit 6; }
python3 -c 'import plistlib,sys; d=plistlib.load(open(sys.argv[1],"rb")); print(d.get("ProductBuildVersion"), d.get("ProductVersion"))' \
  "$R/System/Library/CoreServices/SystemVersion.plist" | tee -a "$LOG"

say "stage size: $(du -sh "$R" | cut -f1)"
say "tar stage (preserve hardlinks/perms)"
rm -f "$TARBALL"
tar -cf "$TARBALL" -C "$R" . || { say "FAIL tar"; exit 7; }
say "tarball: $(ls -lh "$TARBALL" | awk '{print $5}')"

say "create $SIZE non-journaled HFS+ image"
rm -f "$OUT"
truncate -s "$SIZE" "$OUT"
mkfs.hfsplus -s -v iOSRoot "$OUT" >>"$LOG" 2>&1 || { say "FAIL mkfs"; exit 3; }

say "guestfish tar-in (fast path)"
timeout 1800 guestfish -a "$OUT" <<EOF >>"$LOG" 2>&1 || { say "FAIL tar-in"; tail -30 "$LOG"; exit 8; }
run
mount /dev/sda /
tar-in $TARBALL /
EOF
say "tar-in done"

say "fsck HFS+"
fsck.hfsplus -f -y "$OUT" 2>&1 | grep -v "Illegal name" | tail -12 | tee -a "$LOG" || true
fsck.hfsplus -f -n "$OUT" 2>&1 | grep -v "Illegal name" | tail -6 | tee -a "$LOG" || true
say "=== DONE: $OUT ($(stat -c%s "$OUT") bytes) ==="
sha256sum "$OUT" | tee -a "$LOG"
