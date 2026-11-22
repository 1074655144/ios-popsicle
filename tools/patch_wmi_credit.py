#!/usr/bin/env python3
"""byron/XNU WiFi: disable host-side WMI HTC credit flow control.

Rationale (from wifispk boot 2026-11-22):
  - HTC ready gives the WMI endpoint only 2 tx credits.
  - Once the firmware reaches mission mode it sends no further credit reports
    (our RX is polled, not interrupt-driven), so the credits never refill.
  - The first ath12k_mac_start WMI_PDEV_SET_PARAM then waits 3 s on
    tx_credits_wq and returns -EAGAIN (-11); radio-on never completes.
  - WMI commands are serialized (ath12k_wmi_cmd_send waits for each
    completion), so concurrency is 1; dropping the *host-side* credit check
    cannot overrun the firmware. We deliberately do NOT set the wire flag
    ATH12K_HTC_CONN_FLAGS_DISABLE_CREDIT_FLOW_CTRL for WMI, so the firmware's
    own accounting is unchanged -- we only set the local endpoint boolean via
    the existing `disable_credit_flow_ctrl` path.

Also enrich the WMI timeout warning with the current credit/flow state so a
single boot tells us whether credits were the cause.

Idempotent: safe to re-run.
"""
from pathlib import Path

ROOT = Path('/root/17pm-work/src/Ath12kWifi')

# --- htc.c: close host-side credit check on every service, WMI included -------
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

# --- wmi.c: report credit state on timeout -----------------------------------
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
