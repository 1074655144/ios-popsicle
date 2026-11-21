#!/usr/bin/env python3
"""Split an Android dtbo.img into its component flattened device trees.

dtbo.img layout (all big-endian), per AOSP `libdtb`:
  dt_table_header  {magic 0xd7b7ab1e, total_size, header_size, dt_entry_size,
                    dt_entry_count, dt_entries_offset, page_size, version}
  dt_table_entry[] {dt_size, dt_offset, id, rev, custom[4]}
  ... FDT blobs, each starting with 0xd00dfeed ...

Usage:
  python3 tools/port/split_dtbo.py --dtbo device/byron/firmware/dtbo.img \
      --out-dir device/byron/firmware/dtbs
"""
import argparse
import hashlib
import json
import os
import struct

MAGIC = 0xd7b7ab1e
FDT = 0xd00dfeed


def split(data):
    if len(data) < 32 or struct.unpack_from('>I', data, 0)[0] != MAGIC:
        raise ValueError('not a dtbo.img (bad magic)')
    (_, total, hsize, esize, count, eoff, page, ver) = struct.unpack_from('>8I', data, 0)
    if hsize < 32 or esize < 32 or count < 1 or count > 4096:
        raise ValueError('implausible dtbo header')
    if eoff + count * esize > len(data):
        raise ValueError('dt entry table out of bounds')
    out = []
    for i in range(count):
        o = eoff + i * esize
        size, off = struct.unpack_from('>2I', data, o)
        ident, rev = struct.unpack_from('>2I', data, o + 8)
        custom = struct.unpack_from('>4I', data, o + 16)
        if off + size > len(data):
            raise ValueError('entry %d out of bounds (off=%d size=%d)' % (i, off, size))
        blob = data[off:off + size]
        if struct.unpack_from('>I', blob, 0)[0] != FDT:
            raise ValueError('entry %d is not an FDT (magic %08x)' % (
                i, struct.unpack_from('>I', blob, 0)[0]))
        if struct.unpack_from('>I', blob, 4)[0] != size:
            raise ValueError('entry %d: header totalsize=%d != dt_size=%d' % (
                i, struct.unpack_from('>I', blob, 4)[0], size))
        out.append({'index': i, 'dt_size': size, 'dt_offset': off,
                    'id': ident, 'rev': rev, 'custom': list(custom),
                    'sha256': hashlib.sha256(blob).hexdigest(), 'blob': blob})
    return {'total_size': total, 'header_size': hsize, 'entry_size': esize,
            'entry_count': count, 'page_size': page, 'version': ver,
            'entries': out}


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--dtbo', required=True)
    ap.add_argument('--out-dir', required=True)
    ap.add_argument('--meta', help='write entry metadata JSON here')
    a = ap.parse_args()
    info = split(open(a.dtbo, 'rb').read())
    os.makedirs(a.out_dir, exist_ok=True)
    for e in info['entries']:
        path = os.path.join(a.out_dir, 'dtb-%02d.dtb' % e['index'])
        with open(path, 'wb') as f:
            f.write(e.pop('blob'))
        print('%s  %7d bytes  sha256=%s' % (path, e['dt_size'], e['sha256']))
    if a.meta:
        os.makedirs(os.path.dirname(os.path.abspath(a.meta)), exist_ok=True)
        with open(a.meta, 'w', encoding='utf-8') as f:
            json.dump(info, f, indent=2, ensure_ascii=False)
    print('dtbo: %d entries, header total_size=%d, file size=%d' % (
        info['entry_count'], info['total_size'], os.path.getsize(a.dtbo)))


if __name__ == '__main__':
    main()
