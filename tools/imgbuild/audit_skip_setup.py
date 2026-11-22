#!/usr/bin/env python3
"""Read-only audit: verify the ios-sweet / UniXNU skip-setup state inside a root image.

Checks the exact set of preferences, container directories, launchd job changes and
activation data that upstream's sweet-root-tweaks.py writes on images that reach the
home screen. Does not modify the image and does not upload anything.

Usage: python3 audit_skip_setup.py /opt/work/iosroot.img
"""
import os
import plistlib
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from ioslog_fetch import HFS  # noqa: E402


class Reader:
    """Plain local file reader; pass a path valid in the current environment."""
    def __init__(self, path):
        self.f = open(path, 'rb')
        self.calls = self.bytes = 0

    def read(self, off, length):
        self.f.seek(off)
        self.calls += 1
        self.bytes += length
        return self.f.read(length)


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    fs = HFS(Reader(sys.argv[1]))
    ents = fs.walk()
    kids = {}
    for (parent, name), v in ents.items():
        kids.setdefault(parent, []).append((name, v))
    out = {}
    stack = [(2, '')]
    while stack:
        fid, pre = stack.pop()
        for n, v in kids.get(fid, []):
            path = pre + '/' + n
            out[path] = v
            if v[0] == 1:
                stack.append((v[1], path))

    expected = {
        'com.apple.migration': {'LastSystemVersion', 'DMUserDataDisposition'},
        'com.apple.springboard': {'BKNoWatchdogs', 'FBLaunchWatchdogExceptions',
                                  'MCForceShowCloudConfigurationUI',
                                  'SBDisableAutoDim', 'SBDontDimOrLockOnAC',
                                  'SBDisableIdleSleep'},
        'com.apple.purplebuddy': {'SetupDone', 'SetupFinishedAllSteps',
                                  'SetupVersion', 'daemonizeNeedsToRun'},
        'com.apple.purplebuddy.notbackedup': {
            'ShouldRunDiagnosticsMiniBuddy', 'ShouldRunHSA2MiniBuddy',
            'ShouldRunKeychainSyncMiniBuddy', 'ShouldRunMesaMiniBuddy',
            'ShouldRunPaymentMiniBuddy', 'ShouldRunStandardMiniBuddy',
            'SilentICDPUpgrade'},
        'com.apple.managedconfiguration.notbackedup': {
            'LockdownActivationIndicatesCloudConfigurationAvailable'},
    }
    base = '/private/var/mobile/Library/Preferences/'
    bad = []
    for name, keys in expected.items():
        p = base + name + '.plist'
        if p not in out:
            print('MISSING', p)
            bad.append(name)
            continue
        v = out[p]
        try:
            d = plistlib.loads(fs.read_fork(v[3][0], v[1]))
        except Exception as e:
            print('PARSE_ERR', p, e)
            bad.append(name)
            continue
        print('===', name)
        for k in sorted(d):
            mark = '' if k in keys else '  (extra)'
            print('   ', k, '=', repr(d[k])[:160], mark)
        miss = sorted(keys - set(d))
        if miss:
            print('    MISSING KEYS:', miss)
            bad.append(name)

    print('=== containers')
    for sub in ('/private/var/containers/Bundle', '/private/var/containers/Data/System',
                '/private/var/containers/Shared/SystemGroup', '/private/var/containers/Temp'):
        ok = sub in out
        print('   ', ok and 'exists' or 'MISSING', sub)
        if not ok:
            bad.append(sub)

    print('=== activation containers')
    acts = [p for p in out if 'mobileactivationd' in p]
    if not acts:
        print('    MISSING any mobileactivationd container')
        bad.append('mobileactivationd')
    for p in sorted(acts):
        print('   ', p, out[p][0])

    print('=== launchd.plist')
    p = '/System/Library/xpc/launchd.plist'
    if p in out:
        v = out[p]
        d = plistlib.loads(fs.read_fork(v[3][0], v[1]))
        jobs = d['LaunchDaemons']
        print('    _PanicOnCrash =', sum(1 for j in jobs.values() if '_PanicOnCrash' in j))
        print('    _PanicOnCrasX =', sum(1 for j in jobs.values() if '_PanicOnCrasX' in j))
        print('    CommCenter    =', sum(1 for j in jobs.values()
                                        if j.get('Label') == 'com.apple.CommCenter'))
    else:
        print('    MISSING launchd.plist')
        bad.append('launchd.plist')

    print('=== RESULT:', 'OK' if not bad else 'PROBLEMS: ' + ', '.join(bad))
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
