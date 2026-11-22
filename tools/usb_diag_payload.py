#!/usr/bin/env python3
"""Derive a USB-diagnostic payload from an already-booting payload, safely.

The XNU kernel already contains the QcomXnuUsbDebug CDC ACM console (patches
0248-0253, 0258, 0365). It only runs when the boot args contain both
`pandora_usb=2` and `qcom-usb-debug=1`. This tool changes ONLY the fixed
608-byte cmdline field at payload offset 0x48 (see tools/mkpayload.py):
no kernel bytes, no ADT, no pinned extents, no partition writes.

Usage:
  tools/usb_diag_payload.py shim/loader/ampfix1/payload.bin \\
      shim/loader/usbfix1 [--level 1|2] [--drop-autoswipe] [--drop-reboot-after]

`--level 1` is the read-only controller probe (no CDC ACM), useful first if
the handover state is unknown. `--level 2` starts the USB serial console.

It copies logo.bin next to the source payload if present. The output must
then be linked with `OUT=<out-dir> bash shim/loader/build_wsl.sh` so the
link-time _payload_end covers the new payload (never use loader_repack.py).
"""
import argparse
import os
import shutil
import struct
import sys

CMDLINE = 0x48
BOOT_LINE_LENGTH = 608
MAGIC = b'SWEETXNU'
KEYS = ('pandora_usb', 'qcom-usb-debug')


def get_cmdline(blob):
    if blob[:8] != MAGIC:
        sys.exit('not a SWEETXNU payload: bad magic')
    field = blob[CMDLINE:CMDLINE + BOOT_LINE_LENGTH]
    end = field.find(b'\0')
    if end < 0:
        sys.exit('cmdline field is not NUL-terminated')
    try:
        return field[:end].decode('ascii')
    except UnicodeDecodeError:
        sys.exit('cmdline is not ASCII')


def set_cmdline(blob, text):
    data = text.encode('ascii')
    if len(data) >= BOOT_LINE_LENGTH:
        sys.exit('cmdline too long: %d >= %d' % (len(data), BOOT_LINE_LENGTH))
    field = bytearray(BOOT_LINE_LENGTH)
    field[:len(data)] = data
    blob[CMDLINE:CMDLINE + BOOT_LINE_LENGTH] = field


def strip_keys(words):
    out, skip = [], False
    for word in words:
        if skip:
            skip = False
            continue
        if '=' in word and word.split('=', 1)[0] in KEYS:
            continue
        out.append(word)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('src')
    ap.add_argument('out_dir')
    ap.add_argument('--level', type=int, choices=(1, 2), default=2)
    ap.add_argument('--drop-autoswipe', action='store_true',
                    help='remove pandora_autoswipe/at (diagnostic boot stays on the desktop)')
    ap.add_argument('--drop-reboot-after', action='store_true',
                    help='remove pandora_reboot_after (interactive setup must not be cut off)')
    ap.add_argument('--extra', default='', help='extra boot args, appended verbatim')
    a = ap.parse_args()

    blob = bytearray(open(a.src, 'rb').read())
    old = get_cmdline(blob)
    words = strip_keys(old.split())
    if a.drop_autoswipe:
        words = [w for w in words if not w.startswith(('pandora_autoswipe=', 'pandora_autoswipe_at='))]
    if a.drop_reboot_after:
        words = [w for w in words if not w.startswith('pandora_reboot_after=')]
    words += ['pandora_usb=%d' % a.level, 'qcom-usb-debug=1']
    if a.extra:
        words += a.extra.split()
    new = ' '.join(words)
    set_cmdline(blob, new)

    # The payload size and every byte outside the cmdline field are unchanged.
    os.makedirs(a.out_dir, exist_ok=True)
    dst = os.path.join(a.out_dir, 'payload.bin')
    open(dst, 'wb').write(blob)
    logo = os.path.join(os.path.dirname(a.src), 'logo.bin')
    if os.path.isfile(logo):
        shutil.copyfile(logo, os.path.join(a.out_dir, 'logo.bin'))

    check = bytearray(open(dst, 'rb').read())
    assert get_cmdline(check) == new
    assert len(check) == len(blob)
    print('cmdline_len %d/%d' % (len(new), BOOT_LINE_LENGTH - 1))
    print('cmdline:', new)
    print('payload:', dst, '(%d bytes, unchanged size)' % len(blob))
    print('next: OUT=%s bash shim/loader/build_wsl.sh' % a.out_dir)
    # adt_off/size from the header are useful to prove the ADT was untouched.
    adt_off, adt_size = struct.unpack_from('<QQ', blob, 0x20)
    print('adt: off=%#x size=%#x (unchanged)' % (adt_off, adt_size))


if __name__ == '__main__':
    main()
