#!/usr/bin/env python3
"""Read-only: list/dump SpringBoard & backboardd .ips crash reports inside the
pinned iOS root image on the phone (via adb + pinfile rawreadat). Never boots,
never writes to the phone.

Usage (Windows/Git-Bash python):
  ADB_WIN='.../adb.exe' python3 tools/crash_fetch.py [--dump <name-substr>]

The iOS root is a case-sensitive HFS+ volume written verbatim into the pinned
/data/local/tmp/iosroot.img file's physical extents; Android FBE hides it from
normal reads, so every read goes through pinfile rawreadat below encryption.
"""
import sys, os, time
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.environ.setdefault('ADB', os.environ.get('ADB_WIN', 'adb'))
from ioslog_fetch import HFS, HFS_EPOCH, Remote

DUMP = None
if '--dump' in sys.argv:
    i = sys.argv.index('--dump')
    DUMP = sys.argv[i + 1] if i + 1 < len(sys.argv) else ''

CANDIDATES = [
    'private/var/mobile/Library/Logs/CrashReporter',
    'private/var/mobile/Library/Logs/CrashReporter/Submitted',
    'private/var/db/diagnostics',
]

def main():
    r = Remote()
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
                return None
            cur = v[1]
        return cur

    def files_under(fid, rel=''):
        for name, v in kids.get(fid, {}).items():
            if v[0] == 1:
                yield from files_under(v[1], rel + name + '/')
            else:
                yield rel + name, v

    found = {}
    for path in CANDIDATES:
        fid = lookup(path)
        if fid is None:
            print('[missing dir]', path)
            continue
        rows = list(files_under(fid))
        print('[dir]', path, 'files=', len(rows))
        for rel, v in rows:
            found[path + '/' + rel] = v

    print()
    print('=== all candidate files (name / size / mtime / compressed) ===')
    for path, v in sorted(found.items()):
        fork, flags = v[3]
        mt = time.strftime('%Y-%m-%d %H:%M', time.gmtime(v[2] - HFS_EPOCH))
        low = path.lower()
        mark = ' <<<' if any(k in low for k in ('springboard', 'backboardd', 'reportcrash', 'driverkit')) else ''
        print('  size={:9} mt={} comp={} {}{}'.format(fork[0], mt, bool(flags & 0x20), path, mark))

    if DUMP is not None:
        print()
        print('=== DUMP match={!r} ==='.format(DUMP))
        n = 0
        for path, v in sorted(found.items()):
            if DUMP and DUMP.lower() not in path.lower():
                continue
            fork, flags = v[3]
            if flags & 0x20:
                print('[skip compressed]', path)
                continue
            data = fs.read_fork(fork, v[1])
            print('----- {} ({} bytes) -----'.format(path, len(data)))
            sys.stdout.buffer.write(data[:200000])
            sys.stdout.buffer.write(b'\n')
            n += 1
            if n >= 6:
                break
        print('[dumped {}]'.format(n))

if __name__ == '__main__':
    main()
