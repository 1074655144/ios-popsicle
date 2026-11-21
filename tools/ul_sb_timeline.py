#!/usr/bin/env python3
"""Build a focused white-Apple crash timeline from a parsed unified-log jsonl.

Read-only. Usage: ul_sb_timeline.py <ul.jsonl>

Why: pid 25 is runningboardd, pid 26 is SpringBoard in this boot. Generic
probes mis-attributed runningboardd chatter to SpringBoard. This script keys
off process name and specific crash/bootUI markers instead.
"""
import json, sys, collections

p = sys.argv[1]
rows = []
for line in open(p, errors='replace'):
    try:
        rows.append(json.loads(line))
    except Exception:
        pass

def ts(d):
    return d.get('timestamp') or ''

rows = sorted(rows, key=ts)

def msg(d):
    return (d.get('message') or '').replace('\n', ' ')

def show(d, n=280):
    return '{} [{}] {}: {}'.format(ts(d), d.get('log_type', ''), d.get('process') or '?', msg(d)[:n])

# 1. process name distribution for SpringBoard-ish
print('=== processes whose name mentions SpringBoard/FrontBoard/BootUI ===')
c = collections.Counter(d.get('process') or '?' for d in rows
                        if any(k in (d.get('process') or '') for k in
                               ('SpringBoard', 'FrontBoard', 'BootUI', 'backboardd')))
for k, v in c.most_common():
    print('  {:6}  {}'.format(v, k))

# 2. SpringBoard process own messages (name == ...SpringBoard)
print()
print('=== SpringBoard process OWN messages ===')
sb = [d for d in rows if (d.get('process') or '').endswith('SpringBoard')
      or 'SpringBoard.app' in (d.get('process') or '')]
print('  count =', len(sb))
for d in sb[:80]:
    print(' ', show(d))

# 3. The decisive markers, time ordered
print()
print('=== CRASH / BOOTUI MARKERS (time ordered) ===')
markers = ('Simulating crash', 'Software renderer', 'Current bootUI',
           'updateOverlay', 'screen owner', 'BKBootUIPresenter',
           'exit reason', 'namespace', 'exited --', 'assertion failed',
           'exec SpringBoard', 'exec backboardd', 'exec launchd',
           'pandora-metal', 'no pipeline', 'device refused')
hit = [d for d in rows if any(k in msg(d) for k in markers)]
for d in hit[:260]:
    print(' ', show(d))
print('  (total {})'.format(len(hit)))
