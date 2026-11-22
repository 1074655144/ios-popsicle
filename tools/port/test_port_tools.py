#!/usr/bin/env python3
"""Offline regression tests for the byron port toolchain. No phone, no network,
no partition writes. Run:  python3 tools/port/test_port_tools.py
"""
import glob
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
ANALYZE = os.path.join(HERE, 'analyze_firmware.py')
GENERATE = os.path.join(HERE, 'gen_byron_config.py')
COLLECT = os.path.join(HERE, 'collect_board.sh')
BASELINE = os.path.join(HERE, 'popsicle_baseline.json')

PASS = FAIL = 0


def posix(p):
    """Path as the WSL bash spawned by Python sees it: C:/x -> /mnt/c/x."""
    p = p.replace('\\', '/')
    if re.match(r'^[A-Za-z]:/', p):
        return '/mnt/' + p[0].lower() + p[2:]
    return p


def win(p):
    """Windows-native path with forward slashes (for python.exe arguments)."""
    return p.replace('\\', '/')


def ok(cond, msg):
    global PASS, FAIL
    if cond:
        PASS += 1
        print('  PASS  %s' % msg)
    else:
        FAIL += 1
        print('  FAIL  %s' % msg)


def run(argv, **kw):
    return subprocess.run([sys.executable] + argv, cwd=REPO, capture_output=True,
                          text=True, errors='replace', **kw)


# ---------------------------------------------------------------------------
# a real (minimal) flattened device tree, written by hand so the FDT parser is
# genuinely exercised rather than mocked
# ---------------------------------------------------------------------------
class FDT:
    BEGIN, END_NODE, PROP, END = 1, 2, 3, 9

    def __init__(self):
        self.st = b''
        self.strs = b''
        self.off = {}

    def _s(self, name):
        if name not in self.off:
            self.off[name] = len(self.strs)
            self.strs += name.encode() + b'\0'
        return self.off[name]

    def begin(self, name):
        raw = name.encode() + b'\0'
        self.st += struct.pack('>I', self.BEGIN) + raw + b'\0' * ((-len(raw)) % 4)

    def end(self):
        self.st += struct.pack('>I', self.END_NODE)

    def prop(self, name, value):
        o = self._s(name)
        self.st += struct.pack('>III', self.PROP, len(value), o)
        self.st += value + b'\0' * ((-len(value)) % 4)

    def p32(self, name, *vals):
        self.prop(name, struct.pack('>%dI' % len(vals), *vals))

    def pstr(self, name, *vals):
        self.prop(name, b''.join(v.encode() + b'\0' for v in vals))

    def finish(self):
        st = self.st + struct.pack('>I', self.END)
        off_struct = 56
        off_strings = off_struct + len(st)
        hdr = struct.pack('>10I', 0xd00dfeed, off_strings + len(self.strs),
                          off_struct, off_strings, 40, 17, 16, 0,
                          len(self.strs), len(st))
        return hdr + b'\0' * 16 + st + self.strs


def byron_dtb():
    """SM8850-shaped DTBO: mostly identical SoC registers, different board."""
    b = FDT()
    b.begin('')
    b.p32('#address-cells', 2)
    b.p32('#size-cells', 2)
    b.pstr('compatible', 'xiaomi,byron')

    b.begin('cpus')
    b.p32('#address-cells', 1)
    b.p32('#size-cells', 0)
    for m in (0x0, 0x100, 0x200, 0x300, 0x400, 0x500, 0x10000, 0x10100):
        b.begin('cpu@%x' % m)
        b.pstr('compatible', 'arm,armv8')
        b.p32('reg', m)
        b.end()
    b.end()

    b.begin('memory@80000000')
    b.pstr('device_type', 'memory')
    b.p32('reg', 0, 0x80000000, 0, 0x80000000, 1, 0, 0, 0xfcc00000)
    b.end()

    b.begin('psci')
    b.pstr('compatible', 'arm,psci-1.0')
    b.pstr('method', 'smc')
    b.end()

    b.begin('soc')
    b.p32('#address-cells', 2)
    b.p32('#size-cells', 2)

    b.begin('interrupt-controller@17000000')
    b.pstr('compatible', 'arm,gic-v3')
    b.p32('redistributor-stride', 0x40000)
    b.p32('reg', 0, 0x17000000, 0, 0x10000,
          0, 0x17080000, 0, 0x200000,
          0, 0x17040000, 0, 0x10000)
    b.end()
    b.begin('timer')
    b.pstr('compatible', 'arm,armv8-timer')
    b.p32('clock-frequency', 19200000)
    b.end()
    b.begin('ufshc@1d84000')
    b.pstr('compatible', 'qcom,ufshc')
    b.p32('reg', 0, 0x1d84000, 0, 0x3000)
    b.end()
    b.begin('pinctrl@f000000')
    b.pstr('compatible', 'qcom,canoe-tlmm')
    b.p32('reg', 0, 0x0f000000, 0, 0x100000)
    b.end()
    b.begin('mdss_mdp@9800000')
    b.pstr('compatible', 'qcom,mdss_mdp')
    b.p32('reg', 0, 0x09800000, 0, 0x1c8800)
    b.end()
    b.begin('arbiter@c400000')
    b.pstr('compatible', 'qcom,canoe-spmi-pmic-arb')
    b.p32('reg', 0, 0x0c400000, 0, 0x1000)
    b.end()
    b.begin('spi@1a80000')
    b.pstr('compatible', 'synaptics,tcm-spi')
    b.p32('reg', 0, 0x01a80000, 0, 0x1000)
    b.end()
    b.begin('mdss_dsi_byron_cmd_dsc_panel')
    b.pstr('compatible', 'qcom,dsi-panel')
    b.p32('qcom,mdss-dsi-panel-width', 1200)
    b.p32('qcom,mdss-dsi-panel-height', 2608)
    b.p32('qcom,tdm-max-slots', 2)
    b.end()
    b.begin('pcie@1c00000')
    b.pstr('compatible', 'qcom,pcie')
    b.end()
    b.begin('gpio-keys')
    b.begin('vol_up')
    b.p32('linux,code', 115)
    b.p32('gpios', 101)
    b.end()
    b.end()
    b.end()

    b.begin('reserved-memory')
    b.p32('#address-cells', 2)
    b.p32('#size-cells', 2)
    b.begin('splash_region')
    b.p32('reg', 0, 0xfc800000, 0, 0x2b00000)
    b.end()
    b.end()
    b.end()
    return b.finish()


# ---------------------------------------------------------------------------
# tiny protobuf encoder, used to build a fake (but structurally real) brillo
# update payload entirely offline
# ---------------------------------------------------------------------------
def pb_varint(n):
    out = b''
    while True:
        b = n & 0x7f
        n >>= 7
        out += bytes([b | (0x80 if n else 0)])
        if not n:
            return out


def pb_v(field, value):
    return pb_varint((field << 3) | 0) + pb_varint(value)


def pb_b(field, value):
    return pb_varint((field << 3) | 2) + pb_varint(len(value)) + value


def fake_payload():
    """ZIP local header + CrAU header + manifest + one XZ op + one ZERO op."""
    import hashlib
    import lzma
    chunk = lzma.compress(b'HELLO')
    sha = hashlib.sha256(chunk).digest()
    extent = pb_v(1, 0) + pb_v(2, 1)          # start 0, 1 block of 4096 B
    op1 = (pb_v(1, 8) + pb_v(2, 0) + pb_v(3, len(chunk)) +
           pb_b(6, extent) + pb_b(8, sha))    # REPLACE_XZ
    op2 = (pb_v(1, 6) + pb_b(6, pb_v(1, 1) + pb_v(2, 1)))  # ZERO
    part = (pb_b(1, b'dtbo') + pb_b(7, pb_v(1, 8192)) +
            pb_b(8, op1) + pb_b(8, op2))
    manifest = pb_v(3, 4096) + pb_b(13, part)
    head = (b'CrAU' + struct.pack('>Q', 2) + struct.pack('>Q', len(manifest)) +
            struct.pack('>L', 0))
    lh = b'PK\x03\x04' + b'\0' * 22 + struct.pack('<HH', 0, 0)
    return lh + head + manifest + chunk, len(manifest), chunk


class FakeRemote:
    """Serves bytes from an in-memory blob through the same get(start,end) API."""
    def __init__(self, data):
        self.data = data
        self.size = len(data)

    def get(self, start, end):
        return self.data[start:end + 1]


# ---------------------------------------------------------------------------
def main():
    T = tempfile.mkdtemp(prefix='byron-port-test-')
    try:
        dtb = os.path.join(T, 'byron.dtb')
        open(dtb, 'wb').write(byron_dtb())
        fwjson = os.path.join(T, 'firmware.json')
        report = os.path.join(T, 'DIFF.md')

        print('== 1. FDT 解析 / 固件 diff')
        r = run([ANALYZE, '--dtb', dtb, '--device', 'byron', '--out', fwjson,
                 '--report', report])
        ok(r.returncode == 0, 'analyze_firmware.py 正常退出 (%s)' % r.stderr.strip()[:80])
        result = json.load(open(fwjson, encoding='utf-8'))
        ex = result['extracted']
        ok(ex['gicd']['value'] == '0x17000000', 'GICD = 0x17000000')
        ok(ex['gicr']['value'] == '0x17080000', 'GICR = 0x17080000')
        ok(ex['ufs']['value'] == '0x1d84000', 'UFS = 0x1d84000')
        ok(ex['splash_base']['value'] == '0xfc800000', 'splash_region = 0xfc800000')
        ok(ex['timer_freq']['value'] == '19200000', 'timer = 19.2 MHz')
        ok(ex['tdm_slots']['value'] == '2', 'qcom,tdm-max-slots = 2 (与 popsicle 的 4 不同)')
        ok(ex['mpidrs']['value'] and len(ex['mpidrs']['value']) == 8, '8 个 CPU MPIDR')
        ok(ex['touch_secondary']['value'] is None, '无背屏触摸芯片 (byron 预期缺失)')
        d = {x['key']: x for x in result['diff']}
        ok(d['gicd_base']['verdict'] == 'same', 'gicd_base 判定 same（SoC 级可复用）')
        ok(d['tdm_slots']['verdict'] == 'different', 'tdm_slots 判定 different')
        ok(d['rear_display']['verdict'] == 'different' and d['rear_display']['byron'] == 'none',
           '检出无背屏 → 需要禁用副屏驱动')
        ok(d['panel_phys_w']['byron'] == '1200' and d['panel_phys_w']['verdict'] == 'different',
           '面板物理宽度 1200 ≠ popsicle 1220')
        ok(d['tlmm_base_real']['verdict'] == 'pending_live', 'TLMM 真值被标为必须真机探测')
        ok(d['pinned_extents']['verdict'] == 'pending_build', 'pinned extents 标为构建产物')
        ok('different' in open(report, encoding='utf-8').read(), 'Markdown 报告已生成')

        print('== 2. 生成器：数据不齐时绝不放行')
        live = os.path.join(T, 'live')
        os.makedirs(live)
        open(os.path.join(live, 'props.txt'), 'w').write(
            '[ro.product.device]: [byron]\n[ro.product.model]: [2605EPN8EC]\n')
        open(os.path.join(live, 'power_supply.txt'), 'w').write(
            'POWER_SUPPLY_NAME=battery\nPOWER_SUPPLY_CHARGE_FULL_DESIGN=8000000\n'
            'POWER_SUPPLY_NAME=bms\n')
        open(os.path.join(live, 'by_name.txt'), 'w').write('lrwxrwxrwx ... userdata -> /dev/block/sda34\n')
        open(os.path.join(live, 'dm_table.txt'), 'w').write(
            'userdata: 0-1000869848: default-key aes-xts-plain64 259:18 0\n')
        open(os.path.join(live, 'thermal.txt'), 'w').write('[SS-CPU0]\n' + 'x' * 100)
        wr = os.path.join(T, 'out')
        base = [GENERATE, '--firmware', fwjson, '--live', live, '--write-root', wr]
        r = run(base + ['--check'])
        ok(r.returncode == 0 and 'BOARD_DATA_COMPLETE=no' in r.stdout,
           '缺数据时 COMPLETE=no')
        ok('missing (' in r.stdout, '列出缺失字段')
        r = run(base + ['--check', '--strict'])
        ok(r.returncode == 2, '--strict 在缺数据时退出码 2')
        r = run(base + ['--check', '--attest'])
        ok('BOARD_DATA_COMPLETE=no' in r.stdout, '缺数据时即便 --attest 也不放行')

        print('== 3. 生成器：补齐数据 → data_ready，attest → yes')
        params = json.load(open(BASELINE, encoding='utf-8'))['params']
        manual = {}
        for p in params:
            if p['required']:
                manual[p['key']] = 'measured-%s' % p['key']
        manual['page_size_16k'] = 'yes'
        manual['abl_load_addr'] = '0x9fc00000'
        manual.update({
            'phys_base': '0x8c0000000', 'mem_size': '0x140000000',
            'gicd_base': '0x17000000', 'gicr_base': '0x17080000',
            'fb_w': '1200', 'fb_h': '2608', 'fb_stride': '4800',
            'ufs_base': '0x1d84000', 'timer_freq': '19200000',
            'vtimer_intid': '27', 'dsp_shm': '0xb0000000',
            'splash_base': '0xfc800000', 'splash_size': '0x2b00000',
            'mpidrs': ['0x0', '0x100', '0x200', '0x300', '0x400', '0x500',
                       '0x10000', '0x10100'],
        })
        mp = os.path.join(T, 'manual.json')
        json.dump(manual, open(mp, 'w', encoding='utf-8'))
        r = run(base + ['--manual', mp, '--check'])
        ok('BOARD_DATA_COMPLETE=data_ready' in r.stdout, '数据齐全只给 data_ready（仍被拦截）')
        r = run(base + ['--manual', mp, '--check', '--attest'])
        ok('BOARD_DATA_COMPLETE=yes' in r.stdout, '仅 --attest 后给 yes')
        r = run(base + ['--manual', mp, '--attest', '--write'])
        ok(r.returncode == 0, '--write 正常退出')
        env = open(os.path.join(wr, 'profiles', 'byron.env'), encoding='utf-8').read()
        ok('BOARD_DATA_COMPLETE=yes' in env, '生成的 profile 含 COMPLETE=yes')
        ok('BOARD_TLMM_BASE_REAL=' in env and 'BOARD_GICD_BASE=' in env,
           'profile 用 BOARD_ 前缀保存板级数据，不覆盖 safe_boot 变量')
        ok(len(re.findall(r'^BOARD_DATA_COMPLETE=', env, re.M)) == 1,
           'profile 只有一个生效的 COMPLETE 定义')
        ov = json.load(open(os.path.join(wr, 'device', 'byron', 'adt_overrides.json'), encoding='utf-8'))
        ok(ov['overrides'].get('FB_W') == 1200 and ov['overrides'].get('GICD') == 0x17000000,
           'ADT overrides 数值已正确转换')
        ok(ov['overrides'].get('MPIDRS') == [0, 0x100, 0x200, 0x300, 0x400, 0x500,
                                             0x10000, 0x10100],
           'MPIDRS 列表正确转换')
        ok(not ov.get('skipped_non_numeric'), '数值齐全时无占位值被丢弃')
        ok(os.path.isfile(os.path.join(wr, 'docs', 'byron', 'PORT_CHECKLIST.md')),
           '生成逐项移植清单')
        real_profile = os.path.join(REPO, 'profiles', 'byron.env')
        ok('BOARD_DATA_COMPLETE=no' in open(real_profile, encoding='utf-8').read(),
           '测试未污染真实 profiles/byron.env（安全闸门仍为 no）')

        print('== 4. ADT 覆盖白名单')
        sys.path.insert(0, HERE)
        from board_overlay import apply_board_overrides, ALLOWED
        p = os.path.join(T, 'ov.json')
        json.dump({'overrides': {'GICD': '0x17000000', 'FB_W': 1200,
                                 'MPIDRS': ['0x0', 256]}}, open(p, 'w'))
        ns = {'GICD': 0x1}
        applied = apply_board_overrides(ns, p)
        ok(ns['GICD'] == 0x17000000 and ns['FB_W'] == 1200 and ns['MPIDRS'] == [0, 256],
           '白名单键按 0x/十进制正确转换')
        ok(sorted(applied) == ['FB_W', 'GICD', 'MPIDRS'], '返回已应用键列表')
        json.dump({'overrides': {'EVIL_KEY': 1}}, open(p, 'w'))
        try:
            apply_board_overrides({}, p)
            ok(False, '未知键应被拒绝')
        except ValueError as e:
            ok('non-whitelisted' in str(e), '未知键被拒绝')
        json.dump({'overrides': {'GICD': 'not-a-number'}}, open(p, 'w'))
        try:
            apply_board_overrides({}, p)
            ok(False, '非整数值应被拒绝')
        except ValueError:
            ok(True, '非整数值被拒绝')
        ok('PHYS_BASE' in ALLOWED and 'FB_STRIDE' in ALLOWED, '关键板级常量在白名单内')

        print('== 5. 真机采集脚本：只读 + mock 跑通')
        src = open(COLLECT, encoding='utf-8').read()
        # Only the phone-side read lines matter; prose/README text is ignored.
        cmds = '\n'.join(l for l in src.splitlines()
                         if re.match(r'^\s*grab(bin)?\s', l))
        for bad in ('fastboot boot', 'fastboot flash', 'setprop', 'dd of=',
                    'rawwrite', 'mkfs', 'mount -o', 'rm -rf', 'su -c \'rm'):
            ok(bad not in cmds, '采集命令行不含写操作: %s' % bad)
        mocklog = os.path.join(T, 'adblog.txt')
        mockadb = os.path.join(T, 'mock_adb.py')
        # A Python mock (not a shell script): on Windows a shebang script is not
        # a Win32 executable, so collect's --adb-wrap uses python.exe instead.
        with open(mockadb, 'w', encoding='utf-8') as f:
            f.write('''import sys
LOG = r"%s"
DTB = r"%s"
args = sys.argv[1:]
open(LOG, "a", encoding="utf-8").write(" ".join(args) + "\\n")
if not args:
    pass
elif args[0] == "get-serialno":
    print("MOCKSERIAL")
elif args[0] == "exec-out":
    sys.stdout.buffer.write(open(DTB, "rb").read())
elif args[0] == "shell":
    cmd = args[1] if len(args) > 1 else ""
    if "getprop" in cmd:
        print("[ro.product.device]: [byron]")
        print("[ro.product.model]: [2605EPN8EC]")
    elif "power_supply" in cmd:
        print("POWER_SUPPLY_NAME=battery")
    else:
        print("mock-output")
''' % (win(mocklog), win(dtb)))
        outdir = os.path.join(T, 'capture')
        env = dict(os.environ, COLLECT_NO_SLEEP='1')
        r = subprocess.run(['bash', posix(COLLECT), '--device', 'byron',
                            '--out', posix(outdir), '--adb', win(mockadb),
                            '--adb-wrap', posix(sys.executable)],
                           cwd=REPO, capture_output=True, text=True, errors='replace', env=env)
        ok(r.returncode == 0, 'collect_board.sh 正常退出 (%s)' % r.stderr.strip()[:90])
        ok(os.path.isfile(os.path.join(outdir, 'fdt.dtb')) and
           os.path.getsize(os.path.join(outdir, 'fdt.dtb')) > 40, '导出 live FDT')
        for f in ('props.txt', 'interrupts_1.txt', 'interrupts_2.txt', 'dm_table.txt',
                  'gpt.bin', 'README.txt', 'meta.txt'):
            ok(os.path.isfile(os.path.join(outdir, f)), '生成 %s' % f)
        log = open(mocklog, encoding='utf-8').read()
        for bad in ('fastboot', 'flash', 'setprop', 'dd of=', 'rawwrite', 'mkfs', 'mount -o'):
            ok(bad not in log, 'mock adb 未收到危险命令: %s' % bad)
        ok('getprop' in log and '/sys/firmware/fdt' in log, 'mock adb 收到只读读取命令')

        print('== 6. 语法 / 回归')
        scripts = [COLLECT, os.path.join(REPO, 'mac', 'phone_prepare.sh'),
                   os.path.join(REPO, 'mac', 'boot_ios.sh'),
                   os.path.join(REPO, 'tools', 'safe_boot.sh'),
                   os.path.join(REPO, 'tools', 'safe_recover.sh')]
        r = subprocess.run(['bash', '-n'] + [posix(s) for s in scripts],
                           cwd=REPO, capture_output=True, text=True, errors='replace')
        ok(r.returncode == 0, 'bash -n 全部通过 (%s)' % r.stderr.strip()[:80])
        py = [ANALYZE, GENERATE, os.path.join(HERE, 'board_overlay.py'),
              os.path.join(REPO, 'tools', 'mkadt_pandora.py')]
        r = subprocess.run([sys.executable, '-m', 'py_compile'] + py,
                           cwd=REPO, capture_output=True, text=True, errors='replace')
        ok(r.returncode == 0, 'Python 语法检查通过 (%s)' % r.stderr.strip()[:80])
        r = subprocess.run(['bash', posix(os.path.join(REPO, 'tools', 'tests', 'test_safe_boot.sh'))],
                           cwd=REPO, capture_output=True, text=True, errors='replace')
        ok(r.returncode == 0, '原有 safe_boot 回归通过 (%s)' % r.stdout.strip().splitlines()[-1][:60]
           if r.stdout.strip() else '原有 safe_boot 回归通过')

        print('== 7. OTA 取包 / DTB 拆分工具（完全离线）')
        sys.path.insert(0, HERE)
        import fetch_ota
        import split_dtbo
        import extract_boot_dtbs

        blob, msize, comp = fake_payload()
        rmt = FakeRemote(blob)
        entries = [{'name': 'payload.bin', 'lho': 0}]
        pl = fetch_ota.Payload(rmt, entries)
        ok(pl.version == 2 and pl.manifest_size == msize, 'CrAU 头解析正确')
        ok(pl.block_size == 4096 and 'dtbo' in pl.parts, 'manifest 分区表解析正确')
        ok(pl.parts['dtbo']['size'] == 8192 and len(pl.parts['dtbo']['ops']) == 2,
           'dtbo 分区大小与操作数正确')
        img = pl.extract(rmt, 'dtbo')
        ok(len(img) == 8192 and img[:5] == b'HELLO' and img[5:4096] == b'\0' * 4091,
           'REPLACE_XZ 解压并按 dst_extent 落位（含 SHA-256 校验）')
        ok(img[4096:] == b'\0' * 4096, 'ZERO 操作填充第二段')
        # corrupt the compressed bytes -> the hash check must reject them
        bad = bytearray(blob); bad[-1] ^= 0xff
        try:
            fetch_ota.Payload(FakeRemote(bytes(bad)), entries).extract(
                FakeRemote(bytes(bad)), 'dtbo')
            ok(False, '哈希不符应被拒绝')
        except IOError:
            ok(True, '哈希不符被拒绝')

        fdt = byron_dtb()
        dtbo_img = (struct.pack('>8I', 0xd7b7ab1e, 64 + len(fdt), 32, 32, 1, 32,
                                4096, 0) +
                    struct.pack('>8I', len(fdt), 64, 0, 0, 0, 0, 0, 0) + fdt)
        info = split_dtbo.split(dtbo_img)
        ok(info['entry_count'] == 1 and info['entries'][0]['dt_size'] == len(fdt),
           'dtbo.img 表头与单条目解析正确')
        ok(info['entries'][0]['blob'] == fdt, 'dtbo.img 拆出的 FDT 字节完全一致')
        try:
            split_dtbo.split(dtbo_img[:40] + b'\0' * 20)
            ok(False, '损坏的 dtbo 应被拒绝')
        except ValueError:
            ok(True, '损坏的 dtbo 被拒绝')

        seg = fdt + fdt
        ok(len(extract_boot_dtbs.split_blob(seg)) == 2, 'vendor_boot 拼接 FDT 正确拆分')
        vbh = bytearray(4096)
        vbh[:8] = b'VNDRBOOT'
        struct.pack_into('<2I', vbh, 8, 4, 4096)       # version, page
        struct.pack_into('<2I', vbh, 2096, 2128, len(seg))  # header_size, dtb_size
        off, size = extract_boot_dtbs.vendor_boot_dtb(bytes(vbh) + seg)
        ok(off == 4096 and size == len(seg), 'vendor_boot v4 头定位 dtb 段正确')
        ok([f for f, w, v in fetch_ota.fields(pb_v(3, 4096))] == [3],
           'protobuf 解码器正确解析 varint 字段')

        print('== 8. 真实 byron 固件（存在时才检查，缺失则跳过）')
        real = os.path.join(REPO, 'device', 'byron', 'firmware')
        dtbs = sorted(glob.glob(os.path.join(real, 'dtbs', '*.dtb')))
        if dtbs:
            sys.path.insert(0, os.path.join(REPO, 'tools'))
            import dt as real_dt
            models = [(real_dt.load(p).str('model') or [''])[0] for p in dtbs]
            ok(all('Byron' in m for m in models), '真实 DTBO 型号均为 Byron')
            fw = os.path.join(REPO, 'device', 'byron', 'firmware.json')
            if os.path.isfile(fw):
                d = {x['key']: x for x in json.load(open(fw, encoding='utf-8'))['diff']}
                ok(d['gicd_base']['verdict'] == 'same' and d['ufs_base']['verdict'] == 'same',
                   '真实固件确认 SoC 常量可直接复用')
                ok(d['tdm_slots']['byron'] == '2' and d['wifi_chip']['byron'] == 'qcom,wcn786x',
                   '真实固件确认 TDM=2 / WCN786x')
                ok(d['splash_size']['verdict'] == 'runtime_patched',
                   'splash_size 识别为 bootloader 运行时填值')
        else:
            print('  SKIP 无真实固件（device/byron/firmware 为空），不影响其余测试')

        py = [os.path.join(HERE, 'fetch_ota.py'), os.path.join(HERE, 'split_dtbo.py'),
              os.path.join(HERE, 'extract_boot_dtbs.py'), os.path.join(HERE, 'extract_stock_dump.py')]
        r = subprocess.run([sys.executable, '-m', 'py_compile'] + py,
                           cwd=REPO, capture_output=True, text=True, errors='replace')
        ok(r.returncode == 0, '新增工具 Python 语法检查通过 (%s)' % r.stderr.strip()[:80])

        # --- stock dump: hash cross-check + field mapping (offline) ----------
        import importlib.util
        spec = importlib.util.spec_from_file_location('esd', os.path.join(HERE, 'extract_stock_dump.py'))
        esd = importlib.util.module_from_spec(spec); spec.loader.exec_module(esd)
        ok(esd._wsl_path('C:/Users/tester/x.img') == '/mnt/c/Users/tester/x.img',
           'stock dump: Windows 路径转 WSL /mnt/c 正确')
        fake = {
            'facts': {
                'chips': {
                    'fuel_gauge': {'node': 'bq27z561@55', 'compatible': ['ti,bq27z561_master']},
                    'charger_pmic': {'node': 'smb1501@68', 'compatible': ['qcom,i2c-pmic']},
                    'wlan_chip': {'node': 'wcn786x', 'compatible': []},
                    'audio_amp': {'node': 'tfa98xx_1@34', 'compatible': []},
                },
                'calibration': {'demura_panel_id': '0000000000000000', 'cell_id': 'TESTCELL000000',
                                'wlan_mac': 'wlan0=000000000000'},
            }
        }
        fp = os.path.join(T, 'stock.json')
        json.dump(fake, open(fp, 'w'), ensure_ascii=False)
        gspec = importlib.util.spec_from_file_location('gbc', GENERATE)
        gbc = importlib.util.module_from_spec(gspec); gspec.loader.exec_module(gbc)
        mapped = gbc.parse_stock_dump(fp)
        ok('ti,bq27z561_master' in mapped.get('battery_gauge', ''), 'stock dump: 电量计型号映射')
        ok(mapped.get('wifi_chip') == 'wcn786x', 'stock dump: Wi-Fi 芯片映射')
        ok(mapped.get('panel_id') == '0000000000000000', 'stock dump: 面板 ID 映射')
        # stock data must never fabricate runtime-only fields
        for k in ('memory_banks', 'splash_size', 'fb_w', 'tlmm_base_real', 'page_size_16k'):
            ok(k not in mapped, 'stock dump: 不伪造运行时字段 %s' % k)
    finally:
        shutil.rmtree(T, ignore_errors=True)

    print('\n== %d passed, %d failed' % (PASS, FAIL))
    return 1 if FAIL else 0


if __name__ == '__main__':
    sys.exit(main())
