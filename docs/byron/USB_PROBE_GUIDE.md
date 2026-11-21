# byron USB CDC ACM 引导期探测 —— 操作指南

> 目的：拿到剩余 5 项必需板级参数 `fb_w / fb_h / fb_stride / fb_format / abl_load_addr`。
> 这 5 项是 ABL 交接那一刻的寄存器/装载地址，正常开机状态只读拿不到（屏幕 DSC 花屏、
> `/dev/mem` 不存在、pstore 写坏，三条通道已证伪）。本方案用 USB 串口回传，是唯一可行路。

## 原理（一句话）

`fastboot boot` 载入一个一次性 RAM 程序（`shim/usbprobe`），它接管 ABL 交接的 USB 控制器，
枚举成 CDC ACM 串口，把探测到的寄存器值**每 3 秒循环重发一次**到电脑（给 Windows 装驱动留时间）。
**不写任何分区**，约 150 秒后 PSCI 自动重启回安卓；长按电源键可随时强制重启。

## 前提

1. 电脑已装 pyserial（已装：`pyserial 3.5`）。
2. 手机能用 `fastboot boot`（BL 已解锁，这是既有状态）。
3. 数据线是**原装/数据线**，能进 fastboot。

## 一次性准备：CDC ACM 驱动（关键）

探测设备 PID/VID = `1209:316D`。Windows 通常认不出，需要先装 usbser 驱动：

1. 下载 Zadig（https://zadig.akeo.ie/）。
2. 手机进 fastboot，**先不要** boot 探测镜像——直接在 fastboot 模式下，`Options → List All Devices`，
   找 `USB\VID_1209&PID_316D`（若此时看不到，跳过这步，boot 后再看）。
3. 更简单：先按下面步骤 boot 探测镜像，此时 Windows 会弹出"未知设备"。打开设备管理器 →
   找到 `Unknown USB Device (Device Descriptor Request Failed)` 或 `VID_1209 PID_316D` →
   右键更新驱动 → 选"USB Serial Device"（usbser.inf）。或用 Zadig 装 WinUSB 后重新识别。
4. 装好后设备管理器出现 `USB Serial Device (COMx)`，记下 COM 号。

> 若 Windows 自动识别，可跳过驱动步骤，直接在捕获脚本里自动查找。

## 操作步骤

在**电脑**上开两个终端：

**终端 A（监听串口）**：
```bash
cd ios-popsicle
python3 tools/port/capture_usb_probe.py --out device/byron/live/usb_probe.txt --wait 200
# 若自动查找失败，指定端口：--port COM12
```
先启动它，它会打印"等待探测设备"。

**终端 B（推送并 boot）**：
```bash
cd ios-popsicle
ADB='/e/刷机工具/RKDevTool_Release_v2.95/bin/adb.exe'
FASTBOOT='/d/软件/搞机助手/fastboot.exe'   # 已验证可用; 另有 /d/软件/搞机工具箱9.70/fastboot.exe

# 1) 手机当前在安卓，重启进 fastboot
"$ADB" reboot bootloader
# 等待手机进入 fastboot 画面

# 2) 一次性从 RAM 启动探测镜像（绝不 fastboot flash）
"$FASTBOOT" boot shim/usbprobe/out/usbprobe-boot.img
```

boot 后：探测程序枚举成串口 →（每 3 秒重发一次完整帧）→ 终端 A 捕获数据 → 打印解析结果 → 手机约 150 秒后自动重启回安卓。
> 首次若 Windows 认不出设备，用 Zadig 装好驱动后**不用重新 boot**——程序在重启前一直循环重发，捕获脚本会自动读到。

## 预期输出

终端 A 应看到类似：
```
===BYRON_USB_PROBE_BEGIN===
MAGIC=BYRUSB1
EL=1
GCTL=0x00102005 DCTL=0x00000000 DSTS=0x00003a20
PHYCFG=0x00000400 VBUS=0x00100000 HWP0=0x...
LOAD=0x000000009fc00000
MMFR0=0x0000000000001021
PAGES16K=YES
FB=0x00000000fc800000 W=1200 H=2608
STRIDE=4800 FMT=0x... PIPE=...
P0=...,...
===BYRON_USB_PROBE_END===
```
并把 5 项写进 `device/byron/live/usb_probe.txt`。

## 若 USB 没起来（串口无数据）

探测程序在 `dwc3_init` 失败时会把失败码和自检值写进 ramoops 尾部。重启回安卓后读：
```bash
"$ADB" shell 'cat /sys/fs/pstore/console-ramoops* 2>/dev/null | grep -A8 BYRON_USB_FAIL'
```
会看到 `RC=`、`SNPSID=`、`GCTL=`、`DSTS=`、`VBUS=` 等诊断行，据此判断卡在哪一步
（SNPSID 应为 `0x33313130`；若全 0 说明基址/时钟问题；GCTL 应显示 device role）。

## 安全说明

- 全程 `fastboot boot`（RAM），**不** `fastboot flash`，不写任何分区。
- 探测程序只读 SSPP 子块寄存器（安全）；不改 GCC/SMMU 全局状态（只做幂等的 PHY/VBUS 位设置，重启即失效）。
- 唯一副作用：接管 USB 控制器约 150 秒，期间 fastboot/adb 断开，属预期。
- 冷启动或长按电源后一切恢复原状。
