#!/usr/bin/env python3
"""Pull the peach WiFi firmware off a rooted byron phone (read-only).

The WCN7880 (peach, PCI 17cb:110e) firmware files are the same ones the
upstream Ath12kWifi port uses. They stay on the machine; nothing is uploaded.

    python3 tools/wlan/pull_peach_firmware.py [output_dir]

Default output: device/byron/firmware/peach/ next to the repo root.
Requires adb root (byron here runs KSU). Only reads /vendor/firmware_mnt.
"""
import os
import subprocess
import sys
from pathlib import Path

FILES = [
    "amss20.bin",
    "phy_ucode20.elf",
    "aux_ucode20.elf",
    "bdwlan.elf",
    "regdb.bin",
    "qdss_trace_config_v2.cfg",
]
SRC = "/vendor/firmware_mnt/image/peach"


def adb() -> str:
    for candidate in (os.environ.get("ADB", ""), "adb"):
        if not candidate:
            continue
        r = subprocess.run([candidate, "devices"], capture_output=True, text=True)
        if r.returncode == 0 and "device" in r.stdout and "offline" not in r.stdout:
            return candidate
    sys.exit("no adb device found (set ADB=...)")


def main():
    repo = Path(__file__).resolve().parents[2]
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else repo / "device" / "byron" / "firmware" / "peach"
    out.mkdir(parents=True, exist_ok=True)
    a = adb()
    uid = subprocess.run([a, "shell", "id"], capture_output=True, text=True).stdout
    if "uid=0" not in uid:
        sys.exit("adb shell is not root")
    for name in FILES:
        r = subprocess.run([a, "pull", f"{SRC}/{name}", str(out / name)],
                           capture_output=True, text=True)
        if r.returncode != 0:
            sys.exit(f"pull failed for {name}: {r.stderr.strip()}")
        size = (out / name).stat().st_size
        print(f"{name}: {size} bytes")
    print(f"firmware in {out}")


if __name__ == "__main__":
    main()
