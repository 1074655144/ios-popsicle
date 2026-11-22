#!/usr/bin/env python3
"""Verify nw_all.o exports every ABI symbol the kernel's 0361 patch expects."""
import os
import subprocess

obj = os.environ.get('NW_ALL_O', os.path.expanduser('~/17pm-work/wl/nw_all.o'))
nm = subprocess.run(['llvm-nm-18', obj], capture_output=True, text=True).stdout
defined = set()
for line in nm.splitlines():
    parts = line.split()
    if len(parts) >= 3 and parts[-2] in 'TtDdBbRrSsAa':
        defined.add(parts[-1].lstrip('_'))
    elif len(parts) >= 2 and parts[-1].startswith('_'):
        defined.add(parts[-1].lstrip('_'))

abi = [
    'nw_wifi_buffer_stats_get', 'nw_wifi_buffer_pool_configure', 'nw_wifi_buffer_pool_trim',
    'nw_wifi_set_events', 'nw_wifi_scan', 'nw_wifi_bss_count', 'nw_wifi_bss_get',
    'nw_wifi_connect', 'nw_wifi_disconnect', 'nw_wifi_power', 'nw_wifi_tx',
    'nw_wifi_tx_packet', 'nw_wifi_status_get', 'nw_wifi_tx_reasons', 'nw_wifi_link_state',
    'nw_wifi_start', 'nw_wifi_set_platform', 'nw_wifi_step', 'nw_wifi_irq_mode',
    'nw_wifi_irq_pending', 'nw_wifi_poll', 'nw_wifi_wait_ms', 'nw_wifi_stop',
    'nw_mhi_crash_report', 'nw_wifi_control_transport_set', 'nw_wifi_stats', 'nw_wifi_where',
]
missing = [s for s in abi if s not in defined]
print(f'ABI symbols: {len(abi) - len(missing)}/{len(abi)} defined')
for s in missing:
    print('  MISSING:', s)
if missing:
    raise SystemExit(1)
