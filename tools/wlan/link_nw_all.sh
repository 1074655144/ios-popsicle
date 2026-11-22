#!/bin/bash
# Merge all Ath12kWifi bitcode into one Mach-O relocatable object, nw_all.o.
# Only the 27 ABI symbols consumed by xnu/patches/0361* remain external; all
# other Linux/ath12k-internal symbols are internalized so the final kernel link
# does not collide with XNU helpers.
set -e
HERE=$(cd "$(dirname "$0")" && pwd)
BC=${NW_BC_DIR:-"$(dirname "$HERE")/../wl/bc"}
OUT=${NW_OUT_DIR:-"$(dirname "$HERE")/../wl"}
mkdir -p "$OUT"
cd "$BC"
N=$(ls ./*.bc 2>/dev/null | wc -l)
echo "=== merging $N bitcode files ==="
[ "$N" -gt 100 ] || { echo "too few bitcode files"; exit 1; }
ls -1 ./*.bc > "$OUT/bc_files.txt"
llvm-link-18 @"$OUT/bc_files.txt" -o "$OUT/nw_all.bc"
echo "=== internalize non-ABI symbols ==="
opt-18 -passes=internalize -internalize-public-api-file="$HERE/abi.txt" \
  "$OUT/nw_all.bc" -o "$OUT/nw_all.int.bc"
mv "$OUT/nw_all.int.bc" "$OUT/nw_all.bc"
echo "=== compile back to Mach-O object ==="
clang -c -target arm64-apple-macos13.0 -mkernel "$OUT/nw_all.bc" -o "$OUT/nw_all.o"
echo "=== result ==="
ls -l "$OUT/nw_all.o"
file "$OUT/nw_all.o"
echo "=== key symbols ==="
llvm-nm-18 "$OUT/nw_all.o" 2>/dev/null | grep -E 'nw_wifi|nw_go|nw_bridge|nw_pci|ath12k_' | head -20 || true
echo "=== DONE ==="
