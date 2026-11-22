#!/usr/bin/env python3
"""Repack an existing loader Image with a new payload.bin, without the NDK.

The loader Image = fixed loader skeleton + embedded payload.bin.  The C/asm
skeleton (compiled once, in shim/loader/wsl-out/Image) does not change between
boots; only the XNU payload (which carries the boot cmdline) does.  When the
Android NDK is unavailable, this tool swaps the payload in place and repacks
the boot image, reproducing the post-link steps of shim/loader/build.sh.

Usage:
    python3 loader_repack.py BASE_IMAGE NEW_PAYLOAD OUT_IMG

BASE_IMAGE   a previously built Image (shim/loader/wsl-out/Image).  Its payload
             is located by matching the prefix of the currently expected
             payload, or by the fixed loader skeleton size.
NEW_PAYLOAD  freshly built payload.bin (from make_phone_payload.sh).
OUT_IMG      output boot image (v4, no ramdisk).

No device access, no flashing, no network.  Pure local file transformation.
"""
import struct
import sys
import os

PAGE = 4096
PAYLOAD_OFF = 0x39000  # loader skeleton size in the verified wsl-out/Image


def main():
    if len(sys.argv) != 4:
        sys.exit(__doc__)
    base_path, payload_path, out_path = sys.argv[1], sys.argv[2], sys.argv[3]
    img = open(base_path, 'rb').read()
    new = open(payload_path, 'rb').read()

    assert img[0x38:0x3C] == b'ARM\x64', 'BASE_IMAGE has no arm64 Image magic'
    old_size = struct.unpack_from('<Q', img, 16)[0]
    assert old_size == len(img), (old_size, len(img))

    # Sanity: the region right after the skeleton must be the old payload
    # (dense bytes, not the skeleton).  We only rely on the fixed offset.
    assert PAYLOAD_OFF % PAGE == 0 and PAYLOAD_OFF < len(img)
    skeleton = img[:PAYLOAD_OFF]
    assert any(skeleton), 'empty skeleton'

    # Rebuild Image: skeleton + new payload, with image_size updated.
    out_img = skeleton + new
    out_img = bytearray(out_img)
    struct.pack_into('<Q', out_img, 16, len(out_img))
    out_img = bytes(out_img)
    assert out_img[0x38:0x3C] == b'ARM\x64'

    # mkbootimg_v4 header (identical to tools/mkbootimg_v4.py).
    hdr = struct.pack('<8sIIII4II1536sI', b'ANDROID!', len(out_img), 0, 0, 1584,
                      0, 0, 0, 0, 4, b'', 0)
    assert len(hdr) == 1584
    pad = lambda b: b + b'\0' * (-len(b) % PAGE)
    open(out_path, 'wb').write(pad(hdr) + pad(out_img))

    import hashlib
    print('skeleton %d B + payload %d B -> Image %d B' %
          (len(skeleton), len(new), len(out_img)))
    print('bootimg %d B  sha256=%s' %
          (os.path.getsize(out_path), hashlib.sha256(open(out_path, 'rb').read()).hexdigest()[:16]))


if __name__ == '__main__':
    main()
