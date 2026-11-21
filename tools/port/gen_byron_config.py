#!/usr/bin/env python3
"""Merge the three data sources of a board port and generate the byron config.

  firmware diff  (analyze_firmware.py -> device/byron/firmware.json)
  live capture   (collect_board.sh   -> device/byron/live/)
  manual probes  (device/byron/manual.json, filled in by a human on the phone)

Then decide, honestly, whether the board is ready:

  BOARD_DATA_COMPLETE=no          -> safe_boot.sh refuses every --commit
  BOARD_DATA_COMPLETE=data_ready  -> all *data* is present, but nobody has
                                     verified it on hardware; still refuses
  BOARD_DATA_COMPLETE=yes         -> only with --attest, i.e. an explicit human
                                     statement that a real byron boot was tested

Passing --attest never writes data by itself; it is a declaration. The script
never talks to a phone and never writes a partition.

Usage
-----
  python3 tools/port/gen_byron_config.py --firmware device/byron/firmware.json \
      --live device/byron/live --check
  python3 tools/port/gen_byron_config.py ... --write
  python3 tools/port/gen_byron_config.py ... --write --attest   # after real boot
"""
import argparse
import datetime
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, 'tools'))
sys.path.insert(0, HERE)
try:
    from gptextract import read_gpt
except Exception:
    read_gpt = None
from board_overlay import coerce as adt_coerce
try:
    import dt
except Exception:
    dt = None

BASELINE = os.path.join(HERE, 'popsicle_baseline.json')

# Only these mkadt_pandora.py globals may be overridden by board data.
ADT_KEYS = {
    'phys_base': 'PHYS_BASE', 'mem_size': 'MEM_SIZE',
    'gicd_base': 'GICD', 'gicr_base': 'GICR',
    'fb': 'FB', 'splash_base': 'FB', 'splash_size': 'FB_SIZE',
    'fb_w': 'FB_W', 'fb_h': 'FB_H', 'fb_stride': 'FB_STRIDE',
    'ufs_base': 'UFS', 'timer_freq': 'TIMEBASE',
    'vtimer_intid': 'VTIMER_INTID', 'mpidrs': 'MPIDRS',
    'dsp_shm': 'DSP_SHM', 'high_phys_base': 'HIGH_PHYS_BASE',
    'high_mem_size': 'HIGH_MEM_SIZE',
}


def read(path, default=''):
    try:
        return open(path, encoding='utf-8', errors='replace').read()
    except OSError:
        return default


def prop(text, name):
    m = re.search(r'^\[%s\]:\s*\[(.*?)\]' % re.escape(name), text, re.M)
    return m.group(1).strip() if m else None


def parse_live(live):
    """Best-effort extraction of the fields that ARE available read-only."""
    out = {}
    if not live:
        return out
    props = read(os.path.join(live, 'props.txt'))
    if props:
        out['identity_device'] = prop(props, 'ro.product.device')
        out['identity_model'] = prop(props, 'ro.product.model')
        out['crypto_state'] = prop(props, 'ro.crypto.state')
    ps = read(os.path.join(live, 'power_supply.txt'))
    m = re.search(r'POWER_SUPPLY_NAME=battery', ps)
    if m:
        cap = re.search(r'POWER_SUPPLY_CHARGE_FULL_DESIGN=(\d+)', ps)
        out['battery_gauge'] = ('%s mAh (design)' % int(int(cap.group(1)) / 1000)
                                if cap else 'present (capacity not exposed)')
        ics = sorted(set(re.findall(r'POWER_SUPPLY_NAME=([\w-]+)', ps)))
        out['charger_ic'] = ', '.join(x for x in ics if x != 'battery') or 'unknown'
    # The live FDT is the only honest source for bootloader-patched memory and
    # splash values; the firmware DTB still has <0 0> placeholders there.
    fdt_path = os.path.join(live, 'fdt.dtb')
    if dt and os.path.isfile(fdt_path):
        try:
            root = dt.load(fdt_path)
            mem = root.child('memory')
            if mem:
                banks = [(a, s) for a, s in mem.reg() if s > 0]
                if banks:
                    out['memory_banks'] = '[' + ','.join(
                        '[%s,%s]' % (hex(a), hex(s)) for a, s in banks) + ']'
            for n in root.walk():
                if 'splash' in n.name.lower() or 'cont_splash' in n.name.lower():
                    r = n.reg()
                    if r:
                        out['splash_base'] = hex(r[0][0])
                        out['splash_size'] = hex(r[0][1])
                        break
        except Exception:
            pass
    byname = read(os.path.join(live, 'by_name.txt'))
    m = re.search(r'userdata\s*->\s*(/dev/block/\S+)', byname)
    if m:
        out['userdata_dev'] = m.group(1)
    dm = read(os.path.join(live, 'dm_table.txt'))
    m = re.search(r'(\d+)-(\d+):\s*default-key', dm)
    if m:
        out['userdata_lba'] = '%s..%s' % (m.group(1), m.group(2))
    gpt = os.path.join(live, 'gpt.bin')
    if os.path.isfile(gpt) and os.path.getsize(gpt) > 4096 and read_gpt:
        try:
            parts = read_gpt(gpt)
            u = next((p for p in parts if p[0] == 'userdata'), None)
            if u:
                # read_gpt returns block numbers in the GPT's own block size.
                # rawwrite wants 512-byte-sector LBAs.
                factor = 8 if u[3] == 4096 else 1
                out['userdata_lba_gpt'] = '%d..%d' % (u[1], u[2])
                out['userdata_lba'] = '%d..%d' % (
                    u[1] * factor, u[2] * factor + factor - 1)
                out['userdata_dev'] = out.get('userdata_dev') or 'by GPT label'
        except Exception:
            pass
    # sysfs is authoritative: it reports the 512-byte-sector start directly.
    sec = read(os.path.join(live, 'userdata_sector.txt'))
    st = re.search(r'^start=(\d+)', sec, re.M)
    sz = re.search(r'^size=(\d+)', sec, re.M)
    if st and sz:
        first, count = int(st.group(1)), int(sz.group(1))
        out['userdata_lba'] = '%d..%d' % (first, first + count - 1)
    dms = read(os.path.join(live, 'dm_sysfs.txt'))
    for line in dms.splitlines():
        if 'name=userdata' in line:
            out['userdata_dm'] = line.strip()
            break
    thermal = read(os.path.join(live, 'thermal.txt'))
    if len(thermal.strip()) > 40:
        out['thermal_table'] = 'captured (%d bytes, needs manual review)' % len(thermal)
    fw = read(os.path.join(live, 'firmware_list.txt'))
    if fw.strip():
        names = [x for x in fw.splitlines() if x.strip()]
        out['firmware_files'] = '%d files: %s' % (
            len(names), ', '.join(sorted({os.path.basename(x) for x in names})[:6]))
    inputs = read(os.path.join(live, 'input_devices.txt'))
    for chip in ('synaptics', 'focaltech', 'goodix'):
        if chip in inputs.lower():
            out.setdefault('touch_vendor_hint', chip)
    irqs = (read(os.path.join(live, 'interrupts_1.txt')) + '\n' +
            read(os.path.join(live, 'interrupts_2.txt')))
    m = re.search(
        r'^\s*(\d+):.*?msmgpio\s+(\d+)\s+\w+\s+[^\n]*(?:synaptics|tcm)[^\n]*',
        irqs, re.I | re.M)
    if m:
        out['touch_irq_gpio'] = m.group(2)
    return out


def parse_stock_dump(path):
    """Map a stock-dump.json (from extract_stock_dump.py) to baseline keys.

    These facts come from the user's OWN unit's read-only partitions and DTBs,
    so they legitimately resolve board_specific chip-part fields without a
    live boot. Runtime-only values (memory/fb/TLMM) are never in here.
    """
    out = {}
    if not path or not os.path.isfile(path):
        return out
    d = json.load(open(path, encoding='utf-8'))
    facts = d.get('facts', {})
    chips = facts.get('chips', {})
    calib = facts.get('calibration', {})

    def compat(key):
        c = chips.get(key, {})
        return (c.get('compatible') or [None])[0] or c.get('node')

    fg = compat('fuel_gauge')
    if fg:
        out['battery_gauge'] = 'fuel gauge %s' % fg
    cp = compat('charger_pmic')
    if cp:
        out['charger_ic'] = cp
    wc = compat('wlan_chip')
    if wc:
        out['wifi_chip'] = wc
    amp = compat('audio_amp')
    if amp:
        out['audio_amp'] = amp
    tm = compat('touch_main')
    if tm:
        out['touch_vendor_hint'] = tm
    if calib.get('demura_panel_id'):
        out['panel_id'] = calib['demura_panel_id']
    if calib.get('cell_id'):
        out['panel_cell_id'] = calib['cell_id']
    if calib.get('wlan_mac'):
        out['wlan_mac'] = calib['wlan_mac']
    if calib.get('audio_amp_calibration'):
        out['audio_amp_calibration'] = calib['audio_amp_calibration']
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--firmware', help='firmware.json from analyze_firmware.py')
    ap.add_argument('--live', help='live/ dir from collect_board.sh')
    ap.add_argument('--stock-dump', help='stock_dump.json from extract_stock_dump.py (9008 backup)')
    ap.add_argument('--manual', help='manual.json with human-measured probe values')
    ap.add_argument('--baseline', default=BASELINE)
    ap.add_argument('--device', default='byron')
    ap.add_argument('--check', action='store_true', help='report only (default)')
    ap.add_argument('--write', action='store_true', help='write profile + overrides + checklist')
    ap.add_argument('--attest', action='store_true',
                    help='declare a REAL device boot was verified; only then may COMPLETE=yes')
    ap.add_argument('--strict', action='store_true', help='exit 2 if required data is missing')
    ap.add_argument('--write-root', default=REPO,
                    help='redirect ALL generated files under this root (tests use a temp dir)')
    a = ap.parse_args()
    WR = os.path.abspath(a.write_root)
    PROFILE = os.path.join(WR, 'profiles', '%s.env' % a.device)

    baseline = json.load(open(a.baseline, encoding='utf-8'))
    firmware = json.load(open(a.firmware, encoding='utf-8')) if a.firmware else {'diff': []}
    fdiff = {d['key']: d for d in firmware.get('diff', [])}
    fwex = firmware.get('extracted', {}).get('firmware_files', {}).get('value')
    live = parse_live(a.live) if a.live else {}
    stock = parse_stock_dump(a.stock_dump)
    manual = json.load(open(a.manual, encoding='utf-8')) if a.manual else {}

    resolved, missing = {}, []
    for p in baseline['params']:
        k = p['key']
        val = None
        if k in manual and str(manual[k]).strip():
            val = manual[k]
        elif k in stock:
            val = stock[k]
        elif p.get('extract') and fdiff.get(k, {}).get('byron') not in (None, ''):
            val = fdiff[k]['byron']
        elif p['source'] == 'firmware' and fwex:
            val = '%d firmware files' % len(fwex)
        elif k in live:
            val = live[k]
        elif p['source'] == 'build':
            # build artefacts are checked on disk, never fabricated
            cands = {
                'pinned_extents': ['device/%s/extents/iosroot.json' % a.device,
                                   'device/%s/extents/ioslog.json' % a.device,
                                   'device/%s/extents/adspfw.json' % a.device],
                'stock_boot_b_sha256': ['backup/manifest.txt'],
            }.get(k, [])
            if cands and all(os.path.isfile(os.path.join(WR, c)) for c in cands):
                val = 'present on disk'
        if isinstance(val, str) and val.lower() in ('unknown', 'n/a', '?', 'todo'):
            val = None
        if val is None:
            missing.append(p)
        else:
            resolved[k] = {'value': val, 'source': ('manual' if k in manual else
                           'stock_dump' if k in stock else
                           'firmware' if p.get('extract') or p['source'] == 'firmware' else
                           'live'), 'param': p}

    req_missing = [p for p in missing if p['required']]
    ready = not req_missing
    state = 'yes' if (ready and a.attest) else ('data_ready' if ready else 'no')

    print('== %s: %d/%d required fields resolved' % (
        a.device, sum(1 for p in baseline['params'] if p['required'] and p['key'] in resolved),
        sum(1 for p in baseline['params'] if p['required'])))
    print('   BOARD_DATA_COMPLETE=%s%s' % (
        state, '  (--attest: real boot declared)' if a.attest and state == 'yes' else ''))
    if req_missing:
        print('   missing (%d):' % len(req_missing))
        for p in req_missing:
            print('     - %-22s [%s/%s] %s' % (p['key'], p['source'], p['class'],
                                               p['targets'][0] if p['targets'] else ''))
    if a.device == 'byron' and live.get('identity_device') not in (None, a.device):
        print('   WARNING: live capture is from %r, not %r' % (live['identity_device'], a.device))

    if a.strict and req_missing:
        return 2
    if not a.write:
        print('   (report only; --write to generate files)')
        return 0

    # ---- profiles/byron.env ------------------------------------------------
    os.makedirs(os.path.dirname(PROFILE), exist_ok=True)
    env = ['# Xiaomi 17 Max (byron) — 由 tools/port/gen_byron_config.py 生成',
           '# 生成时间: %s' % datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
           '# 数据源: firmware diff + 真机只读采集 + 人工探测。',
           '# BOARD_DATA_COMPLETE=yes 仅在 --attest（真机启动已验证）时写入。', '',
           'PROFILE_NAME="Xiaomi 17 Max"', 'CODENAME=byron',
           'PRODUCT_MODEL=2605EPN8EC', 'SOC=SM8850-AC', 'SOC_PLATFORM=kaanapali',
           'PANEL="2608x1200 LTPO AMOLED 120Hz"', 'REAR_DISPLAY=none',
           'BATTERY="8000mAh 金沙江 / P3+G2"', 'ADRENO=840',
           'BOARD_DATA_COMPLETE=%s' % state, '',
           'KERNEL_CONFIG=PANDORA', 'XNU_PATCH_SERIES=xnu/patches',
           'SHIM=shim/loader', 'LAUNCHER=mac/boot_ios.sh',
           'EXTENTS_DIR=device/byron/extents',
           'STOCK_BOOT_B=device/byron/stock/boot_b.img', '',
           '# ---- AUTO-GENERATED BOARD DATA (BOARD_* 前缀, safe_boot 不读取) ----']
    for k in sorted(resolved):
        v = resolved[k]['value']
        if isinstance(v, list):
            v = ','.join(str(x) for x in v)
        v = str(v).replace('\\', '\\\\').replace('"', '\\"').replace('\n', ' ')
        env.append('BOARD_%s="%s"' % (k.upper(), v))
    env += ['', '# 未解析: ' + (', '.join(p['key'] for p in missing) or '无'),
            '# 完整逐项清单: docs/byron/PORT_CHECKLIST.md', '']
    open(PROFILE, 'w', encoding='utf-8').write('\n'.join(env))

    # ---- ADT overrides -----------------------------------------------------
    odir = os.path.join(WR, 'device', a.device)
    os.makedirs(odir, exist_ok=True)
    overrides = {}
    for k, adtkey in ADT_KEYS.items():
        if k in resolved and k != 'splash_base':     # splash_base handled below
            overrides[adtkey] = resolved[k]['value']
    if 'splash_base' in resolved:
        overrides['FB'] = resolved['splash_base']['value']
    # Never emit a placeholder string as a usable ADT constant: a value that
    # cannot be coerced is dropped and reported, not silently passed through.
    clean, skipped = {}, []
    for k, v in overrides.items():
        try:
            clean[k] = adt_coerce(k, v)
        except ValueError:
            skipped.append(k)
    with open(os.path.join(odir, 'adt_overrides.json'), 'w', encoding='utf-8') as f:
        json.dump({'_comment': 'feed to mkadt_pandora.py --board-json; only whitelisted keys apply',
                   'skipped_non_numeric': skipped, 'overrides': clean},
                  f, indent=2, ensure_ascii=False)
    if skipped:
        print('   note: %d ADT override(s) dropped (non-numeric placeholder): %s'
              % (len(skipped), ', '.join(skipped)))

    # ---- checklist ---------------------------------------------------------
    cdir = os.path.join(WR, 'docs', a.device)
    os.makedirs(cdir, exist_ok=True)
    L = ['# %s 移植逐项清单' % a.device, '',
         '> 由 `tools/port/gen_byron_config.py` 自动生成。`BOARD_DATA_COMPLETE=%s`。' % state,
         '> `same` 只表示数值一致，不等于验证通过；`soc_shared` 且 `same` 才可直接复用。', '',
         '| 字段 | byron 值 | 来源 | 复用类 | 需改动的代码 | 状态 | 备注 |',
         '|---|---|---|---|---|---|---|']
    for p in baseline['params']:
        k = p['key']
        r = resolved.get(k)
        L.append('| `%s` | `%s` | %s | %s | %s | %s | %s |' % (
            k, (str(r['value'])[:48] if r else '—'), (r['source'] if r else '—'),
            p['class'], '`%s`' % (p['targets'][0] if p['targets'] else '—'),
            ('✅' if r else ('❌ 必需' if p['required'] else '⚪ 可选')), p['note'][:90]))
    L += ['', '## 仍然无法自动化、必须人在真机上做', '',
          '1. `shim/hello` 探测：framebuffer 宽/高/stride/格式、16K 页支持、ABL 装载地址。'
          '**只读 SSPP 子块**，读 MDSS 顶层寄存器会在时钟关闭时让整机重启（上游 t2 实测）。',
          '2. TLMM 真实基址：DT 写 `0x0f000000`，SM8850 硬件实测 `0x0f100000`，必须自行确认。',
          '3. 触摸主屏确认 IRQ、逐个按物理键确认 GPIO、面板亮度 DCS 读回。',
          '4. 首次真机启动用 60–120 秒短超时（`pandora_reboot_after`），并先跑 '
          '`tools/safe_boot.sh` 的 dry-run。', '',
          '> 数据齐全 ≠ 能开机。所有 `required` 项齐备且 `--attest` 之后，'
          '`tools/safe_boot.sh` 还有 12 项运行时检查（备份、`boot_b` 哈希、'
          'DSU 状态、pinned 文件、机型、超时）才会放行 `--commit`。', '']
    open(os.path.join(cdir, 'PORT_CHECKLIST.md'), 'w', encoding='utf-8').write('\n'.join(L))

    print('   wrote %s, %s, %s' % (
        os.path.relpath(PROFILE, WR), os.path.relpath(os.path.join(odir, 'adt_overrides.json'), WR),
        os.path.relpath(os.path.join(cdir, 'PORT_CHECKLIST.md'), WR)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
