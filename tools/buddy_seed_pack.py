#!/usr/bin/env python3
"""Add first-boot completion seeds to an existing PANDORA firmware pack.

  tools/buddy_seed_pack.py BASE.img OUT.img [WORKDIR]

The root image in byron's RAM boot is built from cryptex DMGs, so it has none of
the /private/var state a restored iPhone has.  sweet-root-tweaks.py tries to
seed activation, but its find_container() finds no mobileactivationd container
in the cryptex root ("warning: no mobileactivationd system container; skipped
data ark"), so NO data_ark.plist is written at all.  That is the missing
buddy-done source: remindd's DataAccess reports PastBuddy=0 on every boot.

This tool keeps every file already in BASE.img and appends, via the kernel's
pandora_files installer (files.txt), the activation records that live on a
restored device.  Nothing is flashed: the new pack is written into the pinned
adspfw.img with pinfile rawwrite and booted with `fastboot boot` only.
"""
import os
import plistlib
import shutil
import struct
import sys
import tempfile

BUILD, VERSION = '20H392', '16.7.16'
MS_COMPLETION = 1767225600000  # synthetic, fixed: 2026-01-01 00:00 UTC in ms


def read_pack(path, work):
    f = open(path, 'rb')
    head = f.read(4096)
    assert head[:8] == b'PANDFW01', 'not a PANDFW01 firmware pack'
    n, = struct.unpack_from('<I', head, 8)
    assert 0 < n < 63, 'no room for new files'
    entries = []
    for i in range(n):
        raw, off, size = struct.unpack_from('<48sQQ', head, 16 + 64 * i)
        name = raw.rstrip(b'\0').decode()
        f.seek(off)
        data = f.read(size)
        p = os.path.join(work, name)
        with open(p, 'wb') as o:
            o.write(data)
        entries.append((name, p))
    f.close()
    return entries


def dump_plist(path, obj):
    with open(path, 'wb') as f:
        plistlib.dump(obj, f, fmt=plistlib.FMT_BINARY)


def main():
    if len(sys.argv) not in (3, 4):
        sys.exit(__doc__)
    base, out = sys.argv[1], sys.argv[2]
    work = sys.argv[3] if len(sys.argv) == 4 else tempfile.mkdtemp(prefix='buddyseed-')
    os.makedirs(work, exist_ok=True)
    entries = read_pack(base, work)

    # The canonical data_ark on a restored iPhone (root's Lockdown directory),
    # plus the same record in the container sweet-root-tweaks.py meant to write.
    ark = {
        '-ActivationState': 'Activated',
        '-BrickState': False,
        '-BuildVersion': BUILD,
        '-ProductVersion': VERSION,
        '-DataMigrationCompleted': True,
        '-PreSydroDataMigrationCompleted': True,
        'FirstPurpleBuddyCompletion': MS_COMPLETION,
        'com.apple.purplebuddy-SetupState': 'SetupUsingAssistant',
    }
    ark_root = os.path.join(work, 'data_ark_root.plist')
    ark_system = os.path.join(work, 'data_ark_system.plist')
    dump_plist(ark_root, ark)
    dump_plist(ark_system, ark)

    # The skip-setup preferences already in the image, plus the two keys a
    # restored device carries (SetupState / SetupLastExit).
    purple = {
        'SetupDone': True,
        'SetupFinishedAllSteps': True,
        'SetupVersion': 11,
        'daemonizeNeedsToRun': False,
        'SetupState': 'SetupUsingAssistant',
        'SetupLastExit': MS_COMPLETION,
    }
    pref = os.path.join(work, 'purplebuddy_seed.plist')
    dump_plist(pref, purple)

    lines = [
        '- 700 /private/var/root/Library/Lockdown',
        'data_ark_root.plist 600 /private/var/root/Library/Lockdown/data_ark.plist',
        '- 755 /private/var/containers/Data/System/com.apple.mobileactivationd',
        '- 755 /private/var/containers/Data/System/com.apple.mobileactivationd/Library',
        '- 755 /private/var/containers/Data/System/com.apple.mobileactivationd/Library/internal',
        'data_ark_system.plist 600 /private/var/containers/Data/System/com.apple.mobileactivationd/Library/internal/data_ark.plist',
        'purplebuddy_seed.plist 600 /private/var/mobile/Library/Preferences/com.apple.purplebuddy.plist',
    ]
    files_txt = os.path.join(work, 'files.txt')
    with open(files_txt, 'ab') as o:
        o.write(('\n'.join(lines) + '\n').encode())

    parts = [p for name, p in entries if name != 'files.txt'] + [
        ark_root, ark_system, pref, files_txt]
    # mkfwpack.py's exact layout, in-process so names stay < 48 bytes.
    out_entries, blobs, off = [], [], 4096
    for p in parts:
        data = open(p, 'rb').read()
        name = os.path.basename(p).encode()
        assert len(name) < 48, name
        out_entries.append(struct.pack('<48sQQ', name, off, len(data)))
        blob = data + b'\0' * (-len(data) % 4096)
        blobs.append(blob)
        off += len(blob)
    head = b'PANDFW01' + struct.pack('<II', len(parts), 0) + b''.join(out_entries)
    head += b'\0' * (4096 - len(head))
    with open(out, 'wb') as o:
        o.write(head)
        for b in blobs:
            o.write(b)
    print(f'{out}: {len(parts)} files, {off} bytes, buddy seed added')
    if len(sys.argv) == 3:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == '__main__':
    main()
