#!/bin/bash
# The Ath12kWifi module (tools/wlan/, built on the Mac with xnu/vendor/nw_all.o as result) in the kernel's link.
set -euo pipefail
[[ "${MACHINE_CONFIG:-}" == SWEET ]] || exit 0
if [[ -f "$GITHUB_WORKSPACE/xnu/vendor/nw_all.o" ]]; then
  cp "$GITHUB_WORKSPACE/xnu/vendor/nw_all.o" bsd/dev/nw_all.o
  echo "Ath12kWifi object staged"
else
  # nw_all.o is a separately-built artifact and is not committed to the repo.
  # Basic boot does not need Wi-Fi (pandora_wlan defaults to 0), but nw_go() in
  # 0361-popsicle-wlan-ath12k-board.patch references the nw_wifi_* ABI symbols,
  # so the link needs them to exist. Emit no-op stubs: they are never called on
  # the default boot path, they only satisfy the linker. Supply a real nw_all.o
  # (built from Ath12kWifi + your phone's peach firmware) to enable Wi-Fi.
  echo "nw_all.o absent: emitting no-op Wi-Fi symbol stubs (Wi-Fi off by default)"
  cat > bsd/dev/nw_all_stub.s <<'ASM'
.text
.macro STUB name
    .globl _\name
_\name:
    mov w0, #0
    ret
.endm
STUB nw_wifi_buffer_stats_get
STUB nw_wifi_buffer_pool_configure
STUB nw_wifi_buffer_pool_trim
STUB nw_wifi_set_events
STUB nw_wifi_scan
STUB nw_wifi_bss_count
STUB nw_wifi_bss_get
STUB nw_wifi_connect
STUB nw_wifi_disconnect
STUB nw_wifi_power
STUB nw_wifi_tx
STUB nw_wifi_tx_packet
STUB nw_wifi_status_get
STUB nw_wifi_tx_reasons
STUB nw_wifi_link_state
STUB nw_wifi_start
STUB nw_wifi_set_platform
STUB nw_wifi_step
STUB nw_wifi_irq_mode
STUB nw_wifi_irq_pending
STUB nw_wifi_poll
STUB nw_wifi_wait_ms
STUB nw_wifi_stop
.data
    .globl _nw_wifi_stats
_nw_wifi_stats: .zero 64
    .globl _nw_wifi_where
_nw_wifi_where: .zero 64
ASM
  "$(xcrun --find clang)" -arch arm64 -c bsd/dev/nw_all_stub.s -o bsd/dev/nw_all.o
  echo "no-op Wi-Fi stubs compiled to bsd/dev/nw_all.o"
fi
printf '\nLD_KERNEL_LIBS += $(SRCROOT)/bsd/dev/nw_all.o\n' >> makedefs/MakeInc.def
