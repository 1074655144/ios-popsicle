#!/usr/bin/env python3
"""Add the ADE-style Restore-pane skip seed to a PANDFW01 firmware pack.

The cryptex-derived root image has no
  /private/var/containers/Shared/SystemGroup/
    systemgroup.com.apple.configurationprofiles/Library/ConfigurationProfiles/
so Setup Assistant never sees the CloudConfigurationDetails skip list and
falls through to the "Apps & Data" / Transfer-or-Restore pane.  The existing
buddy seed covers purplebuddy/data_ark only; it does not cover this pane.

This tool derives a NEW pack locally.  It keeps every file already in BASE.img,
appends the two cloud-configuration plists via the kernel's pandora_files
installer at about 2 s after root mount, and writes the new files.txt.  No
partition is flashed, no AVB is changed, and nothing is uploaded.  The
generated image stays outside the repository.

IMPORTANT (force re-apply): the iOS data partition is persistent, so the cloud
plists written on one boot remain on the device for the next boot.  The
pandora_files installer skips a file whose content already matches (pf_same),
so on the second boot the SkipSetup config is NOT re-applied and Setup Assistant
comes back.  To make the skip stable on every boot, files.txt now emits a
"! PATH" (unlink) line before each cloud plist, forcing a fresh write each time
and thus re-triggering the configuration daemon.  Verify in the serial log:
expect "removed ..." then "written" for both plists and NO "exec Setup".

Usage:
  tools/setup_restore_skip_pack.py BASE.img OUT.img [WORKDIR]

Typical BASE is the already-booting fwpack-buddy.img (it contains the earlier
data_ark / purplebuddy seed).  Write OUT over the pinned 40 MiB file on the
phone with `pinwrite rawwrite PATH DEV < OUT`, keeping its extents, then
`fastboot boot` as usual.  On the phone the firmware pack lives in
/data/local/tmp/adspfw2.img (40 MiB), NOT the old 8 MiB adspfw.img.  Device
pinfile is the minimal `pinwrite` build: no rawhash and no N/--yes argument.
"""
import os
import plistlib
import shutil
import struct
import sys

SKIP_SETUP = [
    'Restore',
    'RestoreCompleted',
    'Android',
    'DeviceToDeviceMigration',
]

CLOUD = {
    'ConfigurationWasApplied': True,
    'CloudConfigurationUIComplete': True,
    'PostSetupProfileWasInstalled': True,
    'AllowPairing': True,
    'AutoAdvanceSetup': False,
    'AwaitDeviceConfigured': False,
    'ConfigurationSource': 0,
    'ConfigurationURL': '',
    'IsMDMUnremovable': 0,
    'IsMandatory': False,
    'IsMultiUser': False,
    'IsSupervised': False,
    'OrganizationAddress': 'N/A',
    'OrganizationAddressLine1': 'N/A',
    'OrganizationAddressLine2': 'N/A',
    'OrganizationCity': 'N/A',
    'OrganizationCountry': 'N/A',
    'OrganizationDepartment': 'N/A',
    'OrganizationEmail': 'noreply@localhost.localdomain',
    'OrganizationMagic': '',
    'OrganizationName': 'Skip this step',
    'OrganizationPhone': 'N/A',
    'OrganizationSupportPhone': 'N/A',
    'OrganizationZipCode': 'N/A',
    'SkipSetup': SKIP_SETUP,
    'SupervisorHostCertificates': [],
}

BASE_PROFILE = ('/private/var/containers/Shared/SystemGroup/'
                'systemgroup.com.apple.configurationprofiles')
PROFILE_LIB = BASE_PROFILE + '/Library/ConfigurationProfiles'


def read_pack(path, work):
    f = open(path, 'rb')
    head = f.read(4096)
    assert head[:8] == b'PANDFW01', 'not a PANDFW01 firmware pack'
    n, = struct.unpack_from('<I', head, 8)
    assert 0 < n < 63, 'unexpected pack entry count'
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
    work = sys.argv[3] if len(sys.argv) == 4 else None
    tmp = None
    if work is None:
        import tempfile
        tmp = tempfile.mkdtemp(prefix='restore-skip-')
        work = tmp
    os.makedirs(work, exist_ok=True)

    entries = read_pack(base, work)
    old_files = os.path.join(work, 'files.txt')
    old_lines = []
    if os.path.isfile(old_files):
        old_lines = open(old_files, 'rb').read().decode().splitlines()

    cloud_details = os.path.join(work, 'cloudconfig_details.plist')
    cloud_shared = os.path.join(work, 'shareddevice_configuration.plist')
    dump_plist(cloud_details, CLOUD)
    dump_plist(cloud_shared, CLOUD)

    # Unlink first so pf_same() can never skip these: the iOS data partition is
    # persistent and a stale CloudConfigurationDetails would otherwise be seen
    # as "already the same", so the config daemon would never re-apply SkipSetup.
    new_lines = [
        '- 755 ' + BASE_PROFILE,
        '- 755 ' + BASE_PROFILE + '/Library',
        '- 755 ' + PROFILE_LIB,
        '! - ' + PROFILE_LIB + '/CloudConfigurationDetails.plist',
        '! - ' + PROFILE_LIB + '/SharedDeviceConfiguration.plist',
        'cloudconfig_details.plist 644 ' + PROFILE_LIB + '/CloudConfigurationDetails.plist',
        'shareddevice_configuration.plist 644 ' + PROFILE_LIB + '/SharedDeviceConfiguration.plist',
    ]
    files_txt = os.path.join(work, 'files.txt')
    with open(files_txt, 'wb') as o:
        o.write(('\n'.join(old_lines + new_lines) + '\n').encode())

    parts = [p for name, p in entries if name != 'files.txt'] + [
        cloud_details, cloud_shared, files_txt]
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

    print(out + ': %d files, %d bytes' % (len(parts), off))
    print('SkipSetup:', ', '.join(SKIP_SETUP))
    print('added:', ' '.join(new_lines))
    if tmp:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == '__main__':
    main()
