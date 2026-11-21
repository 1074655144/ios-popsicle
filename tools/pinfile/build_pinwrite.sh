#!/bin/bash
# Build the no-libc pinfile helper used for pinned extents + raw writes/reads.
# Works with the WSL/arm64 cross toolchain; no Android NDK required.
#
#   CROSS=aarch64-linux-gnu-gcc bash tools/pinfile/build_pinwrite.sh
set -euo pipefail
cd "$(dirname "$0")"
CC=${CROSS:-aarch64-linux-gnu-gcc}
command -v "$CC" >/dev/null || { echo "missing $CC" >&2; exit 1; }

"$CC" -static -nostdlib -no-pie -O2 -Wall -fno-builtin -o pinwrite pinwrite.c
sha256sum pinwrite
echo "push to phone with:"
echo "  adb push pinwrite /data/local/tmp/pinwrite"
echo "  adb shell su -c 'chmod 0755 /data/local/tmp/pinwrite; cp /data/local/tmp/pinwrite /data/local/tmp/pinfile; chmod 0755 /data/local/tmp/pinfile'"
