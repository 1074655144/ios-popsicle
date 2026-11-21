#!/usr/bin/env python3
"""从正常安卓的只读快照解析 byron 的 framebuffer 参数 (无需引导期探测).

数据源 (均为 device/byron/live/ 下已保存的只读采集):
  - drm_framebuffer.txt : debugfs .../dri/9800000.qcom,mdss_mdp/framebuffer
  - drm_state.txt       : debugfs .../dri/9800000.qcom,mdss_mdp/state
  - fdt_final.dts       : dtc -f -I dtb -O dts 解析自 exec-out 的 /sys/firmware/fdt

输出 JSON: device/byron/live/live_framebuffer.json

原理:
  XNU loader (shim/loader/loader.c) 把 ABL 的 cont_splash_region 当线性
  ARGB/BGRA8888 framebuffer 直写 (自刷新). 所以需要的参数就是:
    FB      = cont_splash_region 的物理基址 (FDT reg)
    FB_SIZE = cont_splash_region 的大小
    FB_W/H/STRIDE/FORMAT = 该 framebuffer 的扫描参数
  这些在正常安卓下由 DRM debugfs 直接暴露, 不必冒险做引导期寄存器探测.

用法:
  python3 tools/port/collect_live_framebuffer.py
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
LIVE = os.path.abspath(os.path.join(HERE, '..', '..', 'device', 'byron', 'live'))
OUT = os.path.join(LIVE, 'live_framebuffer.json')

FMTS = {
    'AB24': 0x34324241,  # BGRA8888 little-endian
    'AR24': 0x34325241,  # RGBA8888 little-endian
    'XB24': 0x34325842,  # BGRX8888
    'XR24': 0x34325258,  # RGBX8888
    'BG24': 0x34324742,  # BGR888
    'RG24': 0x34324752,  # RGB888
}


def parse_framebuffers(path):
    text = open(path, encoding='utf-8', errors='replace').read()
    fbs = []
    for block in re.split(r'(?=framebuffer\[)', text):
        m = re.search(r'framebuffer\[(\d+)\]', block)
        if not m:
            continue
        fmt = re.search(r'format=(\S+)', block)
        size = re.search(r'\bsize=(\d+)x(\d+)', block)
        pitch = re.search(r'pitch\[0\]=(\d+)', block)
        if not (fmt and size and pitch):
            continue
        fbs.append({
            'id': int(m.group(1)),
            'format': fmt.group(1),
            'w': int(size.group(1)),
            'h': int(size.group(2)),
            'pitch': int(pitch.group(1)),
        })
    return fbs


def parse_splash(path):
    text = open(path, encoding='utf-8', errors='replace').read()
    # cont_splash_region node: reg = <0x00 0xfc800000 0x00 0x2b00000>;
    for m in re.finditer(r'(\w+)\s*\{[^}]*?label\s*=\s*"cont_splash_region"[^}]*?reg\s*=\s*<([^>]+)>',
                         text, re.S):
        vals = [int(x, 0) for x in re.findall(r'0x[0-9a-fA-F]+|\b\d+\b', m.group(2))]
        # <hi lo hi lo> 64-bit pairs
        if len(vals) >= 4:
            base = (vals[0] << 32) | vals[1]
            size = (vals[2] << 32) | vals[3]
            return m.group(1), base, size
    return None, None, None


def main():
    fb_path = os.path.join(LIVE, 'drm_framebuffer.txt')
    fdt_path = os.path.join(LIVE, 'fdt_final.dts')
    for p in (fb_path, fdt_path):
        if not os.path.exists(p):
            print(f'[x] 缺少快照 {p}\n'
                  f'    先采集:\n'
                  f'      adb shell "cat /dev/okqaeuzc/wz_rmhpt/dri/9800000.qcom,mdss_mdp/framebuffer" > {fb_path}\n'
                  f'      adb exec-out cat /sys/firmware/fdt | dtc -f -I dtb -O dts > {fdt_path}',
                  file=sys.stderr)
            return 2

    fbs = parse_framebuffers(fb_path)
    node, base, size = parse_splash(fdt_path)
    # 主 framebuffer = 面积最大且 32bpp 的 (AB24/AR24), 即扫描输出那块.
    primary = [f for f in fbs if f['format'] in ('AB24', 'AR24', 'XB24', 'XR24')]
    primary = max(primary, key=lambda f: f['w'] * f['h']) if primary else None

    result = {
        'note': '正常安卓只读采集 (DRM debugfs + FDT), 非引导期探测. format 为 SSPP 源侧解压后的线性像素格式 (DSC 在 DSI 后端, 对 CPU 直写透明).',
        'fb_base': f'0x{base:08x}' if base else None,
        'fb_size': f'0x{size:x}' if size else None,
        'splash_node': node,
        'primary_framebuffer': primary,
        'fb_format_le': f"0x{FMTS[primary['format']]:08x}" if primary and primary['format'] in FMTS else None,
        'adtoverride': {},
    }
    if primary and base is not None:
        result['adtoverride'] = {
            'FB': result['fb_base'],
            'FB_SIZE': result['fb_size'],
            'FB_W': str(primary['w']),
            'FB_H': str(primary['h']),
            'FB_STRIDE': str(primary['pitch']),
        }

    os.makedirs(LIVE, exist_ok=True)
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
        f.write('\n')

    print(f'[+] 主 framebuffer: {primary}')
    print(f'[+] splash region : {node} @ {result["fb_base"]} size {result["fb_size"]}')
    print(f'[+] format (LE)   : {result["fb_format_le"]}')
    print(f'[+] ADT override  : {result["adtoverride"]}')
    print(f'[+] 已保存 {OUT}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
