#!/usr/bin/env python3
"""Extract the concatenated base FDTs from an Android vendor_boot.img (v4).

Modern Qualcomm devices ship the SoC base device tree inside vendor_boot's
`dtb` section (header v4), as several concatenated FDTs -- one per board/RAM
variant. The dtbo.img overlays are applied on top of one of these. Both are
needed for a complete offline board description.

Usage:
  python3 tools/port/extract_boot_dtbs.py \
      --vendor-boot device/byron/firmware/vendor_boot.img \
      --out-dir device/byron/firmware/base_dtbs \
      --meta device/byron/firmware/base_dtbs.json
"""
import argparse
import hashlib
import json
import os
import struct
import sys

FDT_MAGIC = 0xd00dfeed
VNDRBOOT = b'VNDRBOOT'


def vendor_boot_dtb(data):
    if data[:8] != VNDRBOOT:
        raise ValueError('not a vendor_boot.img')
    version, page = struct.unpack_from('<2I', data, 8)
    if version != 4:
        raise ValueError('vendor_boot header version %d unsupported (need 4)' % version)
    ramdisk_size = struct.unpack_from('<I', data, 24)[0]
    # v4 header: tags_addr@2076, name[16]@2080, header_size@2096, dtb_size@2100
    header_size, dtb_size = struct.unpack_from('<II', data, 2096)
    if not header_size or not dtb_size:
        raise ValueError('missing header_size / dtb_size in vendor_boot v4 header')
    def align(x):
        return (x + page - 1) // page * page
    off = align(header_size) + align(ramdisk_size)
    return off, dtb_size


def split_blob(seg):
    """Concatenated FDTs; each self-describes its totalsize."""
    out, p = [], 0
    while p + 8 <= len(seg) and struct.unpack_from('>I', seg, p)[0] == FDT_MAGIC:
        size = struct.unpack_from('>I', seg, p + 4)[0]
        if size < 8 or p + size > len(seg):
            raise ValueError('bad FDT totalsize %d at offset %d' % (size, p))
        out.append((p, seg[p:p + size]))
        p += size
    if p != len(seg):
        raise ValueError('dtb segment has %d trailing bytes after %d FDTs' % (len(seg) - p, len(out)))
    return out


def describe(blob):
    """Minimal FDT introspection without importing the repo parser (standalone)."""
    off_root = struct.unpack_from('>I', blob, 28)[0]
    # fall back to repo dt.py if available for a richer description
    try:
        repo = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        sys.path.insert(0, os.path.join(repo, 'tools'))
        import dt
        import tempfile
        with tempfile.NamedTemporaryFile(suffix='.dtb', delete=False) as f:
            f.write(blob); tmp = f.name
        try:
            r = dt.load(tmp)
            model = (r.str('model') or [''])[0]
            compat = list(r.str('compatible') or [])[:4]
            nodes = len(list(r.walk()))
        finally:
            os.unlink(tmp)
        return {'model': model, 'compatible': compat, 'nodes': nodes}
    except Exception:
        return {'model': '', 'compatible': [], 'nodes': None}


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--vendor-boot', required=True)
    ap.add_argument('--out-dir', required=True)
    ap.add_argument('--meta')
    a = ap.parse_args()
    data = open(a.vendor_boot, 'rb').read()
    off, size = vendor_boot_dtb(data)
    blobs = split_blob(data[off:off + size])
    os.makedirs(a.out_dir, exist_ok=True)
    meta = {'vendor_boot': a.vendor_boot, 'dtb_offset': off, 'dtb_size': size,
            'count': len(blobs), 'entries': []}
    for i, (rel, blob) in enumerate(blobs):
        path = os.path.join(a.out_dir, 'base-%02d.dtb' % i)
        with open(path, 'wb') as f:
            f.write(blob)
        info = describe(blob)
        meta['entries'].append({'index': i, 'offset': off + rel, 'size': len(blob),
                                'sha256': hashlib.sha256(blob).hexdigest(), **info})
        print('%s  %7d B  %s' % (path, len(blob), info['model'] or info['compatible']))
    if a.meta:
        os.makedirs(os.path.dirname(os.path.abspath(a.meta)), exist_ok=True)
        with open(a.meta, 'w', encoding='utf-8') as f:
            json.dump(meta, f, indent=2, ensure_ascii=False)
    print('vendor_boot dtb @%d, %d bytes, %d FDTs' % (off, size, len(blobs)))


if __name__ == '__main__':
    main()
