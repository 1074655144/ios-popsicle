#!/usr/bin/env python3
"""Probe a parsed unified-log jsonl for the white-Apple stall. Read-only.

Usage: ul_probe.py <ul.jsonl> [mode]
Modes: span | sb | errors | boot | all
"""
import json, sys, collections

p = sys.argv[1]
mode = sys.argv[2] if len(sys.argv) > 2 else 'all'

rows = []
for line in open(p, errors='replace'):
    try:
        d = json.loads(line)
    except Exception:
        continue
    rows.append(d)

def ts(d):
    return d.get('timestamp') or ''


def show(r, limit_msg=300):
    msg = (r.get('message') or '').replace('\n', ' ')[:limit_msg]
    return '{} [{}] {}: {}'.format(ts(r), r.get('log_type', ''), r.get('process') or '?', msg)


if mode in ('span', 'all'):
    times = sorted(ts(d) for d in rows if ts(d))
    print('=== SPAN: {} rows, {}..{} ==='.format(len(rows), times[0] if times else '-', times[-1] if times else '-'))
    # last timestamp per process (who is still alive at the end)
    last = {}
    for d in rows:
        last[d.get('process') or '?'] = ts(d)
    print('=== last-active processes (top 25 by timestamp) ===')
    for k, v in sorted(last.items(), key=lambda x: x[1])[-25:]:
        print('  {}  {}'.format(v, k))

if mode in ('sb', 'all'):
    print()
    print('=== SpringBoard (pid 25) own messages ===')
    sb = [d for d in rows if d.get('pid') == 25 or 'SpringBoard.app' in (d.get('process') or '')]
    for r in sb[:120]:
        print(' ', show(r))
    print('  (total {})'.format(len(sb)))

if mode in ('errors', 'all'):
    print()
    print('=== Error/Fault events, grouped by process (top 30) ===')
    errs = [d for d in rows if d.get('log_type') in ('Error', 'Fault')]
    byp = collections.Counter((d.get('process') or '?') for d in errs)
    print('  total Error/Fault:', len(errs))
    for k, v in byp.most_common(30):
        print('  {:6}  {}'.format(v, k))
    print()
    print('=== Error/Fault from SpringBoard/backboardd/launchd/securityd (first 80) ===')
    focus = [d for d in errs if any(k in (d.get('process') or '') for k in
             ('SpringBoard', 'backboardd', 'launchd', 'securityd', 'containermanagerd', 'usermanagerd'))]
    for r in focus[:80]:
        print(' ', show(r))

if mode in ('boot', 'all'):
    print()
    print('=== boot/setup/unlock/lockscreen/snapshot keywords (first 120) ===')
    kws = ('setup', 'unlock', 'lockscreen', 'lock screen', 'passcode', 'authenticat', 'activat',
           'user session', 'bootstrap', 'wallpaper', 'snapshot', 'home screen', 'springboard')
    hit = []
    for d in rows:
        msg = (d.get('message') or '').lower()
        if any(k in msg for k in kws):
            hit.append(d)
    for r in hit[:120]:
        print(' ', show(r))
    print('  (total {})'.format(len(hit)))
