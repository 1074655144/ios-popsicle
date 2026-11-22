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

Below is the status of the Xiaomi 17 Max (`byron`) real device. The component names follow the original author's wording. Progress percentages and status colors are adjusted to what has actually been done on byron: 🟢 works · 🟡 partly works · 🟠 in progress · ⚪ not started. A note of **还没有做** means the item has not been done on byron. See **[docs/byron/LIVE_BRINGUP_STATUS.md](docs/byron/LIVE_BRINGUP_STATUS.md)** for the current RAM-boot evidence, **[docs/byron/OTHER_DEVICES_FINDINGS.md](docs/byron/OTHER_DEVICES_FINDINGS.md)** for the other-device comparison, and **[docs/byron/PHASE_CLOSEOUT.md](docs/byron/PHASE_CLOSEOUT.md)** for the earlier phase closeout.

Reusable per-phone capture/build/log steps are in **[docs/PHONE_DATA_CAPTURE.md](docs/PHONE_DATA_CAPTURE.md)**. Real-time phone data (extents, logs, screenshots, images) is intentionally not committed.

### System

| Component | Progress | Status | Notes |
|---|---|---|---|
| Boot, lock screen, home screen, built-in apps | `██░░░░░░░░` 20% | 🟠 | RAM 启动到白苹果；SpringBoard 重启循环 6 次、无 screen owner；锁屏/桌面/内置应用还没有做。GPU 已证伪非原因（有无 GPU 白苹果同构） |
| Touch, power and volume buttons, brightness | `██░░░░░░░░` 20% | 🟡 | 内核 HID 触摸/按键注入已通（autoswipe 上滑 104 次实证）；用户态触摸客户端还没有做 |
| Display and GPU (Adreno 840, Metal) | `██████░░░░` 60% | 🟡 | framebuffer/背光 + GPU/Metal 链路已打通（IOServiceOpen=0x0、pipeline/shader 真实渲染，fix14/15）；白苹果与 GPU 无关，桌面呈现还没有做 |
| CPU (8 cores, frequency scaling, idle) | `██░░░░░░░░` 20% | 🟡 | 内核已在 byron 启动；调频/空闲还没有做 |
| Battery gauge and charging | `░░░░░░░░░░` 0% | ⚪ | 还没有做 |
| Thermal management | `░░░░░░░░░░` 0% | ⚪ | 还没有做 |
| App Store apps | `░░░░░░░░░░` 0% | ⚪ | 还没有做 |

### Connectivity

| Component | Progress | Status | Notes |
|---|---|---|---|
| Wi-Fi: chip and firmware (WCN7880) | `░░░░░░░░░░` 0% | ⚪ | 还没有做 |
| Wi-Fi: scan | `░░░░░░░░░░` 0% | ⚪ | 还没有做 |
| Wi-Fi: connection and data | `░░░░░░░░░░` 0% | ⚪ | 还没有做 |
| Wi-Fi: Settings panel and status icon | `░░░░░░░░░░` 0% | ⚪ | 还没有做 |
| Modem firmware | `░░░░░░░░░░` 0% | ⚪ | 还没有做 |
| 4G/5G, calls, SMS, SIM | `░░░░░░░░░░` 0% | ⚪ | 还没有做 |
| Bluetooth | `░░░░░░░░░░` 0% | ⚪ | 还没有做 |
| USB | `░░░░░░░░░░` 0% | ⚪ | 还没有做 |
| NFC, GPS | `░░░░░░░░░░` 0% | ⚪ | 还没有做 |

### Media and sensors

| Component | Progress | Status | Notes |
|---|---|---|---|
| Speakers | `░░░░░░░░░░` 0% | ⚪ | 还没有做 |
| Microphones, earpiece | `░░░░░░░░░░` 0% | ⚪ | 还没有做 |
| Vibration motor | `░░░░░░░░░░` 0% | ⚪ | 还没有做 |
| Cameras | `░░░░░░░░░░` 0% | ⚪ | 还没有做 |
| Motion and light sensors | `░░░░░░░░░░` 0% | ⚪ | 还没有做 |
| Fingerprint reader | `░░░░░░░░░░` 0% | ⚪ | 还没有做 |
| Rear display | `░░░░░░░░░░` 0% | ⚪ | 还没有做 |

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
