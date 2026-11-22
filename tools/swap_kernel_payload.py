#!/usr/bin/env python3
"""Swap only the XNU kernel inside an existing SWEETXNU payload.

The ADT (serial number, pinned extents, TrustCache range), boot cmdline and
trust-cache blob are copied byte-for-byte from the source payload; only the
kernel segments are rebuilt from the supplied Mach-O.  This is the safe way to
move a newly CI-built kernel into a payload that is already known to boot.

Usage:
    python3 tools/swap_kernel_payload.py OLD_PAYLOAD NEW_KERNEL OUT_PAYLOAD
"""
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import adt  # noqa: E402
import mkpayload  # noqa: E402

SEG_TABLE = mkpayload.SEG_TABLE
PAGE = 0x4000


def unpack_payload(path):
    p = open(path, 'rb').read()
    magic, version, nsegs = struct.unpack_from('<8sII', p, 0)
    assert magic == b'SWEETXNU' and version == 1, 'not a SWEETXNU v1 payload'
    virt_base, entry, adt_off, adt_size, kernel_end, phys_base, mem_size = struct.unpack_from(
        '<7Q', p, 0x10)
    cmdline = p[0x48:SEG_TABLE].split(b'\0', 1)[0].decode('ascii')
    segs = [struct.unpack_from('<4Q', p, SEG_TABLE + 32 * i) for i in range(nsegs)]
    pieces = [(va, size, p[off:off + n]) for va, size, off, n in segs]
    return dict(raw=p, nsegs=nsegs, virt_base=virt_base, entry=entry,
                adt=p[adt_off:adt_off + adt_size], kernel_end=kernel_end,
                phys_base=phys_base, mem_size=mem_size, cmdline=cmdline,
                pieces=pieces)


def main():
    if len(sys.argv) != 4:
        sys.exit(__doc__)
    old_path, kernel_path, out_path = sys.argv[1:4]
    old = unpack_payload(old_path)

    # The last segment is the appended TrustCache when it starts at kernel_end
    # and is much smaller than a kernel segment.
    kernel_pieces, tc_pieces = old['pieces'][:-1], old['pieces'][-1:]
    tc_va, tc_size, tc_data = tc_pieces[0]
    # addtrustcache.py appends TC at the then-current kernel_end and advances
    # kernel_end past it, so the header's kernel_end is the END of this segment.
    assert tc_va + tc_size == old['kernel_end'] and tc_size < 0x100000, 'unexpected last segment'
    print('old kernel segments:', len(kernel_pieces))
    print('old trustcache: %d B at %#x' % (len(tc_data), tc_va))
    print('cmdline (%d B): %s' % (len(old['cmdline']), old['cmdline']))

    # mkpayload.build applies the chained-fixup rebase itself.  The ADT already
    # has a TrustCache range; it is updated below after the new kernel_end is
    # known.
    blob, info = mkpayload.build(kernel_path, _tmp_adt(old['adt']), old['cmdline'])
    base = unpack_bytes(blob)
    print('new kernel: %s' % kernel_path)
    print('  virt_base %s -> %s' % (hex(old['virt_base']), hex(base['virt_base'])))
    print('  kernel_end %s -> %s' % (hex(old['kernel_end']), hex(base['kernel_end'])))
    print('  segments %d -> %d, payload %d B' % (old['nsegs'], base['nsegs'], len(blob)))

    # Re-append the TrustCache segment at the new kernel_end.
    new_tc_va = base['kernel_end']
    new_tc_size = (len(tc_data) + PAGE - 1) & ~(PAGE - 1)
    new_tc_pa = new_tc_va - base['virt_base'] + base['phys_base']

    root, _ = adt.parse(base['adt'])
    chosen = next(c for c in root.children if c.name == 'chosen')
    mmap = next(c for c in chosen.children if c.name == 'memory-map')
    prop = mmap.prop('TrustCache')
    assert prop is not None, 'source ADT has no TrustCache range'
    mmap.props = [(k, f, v) for k, f, v in mmap.props if k != 'TrustCache']
    mmap.props.append(('TrustCache', 0, struct.pack('<2Q', new_tc_pa, len(tc_data))))
    new_adt = adt.serialize(root)

    pieces = base['pieces'] + [(new_tc_va, new_tc_size, tc_data)]
    header = bytearray(SEG_TABLE + 32 * len(pieces))
    out = bytearray(header)
    table = []
    for va, size, data in pieces:
        off = len(out)
        out += data
        out += b'\0' * (-len(out) & 0xf)
        table.append((va, size, off, len(data)))
    adt_off = len(out)
    out += new_adt
    out += b'\0' * (-len(out) & 0xf)

    struct.pack_into('<8sII', out, 0, b'SWEETXNU', 1, len(pieces))
    struct.pack_into('<7Q', out, 0x10, base['virt_base'], base['entry'], adt_off,
                     len(new_adt), new_tc_va + new_tc_size, base['phys_base'],
                     base['mem_size'])
    # Keep the entire fixed-width cmdline field, including its trailing NULs.
    # Assigning the stripped string here would shrink the bytearray and shift
    # every subsequent offset (the 2026-11-22 first attempt lost 0xa4 bytes).
    out[0x48:SEG_TABLE] = old['raw'][0x48:SEG_TABLE]
    for i, t in enumerate(table):
        struct.pack_into('<4Q', out, SEG_TABLE + 32 * i, *t)

    os.makedirs(os.path.dirname(out_path) or '.', exist_ok=True)
    open(out_path, 'wb').write(out)
    import hashlib
    print('out: %s (%d B) sha256=%s' %
          (out_path, len(out), hashlib.sha256(out).hexdigest()[:16]))
    print('trustcache: %d B at phys %#x (va %#x)' % (len(tc_data), new_tc_pa, new_tc_va))


def _tmp_adt(blob):
    """mkpayload.build needs a path; write next to the output via a temp file."""
    import tempfile
    fd, path = tempfile.mkstemp(prefix='swap-adt-')
    os.write(fd, blob)
    os.close(fd)
    return path


def unpack_bytes(p):
    magic, version, nsegs = struct.unpack_from('<8sII', p, 0)
    assert magic == b'SWEETXNU' and version == 1
    virt_base, entry, adt_off, adt_size, kernel_end, phys_base, mem_size = struct.unpack_from(
        '<7Q', p, 0x10)
    segs = [struct.unpack_from('<4Q', p, SEG_TABLE + 32 * i) for i in range(nsegs)]
    pieces = [(va, size, p[off:off + n]) for va, size, off, n in segs]
    return dict(nsegs=nsegs, virt_base=virt_base, entry=entry, adt=p[adt_off:adt_off + adt_size],
                kernel_end=kernel_end, phys_base=phys_base, mem_size=mem_size, pieces=pieces)


if __name__ == '__main__':
    main()
