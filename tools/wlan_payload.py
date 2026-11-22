#!/usr/bin/env python3
"""Derive a Wi-Fi-enabled payload from an already-booting payload.

Changes ONLY the fixed 608-byte cmdline field at payload offset 0x48:
adds/replaces `pandora_wlan=2` (ath12k board path in the XNU driver).
No kernel bytes, no ADT, no pinned extents, no partition writes.

Usage: tools/wlan_payload.py shim/loader/snfix/payload.bin shim/loader/wififix
Then:  OUT=shim/loader/wififix bash shim/loader/build_wsl.sh
"""
import os, shutil, sys, struct

CMDLINE = 0x48
LEN = 608
MAGIC = b'SWEETXNU'

def main():
    src, out_dir = sys.argv[1], sys.argv[2]
    blob = bytearray(open(src, 'rb').read())
    assert blob[:8] == MAGIC, 'not a SWEETXNU payload'
    field = bytes(blob[CMDLINE:CMDLINE+LEN])
    end = field.find(b'\0')
    assert end >= 0, 'cmdline not terminated'
    cmd = field[:end].decode('ascii')
    words = [w for w in cmd.split() if not w.startswith('pandora_wlan=')]
    words.append('pandora_wlan=2')
    new = ' '.join(words)
    data = new.encode('ascii')
    assert len(data) < LEN, 'cmdline too long'
    nb = bytearray(LEN)
    nb[:len(data)] = data
    blob[CMDLINE:CMDLINE+LEN] = nb
    os.makedirs(out_dir, exist_ok=True)
    dst = os.path.join(out_dir, 'payload.bin')
    open(dst, 'wb').write(blob)
    logo = os.path.join(os.path.dirname(src), 'logo.bin')
    if os.path.isfile(logo):
        shutil.copyfile(logo, os.path.join(out_dir, 'logo.bin'))
    check = open(dst, 'rb').read()
    got = bytes(check[CMDLINE:CMDLINE+LEN]).split(b'\0')[0].decode('ascii')
    assert got == new and len(check) == len(blob)
    adt_off, adt_size = struct.unpack_from('<QQ', blob, 0x20)
    print('cmdline_len %d/%d' % (len(new), LEN-1))
    print('cmdline:', new)
    print('payload:', dst, len(blob), 'bytes (size unchanged)')
    print('adt off=%#x size=%#x (unchanged)' % (adt_off, adt_size))
    print('next: OUT=%s bash shim/loader/build_wsl.sh' % out_dir)

if __name__ == '__main__':
    main()
