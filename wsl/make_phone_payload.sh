#!/bin/bash
# make_phone_payload.sh RUNDIR [extra cmdline]
# Build phone ADT + XNU payload for shim/loader into shim/loader/NAME/.
#
# Environment:
#   REPO       repo root (default: parent of this script)
#   KERNEL     kernel Mach-O (default RUNDIR/xnu-kernel/kernel.development.pandora)
#   NAME       output name (default out)
#   CPUS       cores to start (default 1)
#   DEBUG      0x8 panics restart; 0xc waits, DB_NMI (default 0xc)
#   RD         ufsroot0 for root on UFS + ADTFLAGS --root-extents; md0 uses RAM disk
#   ADTFLAGS   e.g. "--root-extents device/<codename>/extents/iosroot.json --log-extents ..."
#   TRUSTCACHE "FILE..." from the IPSW, first one is StaticTrustCache
#   LOGO       applelogo im4p (default /opt/work/ipsw/logo/applelogo@3x~iphone.im4p)
set -e
R=${1:?usage: make_phone_payload.sh RUNDIR [extra cmdline]}
EXTRA=${2:-}
N=${NAME:-out}
CPUS=${CPUS:-1}
RD=${RD:-md0}
DEBUG=${DEBUG:-0xc}
HERE=$(cd "$(dirname "$0")" && pwd)
REPO=${REPO:-$(cd "$HERE/.." && pwd)}
T=${TOOLS_DIR:-/opt/work/tools}
mkdir -p "$T"

# Use the tools committed in this repo. The temp copy receives the local
# mkpayload.py adjustment below; the originals stay untouched.
for f in adt.py mkadt.py mkpayload.py mkadt_pandora.py addtrustcache.py; do
  tr -d '\r' < "$REPO/tools/$f" > "$T/$f"
done

# Kernel VA that maps to phys_base: 32 MB below the lowest segment instead of
# the mach header, so original kexts placed below our kernel are copied too.
sed -i "s/virt_base = text\['vmaddr'\] & ~(0x2000000 - 1)/virt_base = min(s['vmaddr'] for s in segs) \& ~(0x2000000 - 1)/" "$T/mkpayload.py"
grep -q "virt_base = min(s\['vmaddr'\] for s in segs) & ~(0x2000000 - 1)" "$T/mkpayload.py"

K=${KERNEL:-$R/xnu-kernel/kernel.development.pandora}
O=$R/phone-$N
rm -rf "$O"
mkdir -p "$O"
RAMDISK=()
[[ $RD == md0 ]] && RAMDISK=(--ramdisk /opt/work/init/sweet-init)

python3 "$T/mkadt_pandora.py" "$O/phone.adt" ${ADTFLAGS:-} 2>&1 | tail -2
python3 "$T/mkpayload.py" "$K" "$O/phone.adt" "$O/payload.bin" \
  --cmdline "debug=$DEBUG serial=3 cpus=$CPUS keepsyms=1 -enable_kprintf_spam -noprogress rd=$RD $EXTRA" \
  "${RAMDISK[@]}" 2>&1 | tail -4

if [[ -n ${TRUSTCACHE:-} ]]; then
  python3 "$T/addtrustcache.py" "$O/payload.bin" "$O/payload-tc.bin" $TRUSTCACHE
  mv "$O/payload-tc.bin" "$O/payload.bin"
fi

mkdir -p "$REPO/shim/loader/$N"
cp "$O/payload.bin" "$REPO/shim/loader/$N/payload.bin"

# Apple logo comes from the user's IPSW and is never committed.
LOGO=${LOGO:-/opt/work/ipsw/logo/applelogo@3x~iphone.im4p}
if [[ -f $LOGO ]]; then
  python3 -I "$REPO/tools/bootlogo.py" "$LOGO" "$REPO/shim/loader/$N/logo.bin"
else
  rm -f "$REPO/shim/loader/$N/logo.bin"
fi
sha256sum "$K" "$O/payload.bin"
