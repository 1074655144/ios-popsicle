#!/usr/bin/env python3
"""Read-only owner/gid/mode probe for selected paths in an iOS HFS+ root image.

  check_owner.py IMAGE [PATH ...]        (Windows Git Bash: pass a /opt/... WSL path)

Parses the HFS+ catalog directly and prints uid:gid + octal mode for folders and
files, straight from the on-disk BSD info (HFSPlusBSDInfo @ record+32:
ownerID +0, groupID +4, fileMode +10). No phone, no writes, no logs collected.

This is the computer-side self-check for the byron "first-boot prefs not loaded"
A/B: sweet-root-tweaks.py writes com.apple.purplebuddy.plist with SetupDone=True
into the image, but at runtime every boot still reports PastBuddy=0. If the
mobile home / Library/Preferences directories (or the plists) show a uid/gid/mode
that cfprefsd running as mobile(501) cannot read, that is the smoking gun; if they
are already 501:501 / 0755, this A/B premise is FALSE and must not be patched.
"""
import os
import struct
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from ioslog_fetch import HFS  # noqa: E402

WSL = '//wsl$/Ubuntu-24.04'

# The paths that decide whether mobile(501)'s cfprefsd can load the skip-first-boot prefs.
DEFAULT = [
    '/private/var',
    '/private/var/mobile',
    '/private/var/mobile/Library',
    '/private/var/mobile/Library/Preferences',
    '/private/var/mobile/Library/Preferences/com.apple.purplebuddy.plist',
    '/private/var/mobile/Library/Preferences/com.apple.migration.plist',
    '/private/var/mobile/Library/Preferences/com.apple.springboard.plist',
]

EXPECT = {
    # 0711 is the cryptex-native mode iOS uses for mobile's home (owner=r-x via x;
    # group/other traverse-only). It is correct, not something to "fix" to 0755.
    '/private/var/mobile': (501, 501, 0o711),
    '/private/var/mobile/Library': (501, 501, 0o711),
    '/private/var/mobile/Library/Preferences': (501, 501, 0o755),
    '/private/var/mobile/Library/Preferences/com.apple.purplebuddy.plist': (501, 501, 0o600),
    '/private/var/mobile/Library/Preferences/com.apple.migration.plist': (501, 501, 0o600),
    '/private/var/mobile/Library/Preferences/com.apple.springboard.plist': (501, 501, 0o600),
}


class Local:
    def __init__(self, path):
        p = WSL + path if path.startswith('/') else path
        self.f = open(p, 'rb')
        self.calls = self.bytes = 0

    def read(self, off, length):
        self.f.seek(off)
        self.calls += 1
        self.bytes += length
        return self.f.read(length)


def be(fmt, b, o):
    return struct.unpack_from('>' + fmt, b, o)


def walk_owner(fs):
    """path -> (kind, uid, gid, mode) for every folder(1)/file(2) in the catalog."""
    kids = {}
    meta = {}
    for node, offs, nrec in fs.nodes(fs.catalog):
        for i in range(nrec):
            o = offs[i]
            klen, parent, nlen = be('HIH', node, o)
            name = node[o + 8:o + 8 + 2 * nlen].decode('utf-16-be', 'replace')
            rec = o + 2 + klen
            rtype = be('h', node, rec)[0]
            if rtype not in (1, 2):
                continue
            fid = be('I', node, rec + 8)[0]
            uid, gid, mode = be('I', node, rec + 32)[0], be('I', node, rec + 36)[0], be('H', node, rec + 42)[0]
            kids.setdefault(parent, []).append((name, fid, rtype))
            meta[(parent, name)] = (rtype, uid, gid, mode)
    out = {}
    stack = [(2, '')]
    while stack:
        fid, pre = stack.pop()
        for name, child, rtype in kids.get(fid, []):
            p = pre + '/' + name
            out[p] = meta[(fid, name)]
            if rtype == 1:
                stack.append((child, p))
    return out


def cat_paths(fs, targets):
    """Dump file contents (plist pretty-printed; else repr) for exact paths, read-only."""
    import plistlib
    # build exact path -> (kind, fid, mtime, (fork, flags)) from the standard walk
    ents = fs.walk()
    kids = {}
    for (parent, name), v in ents.items():
        kids.setdefault(parent, []).append((name, v))
    by_path = {}
    stack = [(2, '')]
    while stack:
        fid, pre = stack.pop()
        for name, v in kids.get(fid, []):
            p = pre + '/' + name
            by_path[p] = v
            if v[0] == 1:
                stack.append((v[1], p))
    for p in targets:
        v = by_path.get(p)
        if not v or v[0] != 2:
            print(f'--- {p}: NOT A FILE / MISSING')
            continue
        data = fs.read_fork(v[3][0], v[1])
        print(f'--- {p} ({len(data)} B)')
        try:
            print(plistlib.dumps(plistlib.loads(data)).decode('utf-8', 'replace'))
        except Exception:
            print(repr(data[:512]))


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    args = sys.argv[1:]
    cat = '--cat' in args
    if cat:
        args.remove('--cat')
    targets = args[1:] or DEFAULT
    fs = HFS(Local(args[0]))
    if cat:
        cat_paths(fs, targets)
        return
    ents = walk_owner(fs)
    print('path                                                   kind   uid   gid    mode   verdict')
    print('-' * 96)
    bad = 0
    for p in targets:
        v = ents.get(p)
        if v is None:
            print(f'{p:<54} {"MISSING":>6}')
            bad += 1
            continue
        kind, uid, gid, mode = v
        verdict = ''
        if p in EXPECT:
            eu, eg, em = EXPECT[p]
            ok = (uid, gid, mode & 0o7777) == (eu, eg, em)
            verdict = 'OK' if ok else f'WANT {eu}:{eg} {em:04o}'
            bad += 0 if ok else 1
        print(f'{p:<54} {"dir" if kind == 1 else "file":>6} {uid:5} {gid:5}  {mode & 0o7777:04o}   {verdict}')
    print('-' * 96)
    print(f'{"PASS - A/B premise FALSE, do not patch mode" if bad == 0 else f"{bad} path(s) differ from expected"}')


if __name__ == '__main__':
    main()
