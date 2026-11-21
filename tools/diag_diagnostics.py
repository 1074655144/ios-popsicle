#!/usr/bin/env python3
"""Local-only diagnostic: list the HFS diagnostics tree from a root image.

Uses the same HFS parser as ioslog_fetch.py. Two modes:
  - local (default): read a root image from the local disk (read-only).
  - --phone: read the phone's root image via adb/pinfile (read-only, no boot).

Prints each diagnostics file's path, size, flags, mtime, and whether the
fetch filter in ioslog_fetch.py would skip it (compressed / too old).
"""
import sys, os, time
from collections import defaultdict
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

PHONE = '--phone' in sys.argv
IMG = None
if not PHONE:
    IMG = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith('--') else os.path.join(
        os.path.dirname(HERE), 'incoming', 'iosroot.img')

if PHONE:
    os.environ.setdefault('ADB', os.environ.get('ADB_WIN', 'adb'))

from ioslog_fetch import HFS, HFS_EPOCH

MINUTES = 60


class LocalRemote:
    def __init__(self, path):
        self.f = open(path, 'rb')

    def read(self, off, length):
        self.f.seek(off)
        return self.f.read(length)


def main():
    if PHONE:
        from ioslog_fetch import Remote
        r = Remote()
        img_label = 'PHONE (adb/pinfile read-only)'
    else:
        r = LocalRemote(IMG)
        img_label = IMG
    fs = HFS(r)
    ents = fs.walk()
    kids = {}
    for (parent, name), v in ents.items():
        kids.setdefault(parent, {})[name] = v

    def lookup(path):
        cur = 2
        for part in path.strip('/').split('/'):
            v = kids.get(cur, {}).get(part)
            if v is None or v[0] != 1:
                raise SystemExit('no folder ' + path + ' (' + part + ')')
            cur = v[1]
        return cur

    def files_under(fid, rel=''):
        for name, v in kids.get(fid, {}).items():
            if v[0] == 1:
                yield from files_under(v[1], rel + name + '/')
            else:
                yield rel + name, v

    diag = lookup('private/var/db/diagnostics')
    rows = list(files_under(diag))
    mt_max = max(v[2] for _, v in rows)
    since = mt_max - 60 * MINUTES
    print('image:', img_label)
    print('diagnostics total files:', len(rows))
    print('mtime max:', mt_max, '->', time.strftime('%Y-%m-%d %H:%M', time.gmtime(mt_max - HFS_EPOCH)), 'UTC')
    print('fetch filter: since =', since, '->', time.strftime('%Y-%m-%d %H:%M', time.gmtime(since - HFS_EPOCH)), 'UTC',
          '(minutes={})'.format(MINUTES))

    print()
    print('=== by top-level dir: count / compressed(0x20) / size ===')
    agg = defaultdict(lambda: [0, 0, 0])
    for rel, v in rows:
        top = rel.split('/')[0]
        fork, flags = v[3]
        agg[top][0] += 1
        agg[top][1] += 1 if (flags & 0x20) else 0
        agg[top][2] += fork[0]
    for top, (n, c, sz) in sorted(agg.items(), key=lambda x: -x[1][0]):
        print('  {:20} n={:5} compressed={:5} size={:6} MiB'.format(top, n, c, sz >> 20))

    print()
    print('=== Persist/Special/Signpost/HighVolume files (size flags mtime verdict) ===')
    n = 0
    skipped_time = skipped_comp = would_get = 0
    for rel, v in rows:
        if '/' in rel and rel.split('/')[0] in ('Persist', 'Special', 'Signpost', 'HighVolume'):
            fork, flags = v[3]
            mt = time.strftime('%m-%d %H:%M', time.gmtime(v[2] - HFS_EPOCH))
            comp = bool(flags & 0x20)
            # Mirrors the FIXED ioslog_fetch.py: mtime < 1971 is "unset", always fetched.
            mtime_unset = v[2] < HFS_EPOCH + 60 * 60 * 24 * 365
            too_old = (v[2] < since) and not mtime_unset
            verdict = 'SKIP-compressed' if comp else ('SKIP-too-old' if too_old else 'FETCH')
            if comp:
                skipped_comp += 1
            elif too_old:
                skipped_time += 1
            else:
                would_get += 1
            print('  {:14} size={:9} mt={} flags=0x{:02x} {}'.format(
                verdict, fork[0], mt, flags, rel))
            n += 1
            if n >= 40:
                break
    print('  (shown {} of these dirs; FETCH={} SKIP-time={} SKIP-comp={})'.format(
        n, would_get, skipped_time, skipped_comp))

    print()
    print('=== top-level files (no slash) ===')
    for rel, v in rows:
        if '/' not in rel:
            fork, flags = v[3]
            mt = time.strftime('%m-%d %H:%M', time.gmtime(v[2] - HFS_EPOCH))
            print('  flags=0x{:02x} comp={} size={:9} mt={} {}'.format(
                flags, bool(flags & 0x20), fork[0], mt, rel))


if __name__ == '__main__':
    main()
