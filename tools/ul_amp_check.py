#!/usr/bin/env python3
"""Read-only check: did the --amp fix restore thread scheduling past the 22s stall?

Compares against the known-bad signature: SpringBoard 0 self-logs, log stops at 22.7s,
frame swaps only at 19-22s, still-in-buddy. Usage: ul_amp_check.py ul_AMP.jsonl
"""
import json
import re
import sys

p = sys.argv[1]
rows = []
for line in open(p, errors='replace'):
    try:
        rows.append(json.loads(line))
    except Exception:
        pass
rows.sort(key=lambda d: d.get('timestamp', ''))

print('lines', len(rows))
if not rows:
    sys.exit(0)
last = rows[-1]['timestamp']
print('first', rows[0]['timestamp'][:23], 'last', last[:23])

sb = [d for d in rows if 'SpringBoard' in (d.get('process') or '')]
print('SpringBoard self-logs:', len(sb))

# log coverage span in seconds
from datetime import datetime
fmt = '%Y-%m-%dT%H:%M:%S.%f'
try:
    t0 = datetime.strptime(rows[0]['timestamp'][:26], fmt)
    t1 = datetime.strptime(last[:26], fmt)
    print('coverage_sec', round((t1 - t0).total_seconds(), 1))
except Exception:
    pass

pats = {
    'buddy_0': r'Device PastBuddy is 0',
    'buddy_1': r'Device PastBuddy is 1',
    'still_in_buddy': r'still in buddy',
    'removeOverlay': r'removeOverlay',
    'no_screen_owner': r'No explicit screen owner',
    'bkbootui_timeout': r'BKBootUIPresenter',
    'sys_shell': r'System shell connected',
    'first_boot': r'First boot:',
    'lsd': r'\blsd\b|lsd\[',
    'gestalt_cache_missing': r'com.apple.MobileGestalt.plist: No such file',
    'exec_lsw': r'exec loginwindow',
    'data_migration': r'Data Migration',
}
for name, pat in pats.items():
    c = sum(1 for d in rows if re.search(pat, d.get('message') or ''))
    print(f'{name:22s} {c}')

# per-second tail activity
from collections import Counter
c = Counter(d['timestamp'][11:19] for d in rows)
print('last active seconds:')
for k in sorted(c)[-8:]:
    print('  ', k, c[k])

if sb:
    print('--- first SpringBoard self-logs ---')
    for d in sb[:15]:
        print(' ', d['timestamp'][11:23], (d.get('message') or '').replace('\n', ' ')[:140])
