#!/usr/bin/env python3
"""Extract board facts from a Xiaomi 9008 stock dump (per-partition .img files).

Input:  a directory produced by a 9008/QFIL full backup, e.g. E:/开发版/小米17 max/
        containing dtbo_a.img, boot_a.img, vendor_boot_a.img, persist.img, ...
Output: device/<board>/stock_dump.json  (host only; never commit device/*)

WHAT THIS SOLVES
----------------
A stock dump is the user's OWN unit at a known build, so it supplies facts that
an OTA payload alone cannot:
  * DTB-embedded chip part numbers (fuel gauge / charger PMIC / audio amp / WLAN)
  * persist/ calibration: panel ID, demura, speaker calibration, WLAN MAC
  * which software build is actually flashed (boot/vendor_boot hash match OTA)

WHAT IT CANNOT SOLVE (still needs a boot-time probe)
----------------------------------------------------
  * /memory bank + splash_size : DT has <0 0>, ABL fills them at runtime
  * framebuffer w/h/stride/format, TLMM real base, 16K pages, ABL load addr
Those live in registers/RAM at handoff, not in any on-disk partition.

SAFETY: read-only. Opens .img files for reading only; writes one JSON on the host.
"""
import argparse
import hashlib
import json
import os
import re
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.normpath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, os.path.join(REPO, 'tools'))
try:
    import dt as dtlib
except Exception:
    dtlib = None


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def pick(dump, *names):
    """First existing file matching a name (also tries _a/_b suffix)."""
    for n in names:
        p = os.path.join(dump, n)
        if os.path.isfile(p):
            return p
    for n in names:
        for suffix in ('_a.img', '_b.img'):
            cand = os.path.join(dump, n[:-4] + suffix) if n.endswith('.img') else os.path.join(dump, n + suffix)
            if os.path.isfile(cand):
                return cand
    return None


def strings(data, minlen=4):
    return [s.decode('ascii', 'ignore') for s in re.findall(rb'[ -~]{%d,}' % minlen, data)]


def scan_dtb(path, patterns):
    """Return {key: (node_name, compatible[])} for nodes matching any pattern."""
    found = {}
    if not dtlib or not path:
        return found
    try:
        root = dtlib.load(path)
    except Exception:
        return found
    for n in root.walk():
        blob = (n.name + ' ' + ' '.join(n.str('compatible') or [])).lower()
        for key, pats in patterns.items():
            if key in found:
                continue
            if any(p in blob for p in pats):
                found[key] = {'node': n.name,
                              'compatible': list(n.str('compatible') or [])[:4]}
    return found


def _wsl_path(win_path):
    """C:/x -> /mnt/c/x for the WSL spawned from Python."""
    p = win_path.replace('\\', '/')
    if re.match(r'^[A-Za-z]:/', p):
        return '/mnt/' + p[0].lower() + p[2:]
    return p


def read_ext4_file(img_path, inner_path, out_name):
    """Best-effort: extract a small file from an ext4 image using WSL debugfs.

    Copies the .img into WSL /tmp under a fixed ASCII name, then dumps the
    inner path. Returns raw bytes. Operates purely on the dumped .img on disk.
    """
    import subprocess
    import tempfile
    distro = os.environ.get('BYRON_WSL_DISTRO', 'Ubuntu-24.04')
    # Each wsl.exe call is a fresh session and /tmp is not durable across them,
    # so copy the image every time (48 MB; a few calls). Reliability > speed.
    script = (
        'cp "%s" /tmp/_stock_ext4.img 2>/dev/null || exit 0\n'
        'rm -f /tmp/_stock_out\n'
        'debugfs -R "dump %s /tmp/_stock_out" /tmp/_stock_ext4.img 2>/dev/null\n'
        'cat /tmp/_stock_out 2>/dev/null\n'
        % (_wsl_path(img_path), inner_path)
    )
    try:
        # Feed the script via stdin: avoids MSYS path conversion of argv.
        r = subprocess.run(['wsl.exe', '-d', distro, '--', 'bash', '-s'],
                           input=script.encode('utf-8'),
                           capture_output=True, timeout=90)
        return r.stdout
    except Exception:
        return b''


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dump', required=True, help='directory of 9008 partition .img files')
    ap.add_argument('--device', default='byron')
    ap.add_argument('--ota-dir', default=os.path.join(REPO, 'device', 'byron', 'firmware'),
                    help='dir holding OTA-extracted dtbo.img/boot.img/vendor_boot.img for hash cross-check')
    ap.add_argument('--out', default=None)
    a = ap.parse_args()

    dump = os.path.abspath(a.dump)
    out = a.out or os.path.join(REPO, 'device', a.device, 'stock_dump.json')
    os.makedirs(os.path.dirname(out), exist_ok=True)

    result = {'device': a.device, 'source_dir': dump, 'facts': {}, 'hashes': {}, 'notes': []}

    # --- build identity cross-check: boot / vendor_boot must match OTA --------
    for name in ('boot', 'vendor_boot', 'dtbo'):
        p = pick(dump, name + '.img')
        if p:
            h = sha256(p)
            result['hashes'][name] = {'path': os.path.basename(p), 'sha256': h}
            ota = os.path.join(a.ota_dir, name + '.img')
            if os.path.isfile(ota):
                oh = sha256(ota)
                same = (h == oh)
                # dtbo in a dump keeps 32MB partition padding; compare nonzero prefix
                if name == 'dtbo' and not same:
                    d1 = open(p, 'rb').read().rstrip(b'\0')
                    d2 = open(ota, 'rb').read().rstrip(b'\0')
                    same = hashlib.sha256(d1).hexdigest() == hashlib.sha256(d2).hexdigest()
                    result['notes'].append('dtbo compared on nonzero prefix (dump keeps partition padding)')
                result['hashes'][name]['ota_match'] = same

    # --- chip part numbers from the real DTBs --------------------------------
    patterns = {
        'fuel_gauge': ['ti,bq27', 'fuel-gauge', 'bq27z'],
        'charger_pmic': ['smb1501', 'battery-charger', 'qcom,smb'],
        'audio_amp': ['tfa98', 'tfa98xx'],
        'wlan_chip': ['wcn786', 'wcn788', 'qcom,wcn'],
        'touch_main': ['synaptics,tcm', 'goodix', 'novatek', 'ili2'],
        'fts_touch': ['focaltech', 'fts,fts'],
    }
    chips = {}
    # Prefer already-split DTBs (from OTA or a prior split_dtbo run): dt.load()
    # expects a single FDT, not a 32 MB padded dt_table image.
    dtb_dirs = [os.path.join(a.ota_dir, 'dtbs'),
                os.path.join(a.ota_dir, 'base_dtbs'),
                os.path.join(REPO, 'device', a.device, 'stock_dtbs')]
    for d in dtb_dirs:
        if not os.path.isdir(d):
            continue
        for f in sorted(os.listdir(d)):
            if f.endswith('.dtb'):
                chips.update(scan_dtb(os.path.join(d, f), patterns))
    result['facts']['chips'] = chips

    # --- persist/ calibration (ext4) -----------------------------------------
    persist = pick(dump, 'persist.img')
    calib = {}
    if persist:
        pi = read_ext4_file(persist, '/display/screenColorCal_panelInfo.txt', 'panelInfo')
        if pi and len(pi) < 128:
            calib['panel_info_hex'] = pi.decode('ascii', 'ignore').strip()
        ci = read_ext4_file(persist, '/display/cell_id_0.txt', 'cellId')
        if ci and len(ci) < 128:
            calib['cell_id'] = ci.decode('ascii', 'ignore').strip()
        dj = read_ext4_file(persist, '/display/demura_calib_file_journal_000021000000046e.xml', 'demura')
        if dj and b'PanelId' in dj:
            m = re.search(rb'PanelId="([0-9a-f]+)"', dj)
            if m:
                calib['demura_panel_id'] = m.group(1).decode()
        mac = read_ext4_file(persist, '/wlan/wlan_mac.bin', 'wlanMac')
        if mac and b'wlan0=' in mac:
            calib['wlan_mac'] = mac.decode('ascii', 'ignore').strip()
        amp = read_ext4_file(persist, '/audio/tfa_calr.txt', 'tfaCal')
        if amp and b'CH' in amp:
            calib['audio_amp_calibration'] = amp.decode('ascii', 'ignore').strip()
    result['facts']['calibration'] = calib

    with open(out, 'w', encoding='utf-8') as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    print('wrote', out)
    print('  hashes matched:', {k: v.get('ota_match') for k, v in result['hashes'].items()})
    print('  chips:', {k: v.get('compatible') for k, v in chips.items()})
    print('  calibration:', calib)


if __name__ == '__main__':
    main()
