#!/usr/bin/env python3
"""Probe a parsed unified-log jsonl for the white-Apple stall. Read-only.

Usage: ul_probe.py <ul.jsonl> [mode]
Modes: span | sb | errors | boot | life | bootui | sim | owner | all

  life   : exec/exit/terminate of SpringBoard/backboardd/launchd in time order
  bootui : BKBootUIPresenter / bootUI / assert / ALS / swap_end events
  sim    : "Software renderer"/"Simulating crash"/ReportCrash crash synthesis
  owner  : screen-owner/overlay handoff chain + per-boot summary + SpringBoard silence
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

def sortrows(rs):
    return sorted(rs, key=lambda d: ts(d))


if mode in ('life', 'all'):
    print()
    print('=== LIFECYCLE: exec/exit/terminate/crash of SB/BB/launchd (time order) ===')
    kws = ('exec ', 'exec(', 'exited', 'exit reason', 'terminate', 'terminating',
           'crashed', 'sig ', 'signal ', 'launchd', 'restart', 'respawn')
    proc_kw = ('SpringBoard', 'backboardd', 'launchd', 'FrontBoard', 'BootUI')
    life = []
    for d in rows:
        msg = (d.get('message') or '')
        proc = (d.get('process') or '')
        if any(k in msg for k in kws) and (any(p in msg for p in proc_kw) or any(p in proc for p in proc_kw)):
            life.append(d)
    for r in sortrows(life)[:200]:
        print(' ', show(r, 260))
    print('  (total {})'.format(len(life)))

if mode in ('bootui', 'all'):
    print()
    print('=== BOOTUI: BKBootUIPresenter/bootUI/assert/ALS/swap_end ===')
    kws = ('BKBootUIPresenter', 'bootUI', 'BootUI', 'AssertMacros', 'assert',
           'ALS', 'swap_end', 'simulate', 'present', 'screen owner', 'CBU_')
    ui = [d for d in rows if any(k in (d.get('message') or '') for k in kws)]
    for r in sortrows(ui)[:200]:
        print(' ', show(r, 260))
    print('  (total {})'.format(len(ui)))

if mode in ('sim', 'all'):
    print()
    print('=== SIM: Software renderer / Simulating crash / ReportCrash synthesis ===')
    kws = ('Software renderer', 'Simulating crash', 'simulated', 'ReportCrash',
           'crash report', 'appex', 'CoreServer')
    sim = [d for d in rows if any(k in (d.get('message') or '') for k in kws)]
    for r in sortrows(sim)[:200]:
        print(' ', show(r, 260))
    print('  (total {})'.format(len(sim)))

if mode in ('owner', 'all'):
    print()
    print('=== OWNER: Apple Logo overlay / screen-owner handoff chain (read-only) ===')
    kws = ('screen owner', 'System shell connected', 'systemShellChanged',
           'Current bootUI', 'Presenting overlay', 'addOverlay', 'removeOverlay',
           'BKBootUIPresenter', 'swap_end', 'first app')
    own = [d for d in rows if any(k in (d.get('message') or '') for k in kws)]
    for r in sortrows(own)[:260]:
        print(' ', show(r, 250))
    print('  (total {})'.format(len(own)))
    # per-boot group summary
    print()
    print('=== per-boot summary ===')
    groups = {}
    for d in rows:
        groups.setdefault(d.get('boot_uuid') or '?', []).append(d)
    for k, v in sorted(groups.items(), key=lambda x: ts(x[1][0])):
        sp = sorted(v, key=ts)
        no_owner = sum(1 for d in v if 'No explicit screen owner' in (d.get('message') or ''))
        rm = sum(1 for d in v if 'removeOverlay' in (d.get('message') or ''))
        gpuarg = 'gpu15' if any('pandora_gpu=15' in (d.get('message') or '') for d in v) else 'NO-gpu15'
        print('  {} {:6} rows {} -> {}  no-owner={} removeOverlay={} {}'.format(
            k[:12], len(v), ts(sp[0])[:24], ts(sp[-1])[:24], no_owner, rm, gpuarg))
    # SpringBoard silence check
    print()
    print('=== SpringBoard process silence ===')
    execs = [d for d in rows if (d.get('message') or '').startswith('exec SpringBoard')]
    own_sb = [d for d in rows if 'springboard' in str(d.get('process', '')).lower()
              or 'springboard' in str(d.get('image', '')).lower()]
    print('  exec SpringBoard count:', len(execs))
    print('  SpringBoard-own unified-log rows:', len(own_sb))

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
