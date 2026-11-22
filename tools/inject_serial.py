#!/usr/bin/env python3
"""Inject a device-tree `serial-number` property into an existing SWEETXNU payload.

XNU publishes IOPlatformSerialNumber from the DT root property "serial-number"
(IOPlatformExpert::publishPlatformUUIDAndSerial / IOPlatformExpertDevice::configureDefaults).
Our ADT (mkadt_pandora.py) never set it, so Settings > About and the Setup
Assistant show an empty Serial Number / SN field.

Usage:
  inject_serial.py IN.payload OUT.payload "SERIAL_STRING"

Only the ADT blob and the header's adt_size change. The kernel segments,
cmdline, RAM disk and everything else stay byte-identical. The ADT sits at the
very end of the payload (only 4 bytes of padding follow it), so growing it is
safe.
"""
import struct, sys

sys.path.insert(0, __import__('os').path.dirname(__import__('os').path.abspath(__file__)))
import adt

ADT_OFF, ADT_SIZE = 0x20, 0x28


def main():
    src, dst, serial = sys.argv[1], sys.argv[2], sys.argv[3]
    d = bytearray(open(src, 'rb').read())
    assert d[:8] == b'SWEETXNU', 'not a SWEETXNU payload'
    off, size = struct.unpack_from('<QQ', d, ADT_OFF)
    root, end = adt.parse(bytes(d[off:off + size]))
    assert end == size, f'ADT parse ended at {end}, expected {size}'

    # Remove any pre-existing serial-number / mlb-serial-number, then add ours.
    root.props = [(k, f, v) for k, f, v in root.props
                  if k not in ('serial-number', 'mlb-serial-number')]
    # Two XNU paths read this property, so build a 24-byte blob safe for both:
    #  (a) IOPlatformExpertDevice::configureDefaults -> OSString::withCString(raw):
    #      reads raw[0..] up to the first NUL -> "SERIAL".
    #  (b) IODTPlatformExpert::createSystemSerialNumberString (no '-' present):
    #      output = raw[13..20] + raw[0..2] -> "SERIAL" + prefix, non-empty.
    # Needs len >= 21 and no '-' anywhere so neither path overruns/misroutes.
    s = serial.encode()
    assert len(s) == 8 and b'-' not in s, 'serial must be 8 chars, no hyphen'
    blob = s + b'\0' + b'0000' + s + b'000'   # 8+1+4+8+3 = 24 bytes
    assert len(blob) == 24 and b'-' not in blob
    root.props.append(('serial-number', 0, blob))

    new_adt = adt.serialize(root)
    new = bytearray(d[:off]) + bytearray(new_adt) + bytearray(d[off + size:])
    struct.pack_into('<Q', new, ADT_SIZE, len(new_adt))
    open(dst, 'wb').write(new)
    print(f'serial-number = {serial!r}')
    print(f'ADT {size} -> {len(new_adt)} bytes, payload {len(d)} -> {len(new)} bytes')
    # verify
    r2, e2 = adt.parse(bytes(new[off:off + len(new_adt)]))
    assert e2 == len(new_adt)
    got = r2.prop('serial-number')
    assert got == blob, got
    print('verify OK: raw=', got, ' direct-C=', got.split(b'\0')[0].decode(),
          ' rearranged=', (got[13:21] + got[0:3]).decode())


if __name__ == '__main__':
    main()
