# Building

> **适配机型 / Target device**：本仓库唯一目标为 **小米17 Max（`byron`）**。小米17 系列有多款后缀型号（小米17 / 17 Pro / 17 Pro Max / 17 Max），本文只针对小米17 Max。
> **来源 / Upstream**：fork 自 [OctoDevStudios/ios-popsicle](https://github.com/OctoDevStudios/ios-popsicle)（原适配小米17 Pro Max / `popsicle`）。下文出现的 `popsicle` / `PANDORA`  machine config 名称是上游遗留的技术标识，不代表适配机型已改变。

Requirements: a **Xiaomi 17 Max (`byron`)** with an unlocked bootloader and root under Android, a Mac (or a GitHub Actions fork — see `docs/byron/CI_KERNEL_BUILD.md`) with `adb` and `fastboot`, and your own **iPhone X iOS 16.7.16 (20H392) IPSW** — `iPhone10,3,iPhone10,6_16.7.16_20H392_Restore.ipsw`, SHA256 `ece1194f7e233e9109c5790a8d23a4564a10a254e15ec5b09978a343265568fb`. None of Apple's, Qualcomm's or Xiaomi's files are distributed here.

> **Target iOS version — 16.7.16 (20H392), the project-native build.** The user briefly chose 16.5 on 2026-11-21 but reverted: 16.5's cryptex/trustcache layout uses different build numbers (`096-xxx-xxx`) and is not covered by the project's tested flow. 16.7.16's IPSW has been verified locally against the official SHA256 and is still signed by Apple. To regenerate the build-specific asset names from your IPSW, run `python3 -I tools/port/discover_ipsw_assets.py <your.ipsw> --verify-sha256 ece1194f... -o device/byron/ipsw_assets.env` (it reads `BuildManifest.plist`); all build scripts source that file, falling back to the 16.7.16 names with a warning if absent. Target build is also recorded in `profiles/byron.env`.

## 1. Kernel

Run `.github/workflows/xnu.yml` on your fork with `machine_config=PANDORA`. It builds xnu-8796 with `xnu/patches/` applied in order and needs `xnu/vendor/nw_all.o` (step 2) for the Wi-Fi driver. Its artifacts `xnu-kernel`, `xnu-objects` and `xnu-buildtree` allow local relinks.

Once you have those artifacts, you can rebuild on an Apple Silicon Mac. Install Xcode 15.0.1 as `/Applications/Xcode_15.0.1.app` and accept its license: the scripts use it through `DEVELOPER_DIR`, and with the same Wi-Fi object the result matches the CI kernel's code and data byte for byte. Unpack them into a work folder, with `ci.log` from the run, the objects in `obj/` and `linklibs/`, and the build tree in `bt/`. Then:

```bash
python3 -I mac/kernel_cc.py WORK OUT bsd/dev/pandora_wlan.c
```

```bash
python3 -I mac/relink_kernel.py WORK xnu/vendor/nw_all.o KERNEL_OUT --overlay OUT
```

Use `--all` to recompile every file it has a command for. On an 8-core M1, `--all` takes about 75 seconds. Edit the sources in `WORK/bt/xnu`, keep your changes as patches in `xnu/patches/`, and regenerate through CI if you change `.iig`, `.defs` or headers used everywhere.

## 2. Wi-Fi driver

The driver is [Ath12kWifi](https://github.com/UniXNU/Ath12kWifi) (Linux ath12k, mac80211, cfg80211, MHI and QRTR on XNU), adapted for the WCN7880 "peach" chip:

1. Prepare the Ath12kWifi tree and apply `tools/wlan/ath12kwifi-local.diff`.
2. Copy the `peach` firmware directory from your phone (`/vendor/firmware_mnt/image/peach/`). This stays on your machine.
3. Run `tools/wlan/peach.py`, then `tools/wlan/peach2.py`. Paths at the top of these scripts assume `~/17pm-work`.
4. Run `tools/wlan/build_nw.py`, link the objects with `ld -r`, and copy the result to `xnu/vendor/nw_all.o`.

To replace only the driver in an existing kernel, without rebuilding xnu: `mac/relink_kernel.py`.

## 3. Prepare the phone (Android)

`mac/phone_prepare.sh` creates the pinned files that hold the iOS root and the log, and records where they are on storage. `tools/pinfile` is the helper that runs on the phone. `mac/gpu_pack.sh` and `mac/gpu_phone.sh` build and install the GPU pack.

## 4. Boot (RAM only)

```bash
GPU=1 AUDIO=1 WIFI=2 MODEM=1 bash mac/boot_ios.sh KERNEL SECONDS "pandora_usb=2 qcom-usb-debug=1"
```

The kernel is loaded with `fastboot boot`, then the phone returns to Android after `SECONDS`. Hold Power + Volume Down for 10 seconds to force a restart.

`mac/live.py` reads the kernel log over USB and can order the restart when a log line appears. `mac/test_kernel.sh` and `mac/wifi_cycle.sh` chain all of this for tests, and `mac/log_summary.sh` summarises a run.

The boot line is limited to 607 characters.
