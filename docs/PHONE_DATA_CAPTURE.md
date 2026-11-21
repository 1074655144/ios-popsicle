# Per-phone capture and bring-up steps

This repository keeps the **tools and the procedure**. Files produced on a
phone (pinned extents, kernel logs, screenshots, root images, firmware dumps)
are device-specific and must stay outside git. The ignore rules in `.gitignore`
cover `incoming/`, `*.raw`, `pandora_shot_*.png`, and `device/<codename>/*`.

Nothing below flashes a partition or changes AVB. The only phone writes are
the two pinned temporary files in `/data/local/tmp` (created only after an
explicit `--yes`) and the kernel log/screenshot files iOS itself writes into
those blocks.

## 1. Board data (read-only on Android)

```bash
bash tools/port/collect_board.sh --device <codename> \
  --adb /path/to/adb
python3 tools/port/discover_ipsw_assets.py /path/to/IPSW \
  --verify-sha256 <official-sha256> \
  -o device/<codename>/ipsw_assets.env
python3 tools/port/gen_byron_config.py \
  --firmware device/<codename>/firmware.json \
  --live device/<codename>/live \
  --manual device/<codename>/manual.json --check --strict
```

Keep `device/<codename>/` local. It is ignored by git because it contains
IMEI/MAC/calibration and runtime values unique to the phone.

## 2. Build the root image on the computer

See [tools/imgbuild/README.md](../tools/imgbuild/README.md). In short:

```bash
sudo env IPSW_DIR=/opt/work/ipsw \
  IPSW_ASSETS=device/<codename>/ipsw_assets.env \
  OUT=/opt/work/iosroot.img \
  bash tools/imgbuild/build_root.sh
```

The resulting `iosroot.img` is local runtime data (`*.img` is ignored).

## 3. Prepare the pinned files on the phone

Build the helper with the generic cross toolchain:

```bash
bash tools/pinfile/build_pinwrite.sh
```

Dry-run first, then write:

```bash
IOS_DEVICE=<codename> IOS_EXTENTS_DIR=device/<codename>/extents \
  ADB_BIN=/path/to/adb \
  bash mac/phone_prepare.sh /opt/work/iosroot.img
IOS_DEVICE=<codename> IOS_EXTENTS_DIR=device/<codename>/extents \
  ADB_BIN=/path/to/adb \
  bash mac/phone_prepare.sh /opt/work/iosroot.img --yes
```

This creates `/data/local/tmp/iosroot.img` (16 GiB) and
`/data/local/tmp/ioslog.img` (8 MiB) as f2fs pinned files, writes the image
into their **physical** blocks (needed because FBE encrypts the filesystem
view), verifies the raw SHA-256 and writes local extents JSON.

If FBE is enabled and you already have pinned files, the equivalent manual
write is:

```bash
adb exec-out su -c \
  'cat /data/local/tmp/iosroot.src.img | /data/local/tmp/pinwrite rawwrite /data/local/tmp/iosroot.img /dev/block/by-name/userdata'
```

Re-collect extents after every rewrite; physical blocks change.

## 4. Build the loader and boot (RAM only)

```bash
KERNEL=/path/to/kernel.development.pandora RD=ufsroot0 CPUS=1 DEBUG=0xc \
  NAME=<run-name> \
  ADTFLAGS="--root-extents device/<codename>/extents/iosroot.json --log-extents device/<codename>/extents/ioslog.json" \
  TRUSTCACHE="/path/to/static.trustcache /path/to/system.trustcache /path/to/app.trustcache" \
  bash wsl/make_phone_payload.sh /path/to/run-dir \
  "ufsrw=1 rootrw=1 launchd_unsecure_cache=1 <other boot args>"

OUT=<run-name> bash shim/loader/build_wsl.sh
adb reboot bootloader
fastboot boot shim/loader/wsl-out/loader-boot.img
```

`launchd_unsecure_cache=1` is required on this SWEET userland: without it
`launchd_cache_loader` tries AMFI validation and exits with
`exit reason namespace 7 subcode 0x21`, panicking init.

## 5. Fetch logs and screenshots after returning to Android

Kernel ring (pinned `ioslog` file, raw read):

```bash
python3 - <<'PY'
import json, subprocess
adb = '/path/to/adb'
j = json.loads(subprocess.check_output(
    [adb, 'exec-out', 'su', '-c',
     '/data/local/tmp/pinwrite extents /data/local/tmp/ioslog.img --json'])
    .decode().splitlines()[0])
parts = ['dd if=/dev/block/by-name/userdata bs=4096 skip=%d count=%d 2>/dev/null'
         % (phys // 4096, length // 4096)
         for _, phys, length, _ in j['extents']]
open('/tmp/ioslog.raw', 'wb').write(subprocess.check_output(
    [adb, 'exec-out', 'su', '-c', '; '.join(parts)]))
PY
python3 tools/pandora_log.py /tmp/ioslog.raw /tmp/ioslog_decoded.txt
```

iOS unified log and in-kernel screenshots from the pinned root image:

```bash
ADB=/path/to/adb python3 tools/ioslog_fetch.py <run-name> --minutes 10 --parse
ADB=/path/to/adb python3 tools/shot_fetch.py /tmp/shots_<run-name>
```

Both need `/data/local/tmp/pinfile` on the phone; `phone_prepare.sh` installs it.
`ioslog_fetch.py` also accepts `IOS_IMG`, `PINFILE`, `WSL_ROOT`, `WSL_DISTRO`,
`WSL_WORK` for non-default setups.

Store all outputs outside the repo. Submit only the interpretation in a
document such as `docs/byron/LIVE_BRINGUP_STATUS.md`.
