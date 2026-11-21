#!/bin/bash
# Build byron fbverify with WSL's aarch64-linux-gnu cross toolchain.
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

echo "[1/4] compile start.S"
"$CC" "${flags[@]}" -c start.S -o "$out/start.o"
echo "[2/4] compile fbverify.c"
"$CC" "${flags[@]}" -c fbverify.c -o "$out/fbverify.o"
echo "[3/4] relocation audit"
if "$READELF" -r "$out/fbverify.o" | grep -qE 'R_AARCH64_ABS64|R_AARCH64_ABS32'; then
    echo "ERROR: absolute relocation (Image loaded at unknown address)" >&2
    "$READELF" -r "$out/fbverify.o" | grep -E 'R_AARCH64_ABS' >&2
    exit 1
fi
echo "      ok: no absolute relocations"
echo "[4/4] link + objcopy + bootimg"
"$LD" -T hello.ld --build-id=none "$out/start.o" "$out/fbverify.o" -o "$out/fbverify.elf"
"$OBJCOPY" -O binary "$out/fbverify.elf" "$out/Image"
python3 ../../tools/mkbootimg_v4.py "$out/Image" "$out/fbverify-boot.img"
python3 ../../tools/bootimg_info.py "$out/fbverify-boot.img"
echo "image_size=$(stat -c %s "$out/Image" 2>/dev/null || stat -f %z "$out/Image") bytes"
sha256sum "$out/fbverify-boot.img"
