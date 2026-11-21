#!/bin/bash
# Friendly wrapper around build_root.sh for a specific IPSW/DMG triple.
#
#   mkiosroot.sh OS.dmg SYSTEMOS.dmg APPOS.dmg OUT.img [SIZE]
#
# It derives CRYPTEX_DMGS/IPSW_DIR/OUT/SIZE from the arguments and delegates to
# build_root.sh, so there is only one implementation of the HFS+ image layout.
set -euo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
[[ $# -ge 4 ]] || { echo "usage: mkiosroot.sh OS.dmg SYSTEMOS.dmg APPOS.dmg OUT.img [SIZE]" >&2; exit 2; }
os=$(realpath "$1"); sysos=$(realpath "$2"); appos=$(realpath "$3"); out=$4; size=${5:-16G}
[[ ! -e $out ]] || { echo "refusing to overwrite $out" >&2; exit 1; }
[[ $(dirname "$os") == $(dirname "$sysos") && $(dirname "$os") == $(dirname "$appos") ]] || {
  echo "all three DMGs must be in the same directory" >&2; exit 2;
}

export IPSW_DIR=$(dirname "$os")
export CRYPTEX_DMGS="$(basename "$os") $(basename "$sysos") $(basename "$appos")"
export OUT=$out SIZE=$size
exec "$HERE/build_root.sh"
