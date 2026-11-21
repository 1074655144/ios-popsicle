#!/bin/bash
# Build pandora-loader with WSL's aarch64-linux-gnu cross toolchain (same as shim/fbverify).
# OUT=dir names the staging dir that has payload.bin + logo.bin (from wsl/make_phone_payload.sh).
set -euo pipefail
cd "$(dirname "$0")"
CC=${CROSS:-aarch64-linux-gnu-gcc}
LD=${CROSS_LD:-aarch64-linux-gnu-ld}
OBJCOPY=${CROSS_OBJCOPY:-aarch64-linux-gnu-objcopy}
READELF=${CROSS_READELF:-aarch64-linux-gnu-readelf}
src=${OUT:-out}
out=wsl-out
mkdir -p "$out"
[ -f "$src/payload.bin" ] || { echo "missing $src/payload.bin" >&2; exit 1; }
[ -f "$src/logo.bin" ] || : > "$src/logo.bin"

flags=(-O2 -ffreestanding -fno-builtin -nostdlib -fno-pic
       -fno-stack-protector -mgeneral-regs-only -mstrict-align -Wall -Wextra -Werror)

echo "[1/4] compile start.S / loader.c / payload.S / logo.S"
"$CC" "${flags[@]}" -c start.S -o "$out/start.o"
"$CC" "${flags[@]}" -c loader.c -o "$out/loader.o"
"$CC" "${flags[@]}" -DPAYLOAD=\"$src/payload.bin\" -c payload.S -o "$out/payload.o"
"$CC" "${flags[@]}" -DLOGO=\"$src/logo.bin\" -c logo.S -o "$out/logo.o"

echo "[2/4] relocation audit"
if "$READELF" -r "$out/loader.o" | grep -qE 'R_AARCH64_ABS64|R_AARCH64_ABS32'; then
    echo "ERROR: absolute relocation in loader.c (loaded at unknown address)" >&2
    "$READELF" -r "$out/loader.o" | grep -E 'R_AARCH64_ABS' >&2
    exit 1
fi
echo "      ok: no absolute relocations"

echo "[3/4] link + objcopy + embed verification"
"$LD" -T loader.ld --build-id=none "$out/start.o" "$out/loader.o" "$out/logo.o" "$out/payload.o" -o "$out/loader.elf"
"$OBJCOPY" -O binary "$out/loader.elf" "$out/Image"
python3 - "$out/Image" "$src/payload.bin" <<'PY'
import struct, sys
img = open(sys.argv[1], 'rb').read(); pl = open(sys.argv[2], 'rb').read()
size = struct.unpack_from('<Q', img, 16)[0]
assert img[0x38:0x3c] == b'ARM\x64', 'no arm64 Image magic'
assert size == len(img), (hex(size), hex(len(img)))
off = img.find(pl[:64])
assert off > 0 and off % 4096 == 0 and img[off:off + len(pl)] == pl, 'payload not embedded'
print('Image %d bytes, payload at 0x%x (%d bytes)' % (len(img), off, len(pl)))
PY

echo "[4/4] bootimg + info"
python3 ../../tools/mkbootimg_v4.py "$out/Image" "$out/loader-boot.img"
python3 ../../tools/bootimg_info.py "$out/loader-boot.img"
echo "image_size=$(stat -c %s "$out/Image" 2>/dev/null || stat -f %z "$out/Image") bytes"
sha256sum "$out/loader-boot.img"
