#!/usr/bin/env python3
"""Replace one entry in a PANDFW01 firmware pack, keeping every other entry byte-identical.

  tools/replace_pack_entry.py BASE.img OUT.img NAME NEWFILE

Used to drop a freshly cloud-built NativeAdrenoMetal into the existing byron
bbonly pack without disturbing the SN / Setup / USB / backboardd-prefs work.
The pack is rewritten entry-by-entry; only NAME's bytes change.  Verify the
result with the same tool by reading NAME back, then pinwrite rawwrite into
/data/local/tmp/adspfw2.img and fastboot boot (RAM-only).
"""
import struct
import sys


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
    if len(sys.argv) != 5:
        sys.exit(__doc__)
    base, out, name, newfile = sys.argv[1:]
    new = open(newfile, 'rb').read()
    entries = read_pack(base)
    found = False
    patched = []
    for n, data in entries:
        if n == name:
            print(f'{name}: {len(data)} -> {len(new)} bytes')
            data = new
            found = True
        patched.append((n, data))
    assert found, f'no entry named {name}'
    size = write_pack(out, patched)
    print(f'{out}: {len(patched)} entries, {size} bytes')


if __name__ == '__main__':
    main()
