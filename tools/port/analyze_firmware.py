#!/usr/bin/env python3
"""Offline board-port analyser: diff a candidate device's DTB/DTBO against the
popsicle (Xiaomi 17 Pro Max) baseline.

Why this exists
---------------
porting ios-popsicle to a new SM8850 board is mostly a *data* problem, not a
code problem. device/DT_FINDINGS.md documents exactly which registers upstream
read off the phone; tools/dt.py can already parse a live FDT. This script
automates the first pass: point it at the DTB/DTBO files unpacked from the
candidate's official OTA and it produces a field-by-field diff plus the list
of source files each differing field touches.

Pass **all** trees at once: on Qualcomm platforms the SoC constants live in
vendor_boot's base DTBs while board-specific values live in dtbo overlays, and
some values are zero placeholders patched by the bootloader at boot. Roots are
scored per field so a stub overlay can no longer mask a real base-DTB value.

It is strictly read-only: it never writes to a phone, never touches a partition,
and only ever reads the input files you give it.

Usage
-----
  python3 tools/port/analyze_firmware.py \
      --dtb device/byron/firmware/base_dtbs/*.dtb device/byron/firmware/dtbs/*.dtb \
      --device byron --out device/byron/firmware.json \
      --report docs/byron/FIRMWARE_DIFF.md

  # also inventory an unpacked /vendor/firmware_mnt for firmware file names
  ... --firmware-dir /path/to/fw

  # test / CI: feed a pre-extracted dict instead of real DTBs
  python3 tools/port/analyze_firmware.py --fixture fixture.json --device byron
"""
import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, 'tools'))
import dt  # noqa: E402  (repository's own FDT reader)

BASELINE = os.path.join(HERE, 'popsicle_baseline.json')

# DT carries a zero placeholder here; ABL/UEFI fills the real value at boot.
# These must never be baked into an ADT -- they are reported as pending_live.
RUNTIME_PATCHED = {'splash_size', 'memory_banks'}
PLACEHOLDERS = {'0x0', '0', '[]', '[0x0,0x0]', '[[0x0,0x0]]',
                '[0x0,0x0],[0x0,0x0]', '[[0x0,0x0],[0x0,0x0]]'}


# --------------------------------------------------------------------------
# extractors: each returns a value (str/int/list) or None when the tree does
# not carry the information. They intentionally never fall back to the
# baseline value -- a missing field must stay visible.
# --------------------------------------------------------------------------
def _first(root, **kw):
    return next(iter(root.find(**kw)), None)


def _reg0(node):
    if node is None:
        return None
    r = node.reg()
    return r[0][0] if r else None


def _hex(v):
    return None if v is None else hex(v) if isinstance(v, int) else str(v)


def _find_any(root, needles):
    """Nodes whose name or any compatible string contains one of the needles."""
    out = []
    for n in root.walk():
        hay = (n.name + ' ' + ' '.join(n.str('compatible') or [])).lower()
        if any(x in hay for x in needles):
            out.append(n)
    return out


def _gic(root):
    return _first(root, compatible='arm,gic-v3')


def ex_gicd(root):
    return _hex(_reg0(_gic(root)))


def ex_gicr(root):
    n = _gic(root)
    if n is None:
        return None
    regs = n.reg()
    # GICR is the large (>1 MiB) region; GICD is typically 64 KiB.
    for addr, size in regs[1:]:
        if size >= 0x100000:
            return hex(addr)
    return _hex(regs[1][0]) if len(regs) > 1 else None


def ex_gicr_stride(root):
    n = _gic(root)
    v = n.u32('redistributor-stride') if n is not None else None
    # Qualcomm writes <0 0x40000> (2 cells) or <0x40000> (1 cell).
    return _hex(v[-1]) if v else None


def ex_timer_freq(root):
    for n in root.walk():
        if 'arm,armv8-timer' in (n.str('compatible') or []):
            v = n.u32('clock-frequency')
            return str(v[0]) if v else None
    return None


def ex_vtimer_intid(root):
    """PPI 11 (EL1 virtual timer) -> INTID 16+11 = 27."""
    for n in root.walk():
        if 'arm,armv8-timer' not in (n.str('compatible') or []):
            continue
        it = n.u32('interrupts') or []
        for i in range(0, len(it) - 2, 3):
            if it[i] == 1 and it[i + 1] == 11:
                return str(16 + 11)
    return None


def ex_mpidrs(root):
    cpus = root.child('cpus')
    if cpus is None:
        return None
    ids = []
    for c in cpus.children:
        if not c.name.startswith('cpu@'):
            continue
        r = c.reg()
        if r:
            ids.append(r[0][0])
    return [hex(x) for x in ids] if ids else None


def ex_psci(root):
    for n in root.walk():
        if 'arm,psci-1.0' in (n.str('compatible') or []) or n.name == 'psci':
            m = n.str('method')
            if m:
                return m[0]
    return None


def ex_ufs(root):
    return _hex(_reg0(_first(root, compatible='qcom,ufshc') or
                      (_find_any(root, ['ufshc']) or [None])[0]))


def ex_ufs_smmu_sid(root):
    n = _first(root, compatible='qcom,ufshc')
    i = n.u32('iommus') if n is not None else None
    return _hex(i[1]) if i and len(i) >= 2 else None


def ex_spmi(root):
    ns = _find_any(root, ['spmi-pmic-arb'])
    return _hex(_reg0(ns[0])) if ns else None


def ex_mdp(root):
    ns = _find_any(root, ['mdss_mdp', 'mdss-mdp'])
    return _hex(_reg0(ns[0])) if ns else None


def ex_memory(root):
    n = root.child('memory')
    if n is None:
        return None
    return [[hex(a), hex(s)] for a, s in n.reg()]


def _splash(root):
    for n in root.walk():
        if 'splash' in n.name.lower() or 'cont_splash' in n.name.lower():
            r = n.reg()
            if r:
                return r[0]
    rm = root.child('reserved-memory')
    if rm:
        for n in rm.children:
            if any('splash' in (k.lower() + ' ' + str(v)) for k, v in n.props.items()):
                r = n.reg()
                if r:
                    return r[0]
    return None


def ex_splash_base(root):
    s = _splash(root)
    return hex(s[0]) if s else None


def ex_splash_size(root):
    s = _splash(root)
    return hex(s[1]) if s else None


def _default_panel(root):
    """Resolve qcom,dsi-display-primary -> qcom,dsi-default-panel phandle."""
    ph = getattr(root, 'phandles', {})
    for n in root.walk():
        if 'dsi-display-primary' not in n.name:
            continue
        v = n.u32('qcom,dsi-default-panel') or []
        if v and v[0] and v[0] in ph:
            return ph[v[0]]
    return None


def _panel_timing(root):
    p = _default_panel(root)
    if p is not None:
        t = p.child('qcom,mdss-dsi-display-timings')
        if t:
            for c in t.children:
                if c.u32('qcom,mdss-dsi-panel-width'):
                    return c
    # small/test trees put the timing properties directly on a panel node
    for n in root.walk():
        if n.u32('qcom,mdss-dsi-panel-width') and n.u32('qcom,mdss-dsi-panel-height'):
            return n
    return None


def ex_panel_phys_w(root):
    t = _panel_timing(root)
    v = t.u32('qcom,mdss-dsi-panel-width') if t is not None else None
    return str(v[0]) if v else None


def ex_panel_phys_h(root):
    t = _panel_timing(root)
    v = t.u32('qcom,mdss-dsi-panel-height') if t is not None else None
    return str(v[0]) if v else None


def ex_panel_mode(root):
    t = _panel_timing(root)
    if t is None:
        return None
    p = _default_panel(root)
    name = p.name if p is not None else ''
    if p is not None:
        name += ' ' + ' '.join(p.str('qcom,mdss-dsi-panel-name') or [])
    low = name.lower()
    bits = ['command-mode' if ('cmd' in low or '_cm' in low) else 'video-mode']
    if any(k.startswith('qcom,mdss-dsc-') for k in t.props):
        bits.append('DSC')
    bpp = p.u32('qcom,mdss-dsi-bpp') if p is not None else None
    if bpp:
        bits.append('%dbpp' % bpp[0])
    rates = set()
    if t.parent:
        for c in t.parent.children:
            m = re.search(r'(\d+)hz', c.name.lower())
            if m:
                rates.add(int(m.group(1)))
    if rates:
        bits.append('%d-%dHz' % (min(rates), max(rates)))
    return ' '.join(bits)


def ex_rear_display(root):
    """Only a configured secondary panel or a FocalTech touch counts as rear."""
    for n in root.walk():
        if 'dsi-display-secondary' in n.name:
            v = n.u32('qcom,dsi-default-panel') or []
            if v and v[0]:
                return 'present'
    if _find_any(root, ['focaltech', 'fts']):
        return 'present'
    return 'none'


def ex_touch_main(root):
    ns = _find_any(root, ['synaptics', 'tcm-spi'])
    if not ns:
        return None
    n = ns[0]
    comp = ','.join(n.str('compatible') or []) or n.name
    extras = []
    irq, rst = n.u32('synaptics,irq-gpio'), n.u32('synaptics,reset-gpio')
    if irq and len(irq) >= 2:
        extras.append('irq%d' % irq[1])
    if rst and len(rst) >= 2:
        extras.append('reset%d' % rst[1])
    reg = _hex(_reg0(n))
    return comp + (' @' + reg if reg else '') + \
        (' (' + ' '.join(extras) + ')' if extras else '')


def ex_touch_reset_gpio(root):
    for n in _find_any(root, ['synaptics', 'tcm-spi']):
        v = n.u32('synaptics,reset-gpio')
        if v and len(v) >= 2:
            return str(v[1])
    return None


def ex_touch_secondary(root):
    ns = _find_any(root, ['focaltech', 'fts'])
    if not ns:
        return None
    n = ns[0]
    return '%s @%s' % (','.join(n.str('compatible') or []) or n.name,
                       _hex(_reg0(n)) or '?')


def ex_tlmm_dt(root):
    """SoC TLMM pinctrl only; PMIC gpio nodes (pinctrl@b800) are NOT TLMM."""
    ns = _find_any(root, ['tlmm', 'pinctrl@'])
    for n in ns:
        if 'tlmm' in (n.name + ' ' + ' '.join(n.str('compatible') or [])).lower():
            return _hex(_reg0(n))
    for n in ns:
        r = n.reg()
        if r and r[0][1] >= 0x100000:
            return _hex(r[0][0])
    return None


def ex_vol_up(root):
    for n in root.walk():
        if 'gpio-keys' in n.name or n.name == 'gpio_keys':
            for c in n.children:
                code = c.u32('linux,code')
                if code and code[0] == 115:
                    g = c.u32('gpios') or c.u32('gpio')
                    # standard 3-cell form: <phandle, gpio, flags>
                    return str(g[1] if g and len(g) >= 3 else (g[-1] if g else c.name))
    return None


def ex_tdm_slots(root):
    for n in root.walk():
        for k in n.props:
            if 'tdm-max-slots' in k:
                v = n.u32(k)
                return str(v[0]) if v else None
    return None


def ex_wifi(root):
    chips = set()
    for n in root.walk():
        for c in (n.str('compatible') or []):
            if c.startswith('qcom,wcn') or c.startswith('wcn'):
                chips.add(c)
    return ', '.join(sorted(chips)) or None


EXTRACTORS = {k[3:]: v for k, v in list(globals().items()) if k.startswith('ex_')}


# --------------------------------------------------------------------------
def normalize(v):
    """Compare hex/decimal spellings and simple lists without false alarms."""
    if v is None:
        return None
    if isinstance(v, list):
        return '[' + ','.join(normalize(x) or '' for x in v) + ']'
    s = str(v).strip().lower()
    try:
        return hex(int(s, 0))
    except (ValueError, TypeError):
        return ' '.join(s.split())


def _score(v):
    """Pick the most informative value when several trees describe a field."""
    if v is None:
        return -1
    s = str(v).strip().lower()
    if s in ('', 'none', '0', '0x0', 'absent', '?', '[]'):
        return 0
    if '?' in s or 'unknown' in s:
        return 1
    if isinstance(v, list):
        return 3 + min(len(v), 10) / 100.0
    return 3


def analyse(roots, firmware_files=None, baseline=None):
    baseline = baseline or json.load(open(BASELINE, encoding='utf-8'))
    extracted = {}
    for key in sorted({p['extract'] for p in baseline['params'] if p.get('extract')}):
        fn = EXTRACTORS.get(key)
        if fn is None:
            extracted[key] = {'value': None, 'error': 'no extractor'}
            continue
        best, best_score, src, err = None, -1, None, None
        for i, root in enumerate(roots):
            try:
                v = fn(root)
            except Exception as e:                      # malformed/vendor DTBO
                err = '%s: %s' % (type(e).__name__, e)
                continue
            s = _score(v)
            if s > best_score:
                best, best_score, src = v, s, i
        extracted[key] = {'value': best, 'error': err, 'source_dtb_index': src,
                          'score': best_score}

    if firmware_files is not None:
        extracted['firmware_files'] = {'value': sorted(firmware_files),
                                       'source_dtb_index': None}

    diff = []
    counts = {'same': 0, 'different': 0, 'missing': 0, 'pending_live': 0,
              'pending_build': 0, 'pending_firmware': 0,
              'runtime_patched': 0, 'expected_absent': 0, 'na': 0}
    for p in baseline['params']:
        k = p['key']
        placeholder = None
        if p['source'] == 'firmware':
            got = extracted.get('firmware_files', {}).get('value')
            verdict = 'same' if got else 'pending_firmware'
        elif p.get('extract'):
            e = extracted.get(p['extract'], {})
            got = e.get('value')
            if got is None:
                verdict = 'expected_absent' if p.get('expected_absent') else 'missing'
            elif k in RUNTIME_PATCHED and normalize(got) in PLACEHOLDERS:
                verdict, placeholder, got = 'runtime_patched', got, None
            elif normalize(got) == normalize(p['value']):
                verdict = 'same'
            else:
                verdict = 'different'
        elif p['source'] == 'live':
            verdict, got = 'pending_live', None
        elif p['source'] == 'build':
            verdict, got = 'pending_build', None
        else:
            verdict, got = 'na', None
        counts[verdict] = counts.get(verdict, 0) + 1
        diff.append({
            'key': k, 'class': p['class'], 'source': p['source'],
            'popsicle': p['value'], 'byron': got, 'verdict': verdict,
            'dt_placeholder': placeholder,
            'required': p['required'], 'targets': p['targets'],
            'note': p['note'],
            'extractor_error': extracted.get(p.get('extract'), {}).get('error'),
            'source_dtb_index': extracted.get(p.get('extract'), {}).get('source_dtb_index'),
        })
    return {'extracted': extracted, 'diff': diff, 'summary': counts}


def report_md(result, device, sources):
    L = ['# %s 固件 diff（相对 popsicle）' % device, '',
         '> 由 `tools/port/analyze_firmware.py` 生成。**只读取固件文件，不接触手机、不写任何分区。**', '',
         '输入：' + ', '.join('`%s`' % s for s in (sources or ['<fixture>'])), '',
         '| 判定 | 数量 |', '|---|---|']
    for k, v in result['summary'].items():
        L.append('| %s | %d |' % (k, v))
    L += ['', '## 需要改动的字段（different / missing）', '',
          '| 字段 | popsicle | byron | 判定 | 关联代码 |', '|---|---|---|---|---|']
    rows = [d for d in result['diff'] if d['verdict'] in ('different', 'missing')]
    for d in rows:
        L.append('| `%s` | `%s` | `%s` | %s | %s |' % (
            d['key'], d['popsicle'], d['byron'] or '—', d['verdict'],
            ', '.join('`%s`' % t for t in d['targets'][:2])))
    if not rows:
        L.append('| — | — | — | 无 | — |')
    L += ['', '## 直接复用（same）', '']
    same = [d for d in result['diff'] if d['verdict'] == 'same']
    L += ['- `%s` = `%s`' % (d['key'], d['byron']) for d in same] or ['- 无']
    L += ['', '## 预期缺失（byron 本来就没有，无需改动）', '']
    ea = [d for d in result['diff'] if d['verdict'] == 'expected_absent']
    L += ['- `%s`：%s' % (d['key'], d['note']) for d in ea] or ['- 无']
    L += ['', '## 设备树里是占位符、由 bootloader 运行时填值（必须真机读取）', '']
    rp = [d for d in result['diff'] if d['verdict'] == 'runtime_patched']
    L += ['- `%s`：DT 里是 `%s`，ABL/UEFI 启动时才写真实值，不能写进 ADT'
          % (d['key'], d['dt_placeholder']) for d in rp] or ['- 无']
    L += ['', '## 固件里读不到、必须上真机采集', '']
    for d in result['diff']:
        if d['verdict'] in ('pending_live', 'pending_build', 'pending_firmware'):
            L.append('- `%s`（%s）：%s' % (d['key'], d['verdict'], d['note']))
    L += ['', '> `soc_shared` 且判定为 `same` 的字段才可直接沿用；'
          '`board_specific` 即使数值相同也必须核对来源（例如同为 1200x2608 并不代表 framebuffer 一致）。', '']
    return '\n'.join(L)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--dtb', nargs='*', default=[], help='DTB/DTBO files (as many as the ROM contains)')
    ap.add_argument('--firmware-dir', help='unpacked /vendor/firmware_mnt to inventory')
    ap.add_argument('--fixture', help='JSON with {"extracted": {...}} for offline tests')
    ap.add_argument('--device', default='byron')
    ap.add_argument('--baseline', default=BASELINE)
    ap.add_argument('--out', help='write result JSON here')
    ap.add_argument('--report', help='write a Markdown report here')
    a = ap.parse_args()

    roots, sources = [], list(a.dtb)
    for path in a.dtb:
        if not os.path.isfile(path):
            ap.error('not a file: %s' % path)
        try:
            roots.append(dt.load(path))
        except Exception as e:
            ap.error('%s: cannot parse FDT (%s)' % (path, e))
    if not roots and not a.fixture:
        ap.error('need at least one --dtb or --fixture')

    fw = None
    if a.firmware_dir:
        fw = []
        for base, _, files in os.walk(a.firmware_dir):
            for f in files:
                fw.append(os.path.relpath(os.path.join(base, f), a.firmware_dir))

    baseline = json.load(open(a.baseline, encoding='utf-8'))
    result = analyse(roots, fw, baseline)
    if a.fixture:
        fx = json.load(open(a.fixture, encoding='utf-8'))
        result = analyse([], fw, baseline)
        # fixture overrides extraction results wholesale (for deterministic tests)
        result['extracted'].update(fx.get('extracted', {}))
        for d in result['diff']:
            e = result['extracted'].get(
                next((p['extract'] for p in baseline['params']
                      if p['key'] == d['key'] and p.get('extract')), ''), {})
            if e.get('value') is not None:
                d['byron'] = e['value']
                d['verdict'] = ('same' if normalize(e['value']) == normalize(d['popsicle'])
                                else 'different')
        for k, v in list(result['summary'].items()):
            result['summary'][k] = sum(1 for d in result['diff'] if d['verdict'] == k)

    result['device'] = a.device
    result['sources'] = sources or ['<fixture>']
    result['baseline'] = os.path.relpath(a.baseline, REPO)

    if a.out:
        os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
        with open(a.out, 'w', encoding='utf-8') as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
    if a.report:
        os.makedirs(os.path.dirname(os.path.abspath(a.report)), exist_ok=True)
        with open(a.report, 'w', encoding='utf-8') as f:
            f.write(report_md(result, a.device, sources))

    print('%s: %d fields, %s' % (a.device, len(result['diff']), result['summary']))
    for d in result['diff']:
        if d['verdict'] in ('different', 'missing', 'runtime_patched'):
            print('  %-22s popsicle=%-28s byron=%s  [%s]' % (
                d['key'], str(d['popsicle'])[:27], d['byron'] or d['dt_placeholder'] or '—',
                d['verdict']))
    return 0


if __name__ == '__main__':
    sys.exit(main())
