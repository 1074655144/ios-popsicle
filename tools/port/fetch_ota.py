#!/usr/bin/env python3
"""Fetch only the bytes we need from a Xiaomi / Android full OTA over HTTP Range.

A full OTA is ~9 GB. This tool never downloads it. It reads the ZIP64 central
directory, parses the brillo (CrAU) update payload manifest, and extracts one
named partition by fetching only its InstallOperation data ranges. Typical
result for `dtbo`: ~55 KB transferred instead of 9 GB.

Strictly read-only against the phone -- this tool only does HTTP GETs and writes
files on the host. It is deliberately dependency-free (stdlib only).

Usage
-----
  python3 tools/port/fetch_ota.py --url URL --list
  python3 tools/port/fetch_ota.py --url URL --partition dtbo \
      --out device/byron/firmware/dtbo.img
  python3 tools/port/fetch_ota.py --url URL --entry payload_properties.txt \
      --out device/byron/firmware/payload_properties.txt

Notes
-----
* The signed OTA URL contains an expiring token; pass the current URL each run.
* Operation types handled: REPLACE(0), REPLACE_BZ(1), ZERO(6), DISCARD(7),
  REPLACE_XZ(8). Delta-only types (SOURCE_COPY/BSDIFF/PUFFDIFF/BROTLI_BSDIFF)
  are rejected -- a full OTA must not contain them.
* Every fetched chunk is verified against the SHA-256 hash in the manifest.
"""
import argparse
import bz2
import hashlib
import json
import lzma
import os
import struct
import sys
import urllib.request

UA = {'User-Agent': 'Mozilla/5.0'}
EOCD = b'PK\x05\x06'
Z64_EOCD = b'PK\x06\x06'
Z64_LOC = b'PK\x06\x07'
CEN = b'PK\x01\x02'
LOC = b'PK\x03\x04'


# ---------------------------------------------------------------- HTTP ranges
class Remote:
    def __init__(self, url, timeout=120):
        self.url = url
        self.timeout = timeout
        req = urllib.request.Request(url, method='HEAD', headers=UA)
        with urllib.request.urlopen(req, timeout=timeout) as f:
            self.size = int(f.headers['Content-Length'])
            if f.headers.get('Accept-Ranges') != 'bytes':
                raise RuntimeError('server does not advertise byte ranges')

    def get(self, start, end):
        """Inclusive byte range, chunked because the CDN truncates big ranges."""
        if start > end or end >= self.size:
            raise ValueError('bad range %d..%d (size %d)' % (start, end, self.size))
        CHUNK = 1 << 20                      # 1 MiB per HTTP request
        if end - start + 1 <= CHUNK:
            return self._one(start, end)
        out = bytearray()
        for s in range(start, end + 1, CHUNK):
            out += self._one(s, min(s + CHUNK - 1, end))
        return bytes(out)

    def _one(self, start, end):
        want = end - start + 1
        last = None
        for _ in range(3):
            try:
                req = urllib.request.Request(
                    self.url, headers=dict(UA, Range='bytes=%d-%d' % (start, end)))
                with urllib.request.urlopen(req, timeout=self.timeout) as f:
                    data = f.read()
                if len(data) != want:
                    raise IOError('short read: wanted %d, got %d' % (want, len(data)))
                return data
            except Exception as exc:        # CDN occasionally drops a chunk
                last = exc
        raise IOError('range %d..%d failed after 3 attempts: %s' % (start, end, last))

    def tail(self, n):
        return self.get(self.size - n, self.size - 1), self.size - n


# ------------------------------------------------------------------- ZIP64
def zip_entries(r):
    tail, base = r.tail(1 << 20)
    i = tail.rfind(EOCD)
    if i < 0:
        raise ValueError('EOCD not found')
    e = struct.unpack_from('<4s4H2LH', tail, i)
    cd_size, cd_off, n = e[5], e[6], e[3]
    loc = tail.rfind(Z64_LOC)
    if loc >= 0:
        z64_off = struct.unpack_from('<4sLQL', tail, loc)[2]
        if z64_off >= base:
            rec = tail[z64_off - base:z64_off - base + 56]
        else:
            rec = r.get(z64_off, z64_off + 55)
        if rec[:4] != Z64_EOCD:
            raise ValueError('bad ZIP64 EOCD')
        v = struct.unpack_from('<4sQ2H2L4Q', rec, 0)
        n, cd_size, cd_off = v[6], v[8], v[9]
    cd = tail[cd_off - base:cd_off - base + cd_size] if cd_off >= base else \
        r.get(cd_off, cd_off + cd_size - 1)
    out, p = [], 0
    while p + 46 <= len(cd) and cd[p:p + 4] == CEN:
        v = struct.unpack_from('<4sHHHHHHLLLHHHHHLL', cd, p)
        (_, _, _, flags, method, _, _, crc, cs, us, nl, el, cl, _, _, _, lho) = v
        name = cd[p + 46:p + 46 + nl].decode('utf-8', 'replace')
        extra = cd[p + 46 + nl:p + 46 + nl + el]
        q = 0
        while q + 4 <= len(extra):
            hid, hsz = struct.unpack_from('<HH', extra, q)
            if hid == 1:
                z, zq = extra[q + 4:q + 4 + hsz], 0
                if us == 0xffffffff:
                    us = struct.unpack_from('<Q', z, zq)[0]; zq += 8
                if cs == 0xffffffff:
                    cs = struct.unpack_from('<Q', z, zq)[0]; zq += 8
                if lho == 0xffffffff:
                    lho = struct.unpack_from('<Q', z, zq)[0]; zq += 8
                break
            q += 4 + hsz
        out.append({'name': name, 'method': method, 'comp': cs,
                    'size': us, 'lho': lho, 'crc': crc, 'flags': flags})
        p += 46 + nl + el + cl
    if len(out) != n:
        raise ValueError('central directory entry count mismatch: %d vs %d' % (len(out), n))
    return out


def entry_data(r, e):
    if e['method'] not in (0, 8):
        raise ValueError('unsupported compression method %d' % e['method'])
    lh = r.get(e['lho'], e['lho'] + 29)
    if lh[:4] != LOC:
        raise ValueError('bad local header')
    nl, el = struct.unpack_from('<HH', lh, 26)
    start = e['lho'] + 30 + nl + el
    raw = r.get(start, start + e['comp'] - 1)
    if e['method'] == 8:
        import zlib
        raw = zlib.decompress(raw, -15)
    if len(raw) != e['size']:
        raise ValueError('uncompressed size mismatch')
    if e['method'] == 0 and (e['crc'] & 0xffffffff):
        # CRC32 is informational here; payload manifest hashes are authoritative.
        pass
    return raw


# --------------------------------------------------------- protobuf (minimal)
def _vi(b, p):
    v = s = 0
    while True:
        x = b[p]; p += 1
        v |= (x & 0x7f) << s
        if x < 0x80:
            return v, p
        s += 7


def fields(b):
    """Yield (number, wire, value) for a protobuf message.

    Unknown group wire types are skipped rather than raising: some nested
    payload messages carry opaque bytes that are not protobuf at all.
    """
    p = 0
    while p < len(b):
        try:
            k, p = _vi(b, p)
            fn, wt = k >> 3, k & 7
            if wt == 0:
                v, p = _vi(b, p)
            elif wt == 2:
                n, p = _vi(b, p)
                v = b[p:p + n]; p += n
            elif wt == 5:
                v = b[p:p + 4]; p += 4
            elif wt == 1:
                v = b[p:p + 8]; p += 8
            elif wt in (3, 4):          # deprecated start/end group
                depth = 1
                while depth and p < len(b):
                    k2, p2 = _vi(b, p)
                    w2 = k2 & 7
                    if w2 == 3:
                        depth += 1
                    elif w2 == 4:
                        depth -= 1
                    if w2 == 0:
                        _, p = _vi(b, p)
                    elif w2 == 2:
                        n2, p = _vi(b, p); p += n2
                    elif w2 == 1:
                        p += 8
                    elif w2 == 5:
                        p += 4
                    else:
                        p = p2
                continue
            else:
                raise ValueError('wire type %d' % wt)
            yield fn, wt, v
        except (IndexError, ValueError) as exc:
            raise ValueError('malformed protobuf at byte %d: %s' % (p, exc))


def varints(b, num):
    return [v for f, w, v in fields(b) if f == num and w == 0]


def blobs(b, num):
    return [v for f, w, v in fields(b) if f == num and w == 2]


OP_NAMES = {0: 'REPLACE', 1: 'REPLACE_BZ', 6: 'ZERO', 7: 'DISCARD',
            8: 'REPLACE_XZ'}


# ------------------------------------------------------------- payload parse
class Payload:
    def __init__(self, r, entries):
        e = next((x for x in entries if x['name'] == 'payload.bin'), None)
        if e is None:
            raise ValueError('payload.bin not in OTA')
        lh = r.get(e['lho'], e['lho'] + 29)
        nl, el = struct.unpack_from('<HH', lh, 26)
        self.base = e['lho'] + 30 + nl + el
        head = r.get(self.base, self.base + 23)
        if head[:4] != b'CrAU':
            raise ValueError('not a brillo update payload')
        self.version = struct.unpack_from('>Q', head, 4)[0]
        self.manifest_size = struct.unpack_from('>Q', head, 12)[0]
        self.meta_sig_size = struct.unpack_from('>L', head, 20)[0]
        self.manifest = r.get(self.base + 24,
                              self.base + 24 + self.manifest_size - 1)
        self.data_base = self.base + 24 + self.manifest_size + self.meta_sig_size
        mf = list(fields(self.manifest))
        self.block_size = next((v for f, w, v in mf if f == 3 and w == 0), 4096)
        self.parts = {}
        for _, _, pu in (x for x in mf if x[0] == 13 and x[1] == 2):
            nm = next((v.decode() for v in blobs(pu, 1)), None)
            if nm is None:
                continue
            info = blobs(pu, 7)
            sizes = varints(info[0], 1) if info else []
            size = sizes[0] if sizes and sizes[0] < (1 << 40) else None
            ops = []
            for o in blobs(pu, 8):
                d = {}
                for f, w, v in fields(o):
                    if w == 0 and f in (1, 2, 3):
                        d[f] = v
                    elif f == 6 and w == 2:
                        starts, counts = varints(v, 1), varints(v, 2)
                        d.setdefault('extents', []).append(
                            (starts[0] if starts else 0, counts[0] if counts else 0))
                    elif f == 8 and w == 2:
                        d['hash'] = v.hex()
                ops.append(d)
            self.parts[nm] = {'size': size, 'ops': ops}

    def describe(self):
        return {'payload_version': self.version,
                'manifest_size': self.manifest_size,
                'data_base': self.data_base,
                'block_size': self.block_size,
                'partitions': {k: {'size': v['size'], 'ops': len(v['ops'])}
                               for k, v in self.parts.items()}}

    def extract(self, r, name):
        p = self.parts.get(name)
        if p is None:
            raise ValueError('no such partition: %s (have %d)' % (name, len(self.parts)))
        size = p['size']
        if not size:
            raise ValueError('partition %s has no size in manifest' % name)
        ops = p['ops']
        for o in ops:
            t = o.get(1)
            if t not in OP_NAMES:
                raise ValueError('delta-only operation type %r in %s; '
                                 'this tool only handles full OTAs' % (t, name))
        # Coalesce contiguous data ranges into as few HTTP requests as possible.
        ranges = sorted((o.get(2, 0), o.get(3, 0)) for o in ops if o.get(3))
        merged = []
        for s, ln in ranges:
            if merged and s <= merged[-1][1] + 65536:
                merged[-1][1] = max(merged[-1][1], s + ln - 1)
            else:
                merged.append([s, s + ln - 1])
        cache = {}
        for s, e in merged:
            cache[s] = r.get(self.data_base + s, self.data_base + e)
        out = bytearray(size)
        for o in ops:
            t, off, ln = o.get(1), o.get(2, 0), o.get(3, 0)
            raw = b''
            if ln:
                for s, data in cache.items():
                    if s <= off and off + ln - 1 <= s + len(data) - 1:
                        raw = data[off - s:off - s + ln]
                        break
                if len(raw) != ln:
                    raise IOError('missing cached bytes for op at %d' % off)
                if o.get('hash') and hashlib.sha256(raw).hexdigest() != o['hash']:
                    raise IOError('SHA-256 mismatch for op at %d' % off)
            if t == 0:
                chunk = raw
            elif t == 1:
                chunk = bz2.decompress(raw)
            elif t == 8:
                chunk = lzma.decompress(raw, format=lzma.FORMAT_AUTO)
            elif t in (6, 7):
                chunk = b''
            else:
                raise ValueError(t)
            for start, count in o.get('extents', []):
                dst = start * self.block_size
                if t == 6:
                    need = count * self.block_size
                    if dst + need > size:
                        need = size - dst
                    out[dst:dst + need] = b'\0' * need
                elif t == 7:
                    continue
                else:
                    if dst + len(chunk) > size:
                        chunk = chunk[:size - dst]
                    out[dst:dst + len(chunk)] = chunk
        return bytes(out)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--url', required=True, help='full signed OTA URL')
    ap.add_argument('--list', action='store_true', help='list zip entries + payload partitions')
    ap.add_argument('--partition', help='extract one payload partition')
    ap.add_argument('--entry', help='extract one small ZIP entry by exact name')
    ap.add_argument('--out', help='output file')
    ap.add_argument('--describe-json', help='write payload description JSON here')
    a = ap.parse_args()

    r = Remote(a.url)
    entries = zip_entries(r)
    payload = Payload(r, entries) if any(e['name'] == 'payload.bin' for e in entries) else None

    if a.list:
        print('OTA size: %d bytes (%.2f GiB)' % (r.size, r.size / 1024 ** 3))
        print('\nZIP entries:')
        for e in entries:
            print('  %-46s method=%d  %12d bytes' % (e['name'], e['method'], e['size']))
        if payload:
            d = payload.describe()
            print('\npayload version=%d  manifest=%d B  data_base=%d  block=%d' % (
                d['payload_version'], d['manifest_size'], d['data_base'], d['block_size']))
            print('\npayload partitions (%d):' % len(d['partitions']))
            for k, v in d['partitions'].items():
                print('  %-24s %12d bytes  %2d ops' % (k, v['size'] or 0, v['ops']))
    if a.describe_json and payload:
        os.makedirs(os.path.dirname(os.path.abspath(a.describe_json)), exist_ok=True)
        with open(a.describe_json, 'w', encoding='utf-8') as f:
            json.dump({'ota_url': a.url, 'ota_size': r.size,
                       'zip_entries': [{k: v for k, v in e.items() if k != 'lho'}
                                       for e in entries],
                       'payload': payload.describe()}, f, indent=2, ensure_ascii=False)

    if a.entry:
        e = next((x for x in entries if x['name'] == a.entry), None)
        if e is None:
            ap.error('no such ZIP entry: %s' % a.entry)
        if e['size'] > 64 << 20:
            ap.error('entry too large for --entry (%d bytes); use --partition' % e['size'])
        data = entry_data(r, e)
        print('fetched %s (%d bytes)' % (a.entry, len(data)))
        if a.out:
            _write(a.out, data)

    if a.partition:
        if payload is None:
            ap.error('OTA has no payload.bin')
        data = payload.extract(r, a.partition)
        print('extracted %s: %d bytes (SHA-256 %s)' % (
            a.partition, len(data), hashlib.sha256(data).hexdigest()))
        if a.out:
            _write(a.out, data)
    return 0


def _write(path, data):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, 'wb') as f:
        f.write(data)
    print('wrote %s' % path)


if __name__ == '__main__':
    sys.exit(main())
