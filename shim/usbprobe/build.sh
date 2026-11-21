#!/bin/bash
# Build the byron USB CDC ACM probe with WSL's aarch64-linux-gnu cross toolchain.
# Pure freestanding: no libc, no NDK needed. Produces out/Image and out/usbprobe-boot.img.
set -euo pipefail
cd "$(dirname "$0")"
CC=${CROSS:-aarch64-linux-gnu-gcc}
LD=${CROSS_LD:-aarch64-linux-gnu-ld}
OBJCOPY=${CROSS_OBJCOPY:-aarch64-linux-gnu-objcopy}
READELF=${CROSS_READELF:-aarch64-linux-gnu-readelf}
out=out
mkdir -p "$out"

# Position-independent-at-load: flags 0xa means "anywhere in RAM, 4K pages".
# No ABS64 relocations allowed in C (Image lands at an unknown physical address).
flags=(-O2 -ffreestanding -fno-builtin -nostdlib -fno-pic
       -fno-stack-protector -mgeneral-regs-only -mstrict-align -Wall -Wextra)

echo "[1/5] compile start.S"
"$CC" "${flags[@]}" -c start.S -o "$out/start.o"

echo "[2/5] compile Dwc3.c"
"$CC" "${flags[@]}" -c Dwc3.c -o "$out/Dwc3.o"

echo "[3/5] compile usbprobe.c"
"$CC" "${flags[@]}" -c usbprobe.c -o "$out/usbprobe.o"

echo "[4/5] relocation audit (reject absolute relocations in C)"
if "$READELF" -r "$out/usbprobe.o" "$out/Dwc3.o" | grep -qE 'R_AARCH64_ABS64|R_AARCH64_ABS32'; then
	echo "ERROR: absolute relocation in C objects — Image is loaded at an unknown address" >&2
	"$READELF" -r "$out/usbprobe.o" "$out/Dwc3.o" | grep -E 'R_AARCH64_ABS' >&2
	exit 1
fi
echo "      ok: no absolute relocations"

echo "[5/5] link + objcopy + bootimg"
"$LD" -T usbprobe.ld --build-id=none "$out/start.o" "$out/Dwc3.o" "$out/usbprobe.o" -o "$out/usbprobe.elf"
"$OBJCOPY" -O binary "$out/usbprobe.elf" "$out/Image"
python3 ../../tools/mkbootimg_v4.py "$out/Image" "$out/usbprobe-boot.img"
python3 ../../tools/bootimg_info.py "$out/usbprobe-boot.img"
echo "image_size=$(stat -c %s "$out/Image" 2>/dev/null || stat -f %z "$out/Image") bytes"
sha256sum "$out/usbprobe-boot.img"
