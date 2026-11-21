<div align="center">

# iOS on the Xiaomi 17 Max（小米17 Max）

**iOS 16.7.16 running natively on Snapdragon 8 Elite Gen 5 hardware, booted from RAM.**

![Device](https://img.shields.io/badge/device-byron-111111?style=for-the-badge)
![SoC](https://img.shields.io/badge/SoC-SM8850-3253DC?style=for-the-badge)
![Kernel](https://img.shields.io/badge/kernel-xnu--8796-555555?style=for-the-badge)
![Status](https://img.shields.io/badge/status-experimental-E5A00D?style=for-the-badge)

</div>

> [!IMPORTANT]
> **本仓库适配的目标机型只有一个：小米17 Max（`byron`，SM8850-AC / 骁龙 8 Elite Gen 5）。**

> [!NOTE]
> **来源 / Upstream**：本项目 fork 自 **[OctoDevStudios/ios-popsicle](https://github.com/OctoDevStudios/ios-popsicle)**，
> 原项目适配的是小米17 Pro Max（`popsicle`）。本 fork 在其基础上改适配到小米17 Max（`byron`）。
> 完整致谢见下方 [Credits](#credits)。

> [!WARNING]
> Research project, not a daily driver. You can lose data or damage your phone, and you are responsible for what you run. Back up everything first.

## What this is

A self-built XNU kernel with native drivers for the **Xiaomi 17 Max (`byron`)**, running the unmodified userland of an iPhone X. There is no emulator and no virtual machine: iOS talks to the hardware through drivers compiled into the kernel.

Normal testing writes nothing to the phone's partitions. The kernel starts with `fastboot boot`, lives in RAM, and a restart returns to Android.

## Status

This section describes **only the Xiaomi 17 Max (`byron`) fork**. The percentages in the upstream README are the original author's estimates for the Xiaomi 17 Pro Max (`popsicle`); they are not measurements and are intentionally **not reproduced here**. See **[docs/byron/LIVE_BRINGUP_STATUS.md](docs/byron/LIVE_BRINGUP_STATUS.md)** for the current RAM-boot evidence and **[docs/byron/PHASE_CLOSEOUT.md](docs/byron/PHASE_CLOSEOUT.md)** for the earlier phase closeout.

Reusable per-phone capture/build/log steps are in **[docs/PHONE_DATA_CAPTURE.md](docs/PHONE_DATA_CAPTURE.md)**. Real-time phone data (extents, logs, screenshots, images) is intentionally not committed.

**Legend:** 🟢 verified on byron · 🟡 partially verified on byron · 🟠 current bring-up work / blocker · ⚪ not started or not verified on byron

### Boot chain actually reached on byron

| Component | Byron status | Notes |
|---|---|---|
| RAM boot (`fastboot boot`) | 🟢 | XNU boots from RAM; no partition write, no AVB change |
| Root filesystem | 🟢 | 16 GiB non-journaled HFS+ root built from an iPhone X IPSW; binary-plist keybag fixed; root mounted |
| Early userspace | 🟢 | `launchd` exec succeeds; dyld shared cache mapped; `launchd_unsecure_cache=1` gets past the AMFI cache-loader failure |
| Display / framebuffer | 🟡 | Correct stride 4800; black background with white Apple Logo and backlight confirmed; no desktop UI yet |
| `SpringBoard` / `backboardd` | 🟡 | Both processes exec; fix7 logs show CPU compositing and backlight on, then stop at the Apple Logo |
| Lock screen / home screen / built-in apps | 🟠 | Not reached; fix8 screen/log result is still pending |
| GPU / Metal (Adreno 840) | 🟠 | fix7 logs never found `IOAcceleratorES / AGXAccelerator`; GPU path is not enabled yet |
| CPU cores / frequency scaling / idle | 🟡 | Kernel runs on byron; core count, DVFS and idle behaviour are not characterized yet |
| Touch, buttons, brightness control | ⚪ | Not verified beyond the Apple Logo stage |
| Battery gauge, charging, thermal model | ⚪ | Not verified on byron |
| App Store apps | ⚪ | Not reached; no claim is made here |

### Connectivity, media and sensors

| Component | Byron status | Notes |
|---|---|---|
| Wi-Fi chip / firmware (WCN7880) | ⚪ | Not enabled in the current boot path; upstream Wi-Fi progress does not apply |
| Wi-Fi scan / connection / data | ⚪ | Not tested on byron |
| Wi-Fi settings panel and status icon | ⚪ | UI not reached |
| Modem firmware | ⚪ | Not started on byron |
| 4G/5G, calls, SMS, SIM | ⚪ | Not connected to iOS |
| Bluetooth | ⚪ | Not verified; fix8 explicitly excludes `bluetoothd` and `fairplayd.H2` |
| USB | ⚪ | Android-side ADB is only used to capture pinned logs; iOS USB is not verified |
| NFC, GPS | ⚪ | Not started |
| Speakers | ⚪ | ADSP / CS35L43 path exists but is not exercised on byron yet |
| Microphones, earpiece, vibration motor | ⚪ | Not started |
| Cameras | ⚪ | Not started; iOS normally expects Apple's ISP |
| Motion/light sensors, fingerprint, rear display | ⚪ | Not started |

## Getting started

Nothing here is a ready-to-flash image. You build the kernel and the root filesystem yourself, from your own files. See **[BUILDING.md](BUILDING.md)**.

You need a **Xiaomi 17 Max (`byron`)** with an unlocked bootloader and root, a Mac (or a GitHub Actions fork — see **[docs/byron/CI_KERNEL_BUILD.md](docs/byron/CI_KERNEL_BUILD.md)**), and your own iPhone X IPSW.

## What's in the repo

| Path | Contents |
|---|---|
| `xnu/patches/` | Patches for xnu-8796, applied in order |
| `wsl/` | Drivers compiled into the kernel: GPU, display, touch, audio, storage, battery and more |
| `mac/` | Boot, live log, relink and test tools for macOS |
| `tools/` | Boot image, device tree, trust cache and firmware tools, GPU tests, Wi-Fi driver adaptation |
| `shim/` | The small loader started by `fastboot boot` |
| `bootmgr/` | Optional boot menu. **It writes to the `boot_b` partition**, read its README first |
| `docs/`, `device/` | Technical notes (in Chinese and English) |

## Not included

- Apple's iOS system files (IPSW, shared cache, SDK)
- Qualcomm and Xiaomi firmware
- Partition backups, logs and anything else read from a phone

Firmware is read from your own phone at run time, and modem writes never leave RAM.

## Credits

Built on the work of others:

- **[OctoDevStudios/ios-popsicle](https://github.com/OctoDevStudios/ios-popsicle)** — **本仓库的直接上游 / the repository this fork is based on**. 原仓库适配 Xiaomi 17 Pro Max (`popsicle`)；本 fork 改适配 Xiaomi 17 Max (`byron`).
- **[Data A Live](https://github.com/ShueiTsuki/data-a-live)** by ShueiTsuki: the Xiaomi 17 Pro port the upstream project continues. Kernel drivers, GPU work and most of the tooling come from it.
- **[ios-sweet](https://github.com/dipa-studio/ios-sweet)** and **[ios-fuxi](https://github.com/bangprovn/ios-fuxi)**: the approach and the early kernel patches.
- **[UniXNU](https://github.com/UniXNU/UniXNU)**: 4K-page kernel, storage driver, NativeAdreno, NativeMetal, ArmSmmu4K, Ath12kWifi and Qualcomm components.
- **[Mesa](https://gitlab.freedesktop.org/mesa/mesa)** (Turnip) and **[metal2vulkan](https://github.com/steelbrain/metal2vulkan)**.
- The Linux kernel's Qualcomm drivers, including ath12k.

## License

Kernel patches and kernel drivers: APSL 2.0. Other code and documentation: MIT. Third-party files keep their own licenses. Full terms in [LICENSE](LICENSE).

Not affiliated with Apple, Xiaomi or Qualcomm. All trademarks belong to their owners.
