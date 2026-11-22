#!/usr/bin/env python3
"""Per-boot buddy/overlay verdict from a parsed unified-log jsonl. Read-only.

  tools/ul_buddy_check.py ul_*.jsonl

Earlier probes summed markers across the *whole* jsonl.  One capture can hold
six boots (different boot_uuid), so "exec SpringBoard = 6" looked like a
restart loop when it was one exec in each of six boots.  This tool groups by
boot_uuid first, so the verdict is per boot.
"""
import collections
import json
import sys

KEYS = (
    'exec SpringBoard',
    'System shell connected',
    'First boot:',
    'Current bootUI is an Apple Logo',
    'No explicit screen owner',
    'removeOverlay',
    'BKBootUIPresenter',
    'Device PastBuddy is 0',
    'Device PastBuddy is 1',
    'still in buddy',
    'buddy is done',
    'Software renderer!',
)


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    groups = collections.defaultdict(list)
    for line in open(sys.argv[1], errors='replace'):
        try:
            d = json.loads(line)
        except Exception:
            continue
        groups[d.get('boot_uuid') or '?'].append(d)
    print('boot_uuid      rows   span                     markers')
    for uuid, rows in sorted(groups.items(), key=lambda kv: min(r.get('timestamp', '') for r in kv[1])):
        rows.sort(key=lambda r: r.get('timestamp', ''))
        counts = {k: 0 for k in KEYS}
        for r in rows:
            msg = r.get('message') or ''
            for k in KEYS:
                if k in msg:
                    counts[k] += 1
        hits = ' '.join(f'{k}={v}' for k, v in counts.items() if v)
        print(f'{uuid[:12]:12} {len(rows):6}  {rows[0]["timestamp"][11:23]}..{rows[-1]["timestamp"][11:23]}  {hits}')
    print()
    print('verdict: PastBuddy=1 and removeOverlay>0 -> buddy skipped / desktop reached')
    print('         PastBuddy=0 and removeOverlay=0 -> still stuck in first boot')


if __name__ == '__main__':
    main()
