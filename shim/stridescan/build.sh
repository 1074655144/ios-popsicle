#!/bin/bash
# Build byron stridescan diagnostic image with WSL's aarch64 cross toolchain.
set -euo pipefail
cd "$(dirname "$0")"
CC=${CROSS:-aarch64-linux-gnu-gcc}
LD=${CROSS_LD:-aarch64-linux-gnu-ld}
OBJCOPY=${CROSS_OBJCOPY:-aarch64-linux-gnu-objcopy}
READELF=${CROSS_READELF:-aarch64-linux-gnu-readelf}
out=out
mkdir -p "$out"
flags=(-O2 -ffreestanding -fno-builtin -nostdlib -fno-pic
       -fno-stack-protector -mgeneral-regs-only -mstrict-align -Wall -Wextra)

echo "[1/5] compile start.S"
"$CC" "${flags[@]}" -c start.S -o "$out/start.o"
echo "[2/5] compile stridescan.c"
"$CC" "${flags[@]}" -c stridescan.c -o "$out/stridescan.o"
echo "[3/5] relocation audit"
if "$READELF" -r "$out/stridescan.o" | grep -qE 'R_AARCH64_ABS64|R_AARCH64_ABS32'; then
    echo "ERROR: absolute relocation" >&2
    "$READELF" -r "$out/stridescan.o" | grep -E 'R_AARCH64_ABS' >&2
    exit 1
fi
echo "      ok: no absolute relocations"
echo "[4/5] link + objcopy"
"$LD" -T hello.ld --build-id=none "$out/start.o" "$out/stridescan.o" -o "$out/stridescan.elf"
"$OBJCOPY" -O binary "$out/stridescan.elf" "$out/Image"
echo "[5/5] bootimg"
python3 ../../tools/mkbootimg_v4.py "$out/Image" "$out/stridescan-boot.img"
python3 ../../tools/bootimg_info.py "$out/stridescan-boot.img"
echo "image_size=$(stat -c %s "$out/Image" 2>/dev/null || stat -f %z "$out/Image") bytes"
sha256sum "$out/stridescan-boot.img"
