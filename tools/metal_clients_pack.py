#!/usr/bin/env python3
"""Set NativeAdrenoMetal.clients in a PANDFW01 firmware pack.

The Metal plugin hands a GPU device only to processes listed in
/System/Library/Extensions/NativeAdrenoMetal.clients.  The current byron pack
uses "*" (every process), but only backboardd is a proven Metal client on
iOS 16 here: SpringBoard/chronod that also got a device use CoreImage, which
has no CPU fallback and misses several private device methods in our plugin.
Restricting the device to backboardd lets those processes use their software
renderer again, which is the first-stage configuration GPU_PLAN.md recommends.

Usage:
  tools/metal_clients_pack.py BASE.img OUT.img NAME [NAME ...]

The pack is kept byte-identical except for the clients file and files.txt.
An "! - PATH" (unlink) line is inserted before the clients install line so the
installer always re-applies it even after a persistent iOS data partition has
an older copy.  Device installation is still RAM-only: pinwrite rawwrite into
the pinned 40 MiB /data/local/tmp/adspfw2.img, then fastboot boot.
"""
import os
import struct
import sys

CLIENTS_PATH = '/System/Library/Extensions/NativeAdrenoMetal.clients'


def read_pack(path):
    with open(path, 'rb') as f:
        head = f.read(4096)
        assert head[:8] == b'PANDFW01', 'not a PANDFW01 pack'
        n, = struct.unpack_from('<I', head, 8)
        assert 0 < n < 63, 'bad entry count'
        entries = []
        for i in range(n):
            raw, off, size = struct.unpack_from('<48sQQ', head, 16 + 64 * i)
            name = raw.rstrip(b'\0').decode()
            f.seek(off)
            entries.append((name, f.read(size)))
    return entries


def write_pack(path, entries):
    out_entries, blobs, off = [], [], 4096
    for name, data in entries:
        assert len(name) < 48, name
        out_entries.append(struct.pack('<48sQQ', name.encode(), off, len(data)))
        blob = data + b'\0' * (-len(data) % 4096)
        blobs.append(blob)
        off += len(blob)
    head = b'PANDFW01' + struct.pack('<II', len(entries), 0) + b''.join(out_entries)
    head += b'\0' * (4096 - len(head))
    with open(path, 'wb') as out:
        out.write(head)
        for blob in blobs:
            out.write(blob)
    return off


def main():
    if len(sys.argv) < 4:
        sys.exit(__doc__)
    base, out, names = sys.argv[1], sys.argv[2], sys.argv[3:]
    for name in names:
        assert ' ' not in name and name != '*', name
    entries = read_pack(base)
    found = False
    patched = []
    for name, data in entries:
        if name == 'NativeAdrenoMetal.clients':
            data = (' '.join(names) + '\n').encode()
            found = True
        elif name == 'files.txt':
            text = data.decode()
            target = f'NativeAdrenoMetal.clients 644 {CLIENTS_PATH}'
            assert text.count(target) == 1, 'no clients install line'
            if f'! - {CLIENTS_PATH}\n' not in text:
                text = text.replace(target, f'! - {CLIENTS_PATH}\n{target}', 1)
            data = text.encode()
        patched.append((name, data))
    assert found, 'no NativeAdrenoMetal.clients entry'
    size = write_pack(out, patched)
    print(f'{out}: {len(patched)} entries, {size} bytes, clients={names}')


if __name__ == '__main__':
    main()
