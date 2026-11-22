#!/bin/bash
# Prepare WSL for building the iOS HFS+ root (tools/mkiosroot from ios-fuxi):
#  1. hfsplus.ko for the running WSL kernel (the stock WSL kernel has no HFS+): build
#     microsoft/WSL2-Linux-Kernel at the matching tag with HFSPLUS_FS=m (MODVERSIONS is on,
#     so a full build is needed for Module.symvers).
#  2. apfs-fuse (sgan81) to read the IPSW's APFS images.
#  3. Extract OS / SystemOS / AppOS from the IPSW to /opt/work/ipsw (unzip checks CRCs).
# Clones use a mirror per command only (never a global url.insteadOf).
set -euo pipefail
MIRROR=https://ghfast.top/https://github.com/
# Target iOS is the project-native 16.7.16 (20H392); see profiles/byron.env.
# Override IPSW=... for a different build. Windows path: F:/i4Tools9/Firmware/...
IPSW=${IPSW:-/mnt/f/i4Tools9/Firmware/iPhone10,3,iPhone10,6_16.7.16_20H392_Restore.ipsw}
W=/opt/work
REPO=${REPO:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}
log() { echo "== $(date +%T) $*"; }

log apt
DEBIAN_FRONTEND=noninteractive apt-get install -y -q libelf-dev dwarves cpio bc flex bison \
	libfuse3-dev fuse3 zlib1g-dev libbz2-dev libattr1-dev cmake g++ git >/dev/null

KVER=$(uname -r)                       # 6.6.87.2-microsoft-standard-WSL2
TAG=linux-msft-wsl-${KVER%%-microsoft*}
if [ ! -f $W/wslk/fs/hfsplus/hfsplus.ko ]; then
	log "kernel $TAG"
	[ -d $W/wslk ] || git -c url.$MIRROR.insteadOf=https://github.com/ clone -q --depth 1 -b $TAG \
		https://github.com/microsoft/WSL2-Linux-Kernel $W/wslk
	cd $W/wslk
	zcat /proc/config.gz > .config
	scripts/config --module HFSPLUS_FS --disable LOCALVERSION_AUTO
	make -s olddefconfig
	make -s -j"$(nproc)" LOCALVERSION= >$W/wslk-build.log 2>&1 || { tail -30 $W/wslk-build.log; exit 1; }
fi
modinfo -F vermagic $W/wslk/fs/hfsplus/hfsplus.ko
grep -qw hfsplus /proc/filesystems || insmod $W/wslk/fs/hfsplus/hfsplus.ko
grep -w hfsplus /proc/filesystems

if ! command -v apfs-fuse >/dev/null; then
	log apfs-fuse
	[ -d $W/apfs-fuse ] || git -c url.$MIRROR.insteadOf=https://github.com/ clone -q --recursive \
		https://github.com/sgan81/apfs-fuse $W/apfs-fuse
	cd $W/apfs-fuse && mkdir -p build && cd build
	cmake -DUSE_FUSE3=ON .. >/dev/null && make -s -j"$(nproc)" && install -m 755 apfs-fuse apfsutil /usr/local/bin/
fi
command -v apfs-fuse

log "ipsw images"
mkdir -p $W/ipsw && cd $W/ipsw
# Derive build-specific names from THIS IPSW first (the tool reads BuildManifest.plist
# straight out of the .ipsw zip, no extraction needed). Nothing is hard-coded per build.
ASSETS=${IPSW_ASSETS:-$REPO/device/byron/ipsw_assets.env}
python3 "$REPO/tools/port/discover_ipsw_assets.py" \
	"$IPSW" -o "$ASSETS" 2>&1 | tail -5
# shellcheck disable=SC1090
. "$ASSETS"
# CRYPTEX_DMGS now holds the real cryptex dmg names for this IPSW (e.g. iOS 16.5 / 20F66).
# shellcheck disable=SC2086
unzip -o -q "$IPSW" $CRYPTEX_DMGS Firmware/all_flash/DeviceTree.d22ap.im4p BuildManifest.plist
ls -l $W/ipsw $W/ipsw/Firmware/all_flash
log done
