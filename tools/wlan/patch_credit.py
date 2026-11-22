#!/usr/bin/env python3
"""XNU WiFi: disable the host-side WMI HTC credit flow-control check.

The WMI endpoint gets only two TX credits at HTC ready. With polled RX no
further credit reports arrive after firmware reaches mission mode, so the host
credit check can block a WMI command even though commands are serialized and
the firmware side has capacity. The wire flag is left unchanged; only the
local endpoint boolean is set. Timeout warnings include the credit state.

Idempotent. Set ATH12K_ROOT to override the source tree location.
"""
import os
from pathlib import Path

ROOT = Path(os.environ.get('ATH12K_ROOT', os.path.expanduser('~/17pm-work/src/Ath12kWifi')))

htc = ROOT / 'out/ath12k-src/htc.c'
s = htc.read_text()
old = """	/* Only enable credit flow control for WMI ctrl service */
	if (!(conn_req->service_id == ATH12K_HTC_SVC_ID_WMI_CONTROL ||
	      conn_req->service_id == ATH12K_HTC_SVC_ID_WMI_CONTROL_MAC1 ||
	      conn_req->service_id == ATH12K_HTC_SVC_ID_WMI_CONTROL_MAC2)) {
		flags |= ATH12K_HTC_CONN_FLAGS_DISABLE_CREDIT_FLOW_CTRL;
		disable_credit_flow_ctrl = true;
	}
"""
marker = '/* BYRON-CREDIT-FIX: host-side WMI credit check disabled */'
new = old + ('\t' + marker + '\n'
             '\tdisable_credit_flow_ctrl = true;\n')
if marker in s:
    print('htc.c: already patched')
else:
    assert old in s, 'htc.c: anchor not found'
    htc.with_suffix('.c.pre-credit').write_text(s)
    htc.write_text(s.replace(old, new, 1))
    print('htc.c: patched (host-side WMI credit check disabled)')

wmi = ROOT / 'out/ath12k-src/wmi.c'
s = wmi.read_text()
old2 = '''	if (ret == -EAGAIN)
		ath12k_warn(wmi_ab->ab, "wmi command %d timeout\\n", cmd_id);
'''
marker2 = 'BYRON-CREDIT-FIX'
new2 = '''	if (ret == -EAGAIN)
		ath12k_warn(wmi_ab->ab, "wmi command %d timeout: eid %d credits %d flow %d\\n", cmd_id,
			    wmi->eid, wmi_ab->ab->htc.endpoint[wmi->eid].tx_credits,
			    wmi_ab->ab->htc.endpoint[wmi->eid].tx_credit_flow_enabled);
'''
if marker2 in s:
    print('wmi.c: already patched')
else:
    assert old2 in s, 'wmi.c: anchor not found'
    wmi.with_suffix('.c.pre-credit').write_text(s)
    wmi.write_text(s.replace(old2, new2, 1))
    print('wmi.c: patched (timeout logs credit state)')
