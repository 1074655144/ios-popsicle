#!/usr/bin/env python3 -I
"""Compile every Ath12kWifi source to LLVM bitcode.

Bitcode can be merged with llvm-link as a substitute for `ld -r`, which LLD
does not provide for Mach-O. Paths are overridable by environment variables:

  ATH12K_ROOT   source tree root (default ~/17pm-work/src/Ath12kWifi)
  NW_BC_DIR     output bitcode directory (default ~/17pm-work/wl/bc)
"""
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

root = Path(os.environ.get('ATH12K_ROOT', os.path.expanduser('~/17pm-work/src/Ath12kWifi')))
out = Path(os.environ.get('NW_BC_DIR', os.path.expanduser('~/17pm-work/wl/bc')))
out.mkdir(parents=True, exist_ok=True)
CL = '/usr/lib/llvm-18/lib/clang/18/include'
base = [
    '/usr/bin/clang', '-c', '-target', 'arm64-apple-macos13.0', '-mkernel',
    '-fno-stack-protector', '-nostdinc', '-isystem', str(root / 'shim/libc'),
    '-isystem', CL, '-std=gnu11', '-O2', '-w', '-g0',
    '-DCONFIG_ATH12K_DEBUG', '-DCONFIG_CFG80211=1', '-DCONFIG_MAC80211=1',
    '-DCONFIG_MAC80211_STA_HASH_MAX_SIZE=0', '-DCONFIG_MAC80211_RC_DEFAULT=""',
    '-fno-strict-aliasing', '-fwrapv', '-Wno-incompatible-pointer-types',
    '-include', 'lx_pci.h', '-emit-llvm',
]
for d in ('shim/include', 'include', 'src', 'out/pinned', 'out', 'out/ath12k-src'):
    base += ['-I', str(root / d)]

jobs = []
for line in (root / 'tools/sources.txt').read_text().splitlines():
    line = line.strip()
    if not line or line.startswith('#'):
        continue
    tree, _, name = line.partition(':') if ':' in line else ('', '', line)
    extra = []
    if tree == 'mhi' and name == 'init.c':
        src = root / 'out/os-src/mhi-init.c'
        extra += ['-I', str(root / 'out/mhi-src')]
    elif tree in ('mac80211', 'cfg80211', 'crypto', 'ath12k', 'mhi'):
        src = root / 'out' / ({'ath12k': 'ath12k-src', 'mhi': 'mhi-src'}.get(tree, tree)) / name
    elif tree == 'generated':
        src = root / 'out' / name
    elif tree == 'qmi':
        src = root / 'out/os-src' / name
    else:
        src = root / name
    if tree in ('mac80211', 'cfg80211'):
        extra += ['-I', str(root / 'out' / tree)]
    if tree == 'crypto' or name == 'src/nw_crypto_mac80211.c':
        extra += ['-I', str(root / 'shim/crypto'), '-I', str(root / 'out/crypto')]
    if name in ('src/nw_fils.c', 'src/nw_crypto_mac80211.c'):
        extra += ['-I', str(root / 'out/mac80211')]
    if name.startswith('src/nw_cfg80211_'):
        extra += ['-I', str(root / 'out/cfg80211')]
    if tree == 'mhi' or name == 'src/nw_mhi.c':
        extra += ['-I', str(root / 'out/mhi-src')]
    if tree == 'crypto' and name == 'aes-siv.c':
        extra += ['-Daes_siv_encrypt=nw_aes_siv_encrypt', '-Daes_siv_decrypt=nw_aes_siv_decrypt']
    obj = out / (((tree + '_') if tree else '') + name.replace('/', '_').replace('.c', '.bc'))
    jobs.append((src, obj, extra))


def cc(job):
    src, obj, extra = job
    if not src.exists():
        return (src, 'MISSING')
    result = subprocess.run(base[:2] + extra + base[2:] + [str(src), '-o', str(obj)],
                            capture_output=True, text=True)
    return (src, result.stderr[-700:] if result.returncode else None)


with ThreadPoolExecutor(8) as pool:
    results = list(pool.map(cc, jobs))
bad = [r for r in results if r[1]]
print(len(jobs), 'sources,', len(bad), 'failed')
for src, err in bad[:40]:
    print('--', src.name, '|', err[:400] if err else '')
if bad:
    sys.exit(1)
print('bitcode written to', out)
