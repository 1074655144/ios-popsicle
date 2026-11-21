#!/usr/bin/env python3
"""Extract the boot assets from an iPhone X IPSW into the WSL work directory.

    unpack_ipsw_assets.py IPSW [-o /opt/work/ipsw] [--verify]

Extracts exactly the files the build chain expects, with SHA384 verification against
BuildManifest.plist when --verify is given (Apple's Digest field). Nothing is written
to the phone; the IPSW is opened read-only.

Layout produced (matching mac/build_boot.sh, wsl/make_phone_payload.sh, mkadt_pandora.py):

    <out>/BuildManifest.plist
    <out>/kernelcache.release.iphone10b        (raw IM4P; thin macho step needs ipsw CLI)
    <out>/d22ap.adt                            (only if `ipsw` CLI present: im4p extract)
    <out>/Firmware/all_flash/DeviceTree.d22ap.im4p
    <out>/Firmware/all_flash/applelogo@3x~iphone.im4p
    <out>/<cryptex dmg files>                  (087-86698-044.dmg etc.)
    <out>/Firmware/<cryptex>.dmg.trustcache
    <out>/logo/applelogo@3x~iphone.im4p        (make_phone_payload.sh default LOGO path)

The im4p -> ADT and im4p -> thin-macho conversions are Apple-artifact transformations
handled by the `ipsw` CLI on macOS/Linux. When it is unavailable the raw im4p files are
still extracted and the script prints the exact commands to finish the conversion.
"""
import argparse
import hashlib
import os
import plistlib
import shutil
import subprocess
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from discover_ipsw_assets import discover  # noqa: E402


def wanted_files(manifest):
    """Relative paths inside the IPSW that the build chain consumes."""
    out = set()
    out.add("BuildManifest.plist")

    def path_of(key):
        e = manifest.get(key)
        return (e.get("Info") or {}).get("Path", "") if isinstance(e, dict) else ""

    for key in ["OS", "Cryptex1,SystemOS", "Cryptex1,AppOS"]:
        p = path_of(key)
        if p:
            out.add(p)
    for key in ["StaticTrustCache", "Cryptex1,SystemTrustCache", "Cryptex1,AppTrustCache"]:
        p = path_of(key)
        if p:
            out.add(p)
    for key in ["KernelCache", "AppleLogo"]:
        p = path_of(key)
        if p:
            out.add(p)
    # The manifest's DeviceTree entry points at d221ap.im4p, but the build chain
    # (mkadt_pandora.py) needs the D22AP tree. Both exist in the IPSW; use d22ap.
    out.add("Firmware/all_flash/DeviceTree.d22ap.im4p")
    return out


def digest_of(entry):
    d = entry.get("Digest") if isinstance(entry, dict) else None
    return d if isinstance(d, bytes) else None


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("ipsw")
    ap.add_argument("-o", "--out", default="/opt/work/ipsw")
    ap.add_argument("--verify", action="store_true",
                    help="verify SHA384 of each entry against BuildManifest Digest")
    args = ap.parse_args()

    ipsw = os.path.abspath(args.ipsw)
    out = os.path.abspath(args.out)
    os.makedirs(out, exist_ok=True)

    with zipfile.ZipFile(ipsw) as z:
        names = set(z.namelist())
        bm = plistlib.loads(z.read("BuildManifest.plist"))
        manifest = bm["BuildIdentities"][0]["Manifest"]
        want = wanted_files(manifest)

        missing = sorted(p for p in want if p not in names)
        if missing:
            print("ERROR: expected files missing from IPSW:", file=sys.stderr)
            for m in missing:
                print("  " + m, file=sys.stderr)
            return 2

        # path -> Digest bytes, for verification
        digests = {}
        for _k, e in manifest.items():
            if not isinstance(e, dict):
                continue
            p = (e.get("Info") or {}).get("Path", "")
            if p:
                d = digest_of(e)
                if d:
                    # Some paths are shared by two entries (e.g. AppleLogo and RestoreLogo
                    # both use applelogo@3x~iphone.im4p, with DIFFERENT digests). Keep the
                    # first one (AppleLogo/customer variant), which is what we consume.
                    digests.setdefault(p, d)

        for rel in sorted(want):
            dest = os.path.join(out, rel)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            data = z.read(rel)
            with open(dest, "wb") as f:
                f.write(data)
            note = ""
            if args.verify and rel in digests:
                got = hashlib.sha384(data).digest()
                ok = got == digests[rel]
                note = "  [sha384 %s]" % ("OK" if ok else "MISMATCH")
                if not ok:
                    print("ERROR: sha384 mismatch for " + rel, file=sys.stderr)
                    return 3
            print("%s (%d bytes)%s" % (rel, len(data), note))

    # make_phone_payload.sh expects the logo under <out>/logo/
    logo_src = os.path.join(out, "Firmware/all_flash/applelogo@3x~iphone.im4p")
    logo_dir = os.path.join(out, "logo")
    os.makedirs(logo_dir, exist_ok=True)
    if os.path.exists(logo_src):
        shutil.copyfile(logo_src, os.path.join(logo_dir, "applelogo@3x~iphone.im4p"))
        print("logo/applelogo@3x~iphone.im4p  (copy)")

    # version/build summary from the discovered assets
    version, build, _dmgs, _tcs = discover(ipsw)
    print("\nExtracted iOS %s (%s) assets to %s" % (version, build, out))

    # Optional im4p conversions
    ipsw_cli = shutil.which("ipsw")
    if ipsw_cli:
        dt = os.path.join(out, "Firmware/all_flash/DeviceTree.d22ap.im4p")
        adt = os.path.join(out, "d22ap.adt")
        print("ipsw CLI found: extracting d22ap.adt ...")
        r = subprocess.run([ipsw_cli, "img4", "im4p", "extract", dt, "-o", adt],
                           capture_output=True, text=True)
        print(r.stdout.strip() or r.stderr.strip())
        if r.returncode != 0:
            print("WARN: ipsw im4p extract failed; run it manually.", file=sys.stderr)
    else:
        print("\nNOTE: `ipsw` CLI not found. Remaining conversions (do on macOS/WSL with ipsw installed):")
        print("  ipsw img4 im4p extract %s/Firmware/all_flash/DeviceTree.d22ap.im4p -o %s/d22ap.adt" % (out, out))
        print("  # kernelcache.thin.macho: extract the bare macho from %s/kernelcache.release.iphone10b" % out)
        print("  #   (e.g. `ipsw extract --kernel` or img4tool -e; the IM4P payload is a compressed macho)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
