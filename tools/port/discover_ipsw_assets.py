#!/usr/bin/env python3
"""Discover the build-specific cryptex dmg / trustcache names inside an iOS IPSW.

    discover_ipsw_assets.py IPSW_OR_DIR [-o OUT.env] [--verify-sha256 EXPECTED]

Why: the 087-xxx-xxx cryptex dmg and trustcache file names are build-specific.
The project hard-codes the iOS 16.7.16 (20H392) triple:

    087-86698-044.dmg.trustcache   087-86593-047.dmg.trustcache   087-86715-047.dmg.trustcache

Those names are WRONG for iOS 16.5 (20F66) and any other build. This tool reads
BuildManifest.plist from the IPSW (a .ipsw zip, or an already-extracted directory)
and emits the REAL names for the given IPSW. Nothing is guessed or copied from
another version -- if the manifest does not carry a trust cache, it is omitted.

It writes a sourceable shell env file (default ./ipsw_assets.env) with:

    IPSW_VERSION='16.5'
    IPSW_BUILD='20F66'
    CRYPTEX_DMGS='087-....dmg 087-....dmg 087-....dmg'
    TRUSTCACHE_FILES='087-....dmg.trustcache ...'

The FIRST trustcache emitted is StaticTrustCache -- pass it as the static cache
(module 0) to addtrustcache.py, matching the 16.7.16 flow. BuildManifest layout verified
on iOS 16.5 (20F66) and 16.7.16 (20H392): ProductVersion is a TOP-LEVEL key and each
trust cache is its own manifest entry (Info.Path -> Firmware/NNN-NNNNN-NNN.dmg.trustcache).

Downstream scripts prepend their own directory:
    dmg files live at <ipsw-root>/<name>
    trustcache files live at <ipsw-root>/Firmware/<name>

Only Python 3 stdlib is used. Works on Windows, macOS and Linux/WSL.
"""
import argparse
import hashlib
import os
import plistlib
import sys
import zipfile

# Variable names emitted into the env file (kept identical to what the shell scripts read).
K_VERSION = "IPSW_VERSION"
K_BUILD = "IPSW_BUILD"
K_DMGS = "CRYPTEX_DMGS"
K_TCS = "TRUSTCACHE_FILES"


def _read_manifest(src):
    """Return (plist_bytes, list_of_zip_names_or_None)."""
    if os.path.isdir(src):
        p = os.path.join(src, "BuildManifest.plist")
        if not os.path.isfile(p):
            # deeper (ipsw/ext style)
            for root, _dirs, files in os.walk(src):
                if "BuildManifest.plist" in files:
                    p = os.path.join(root, "BuildManifest.plist")
                    break
            else:
                raise SystemExit("BuildManifest.plist not found under " + src)
        return open(p, "rb").read(), None
    if not os.path.isfile(src):
        raise SystemExit("not a file or directory: " + src)
    with zipfile.ZipFile(src) as z:
        names = z.namelist()
        cands = [n for n in names if n.endswith("BuildManifest.plist")]
        if not cands:
            raise SystemExit("BuildManifest.plist not found in " + src)
        return z.read(cands[0]), names


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def discover(src):
    raw, zip_names = _read_manifest(src)
    bm = plistlib.loads(raw)
    # ProductVersion / ProductBuildVersion live at the TOP level of BuildManifest.plist,
    # NOT under BuildIdentities[i].Info (that Info has BuildNumber/BuildTrain instead).
    version = bm.get("ProductVersion", "")
    build = bm.get("ProductBuildVersion", "")
    identities = bm.get("BuildIdentities", [])
    if not identities:
        raise SystemExit("BuildManifest has no BuildIdentities")
    manifest = identities[0].get("Manifest", {})

    def in_zip(name, full):
        return zip_names is None or name in zip_names or full in zip_names

    # In iOS 16 IPSWs the trust caches are their OWN manifest entries whose Info.Path
    # ends in ".dmg.trustcache" -- there is no per-dmg "TrustCache" field. Order matters:
    # StaticTrustCache first (static cache / module 0), then SystemOS, then AppOS, matching
    # the 16.7.16 flow (087-86698-044 / 087-86593-047 / 087-86715-047).
    # Deliberately NOT including RestoreTrustCache (RAMDisk, recovery-only) or any
    # generic *.trustcache scan -- the boot flow needs exactly these three.
    tc_keys = ["StaticTrustCache", "Cryptex1,SystemTrustCache", "Cryptex1,AppTrustCache"]
    tcs = []
    for key in tc_keys:
        entry = manifest.get(key)
        full = (entry.get("Info") or {}).get("Path", "") if isinstance(entry, dict) else ""
        if not full.lower().endswith(".trustcache"):
            continue
        name = os.path.basename(full)
        if in_zip(name, full) and name not in tcs:
            tcs.append(name)

    # Cryptex/OS dmg names: OS + SystemOS + AppOS Info.Path (e.g. 087-86698-044.dmg).
    dmgs = []
    for key in ["OS", "Cryptex1,SystemOS", "Cryptex1,AppOS"]:
        entry = manifest.get(key)
        full = (entry.get("Info") or {}).get("Path", "") if isinstance(entry, dict) else ""
        if not full.lower().endswith(".dmg"):
            continue
        name = os.path.basename(full)
        if in_zip(name, full) and name not in dmgs:
            dmgs.append(name)

    if not tcs:
        raise SystemExit(
            "No cryptex trust caches found in the manifest. This IPSW may not be an "
            "iPhone X iOS 16 IPSW, or its cryptex layout differs -- inspect manually."
        )
    return version, build, dmgs, tcs


def shell_quote(s):
    return "'" + s.replace("'", "'\\''") + "'"


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("src", help="the .ipsw file, or an extracted IPSW directory")
    ap.add_argument("-o", "--out", default="ipsw_assets.env",
                    help="sourceable shell env to write (default: ./ipsw_assets.env)")
    ap.add_argument("--verify-sha256", default=None,
                    help="expected IPSW SHA256; fails loudly on mismatch")
    args = ap.parse_args()

    version, build, dmgs, tcs = discover(args.src)

    if args.verify_sha256 and os.path.isfile(args.src):
        actual = sha256_of(args.src)
        if actual.lower() != args.verify_sha256.lower():
            raise SystemExit(
                "SHA256 MISMATCH\n  expected %s\n  actual   %s" %
                (args.verify_sha256.lower(), actual.lower())
            )
        print("SHA256 OK: " + actual)

    lines = [
        "# Generated by tools/port/discover_ipsw_assets.py -- DO NOT EDIT BY HAND.",
        "# Source: %s" % os.path.abspath(args.src),
        "%s=%s" % (K_VERSION, shell_quote(version)),
        "%s=%s" % (K_BUILD, shell_quote(build)),
        "%s=%s" % (K_DMGS, shell_quote(" ".join(dmgs))),
        "%s=%s" % (K_TCS, shell_quote(" ".join(tcs))),
    ]
    out = os.path.abspath(args.out)
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")

    print("ProductVersion: %s   ProductBuildVersion: %s" % (version, build))
    print("cryptex dmg (%d): %s" % (len(dmgs), " ".join(dmgs)))
    print("trustcache   (%d): %s" % (len(tcs), " ".join(tcs)))
    print("wrote " + out)


if __name__ == "__main__":
    main()
