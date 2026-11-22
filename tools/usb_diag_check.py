#!/usr/bin/env python3
"""Read-only check of the USB CDC ACM console log from usbserial_capture.ps1.

Usage: tools/usb_diag_check.py device/byron/live/usbdbg1-serial.txt

Prints the boot line, every `PANDORA USB:` status line, the first SpringBoard
exec, and the last timestamp seen. Never uploads or modifies the capture.
"""
import re
import sys

p = sys.argv[1]
raw = open(p, 'rb').read().replace(b'\0', b'').decode('utf-8', 'replace')
lines = raw.splitlines()
print('lines', len(lines), 'bytes', len(raw))

header = [x for x in lines if 'QCOM XNU USB CDC ACM' in x or 'Darwin Kernel Version' in x]
for x in header[:2]:
    print('header:', x)

usb = [x for x in lines if 'PANDORA USB' in x]
print('PANDORA USB lines:', len(usb))
for x in usb:
    print(' ', x.strip())

sb = [x for x in lines if 'exec SpringBoard' in x]
print('exec SpringBoard:', len(sb))
for x in sb[:3]:
    print(' ', x.strip())

seed_keys = ('purplebuddy_seed.plist', 'data_ark_root.plist',
             'data_ark_system.plist', 'cloudconfig_details.plist',
             'shareddevice_configuration.plist')
seeds = [x for x in lines if 'PANDORA FILES:' in x and
         any(k in x for k in seed_keys)]
setup = [x for x in lines if any(k in x for k in (
    'exec Setup', 'exec backupd', 'exec com.apple.datamigrator',
    'FinishRestoreFromBackup', 'restore-datapartition'))]
print('SETUP seed installs:', len(seeds))
for x in seeds:
    print(' ', x.strip())
print('SETUP/restore events:', len(setup))
for x in setup[:12]:
    print(' ', x.strip())

scan = [x for x in lines if 'SWEET FB: scanout' in x]
print('FB scanout:', len(scan))
for x in scan[-2:]:
    print(' ', x.strip())

ts = re.compile(r'^\[\s*([0-9]+\.[0-9]+)\]')
last = None
for x in lines:
    m = ts.match(x)
    if m:
        last = float(m.group(1))
print('last kernel timestamp:', last)

ok = any('serial started' in x and 'error 0' in x and 'core 0' in x for x in usb)
print('VERDICT:', 'USB CDC ACM OK' if ok else 'NOT OK (no clean serial started line)')
