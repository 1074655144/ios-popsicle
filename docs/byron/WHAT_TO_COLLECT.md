# byron（小米 17 Max）需要手机提供什么

> 更新 2026-11-20：用户已提供**完整 9008 字库备份**（`<local firmware dump>/`，164 个分区镜像，5.0 GB）。
> 已从字库提取出大量板级事实，**缺口从 21 项降到 19 项**，且这 19 项里大部分仍需真机只读采集。
> 依据 `device/byron/firmware.json`（真实 diff）+ `device/byron/stock_dump.json`（字库提取）。

## 字库备份带来的变化（重要）

已验证：`boot_a` / `vendor_boot_a` / `dtbo_a` 与 OTA `OS4.0.4.0.XAFCNXM` **哈希完全一致**（dtbo 按去零有效区比对），确认字库就是这台机器、这个构建。之前所有 OTA diff 结论成立。

**已从字库直接拿到、无需再采集**（`tools/port/extract_stock_dump.py` 自动提取）：

| 参数 | 真机值 | 来源 |
|---|---|---|
| `battery_gauge` | `ti,bq27z561_master` | dtbo DTB 的 `bq27z561_standlone@55` |
| `charger_ic` | `smb1501`（PPS 充电 PMIC） | dtbo DTB 的 `smb1501@68` |
| `wifi_chip` | `qcom,wcn786x` | dtbo DTB 的 `wcn786x` 节点 |
| 触摸主控 | `synaptics,tcm-spi` | dtbo DTB（与 OTA 一致） |
| 功放 | `tfa98xx_1@34` + 双通道校准 | dtbo DTB + persist/audio/tfa_calr.txt |
| 面板 ID | `000021000000046e` / cell `AFG564N0ARA41` | persist/display/（demura + cell_id） |
| Wi-Fi MAC | device-specific, local only | persist/wlan/wlan_mac.bin |

> 注意：popsicle 的功放是 CS35L43，byron 是 **tfa98xx**——这是必须改驱动的新差异。

---

## 前提（三样缺一不可）

1. **手机已 root**（采集脚本每条命令走 `su -c`）；本机实测 `adb shell id` 已为 root。
2. **开启 USB 调试**，`adb devices` 能看到手机。
3. **从现在起不再做额外解锁、刷机或改分区**。要拿到 root 通常已经解过 BL，这是既有状态；本次采集全程只读，不改变锁状态。

---

## 第一类：真机只读采集 —— 已完成（2026-11-20）

```bash
cd ios-popsicle
bash tools/port/collect_board.sh --device byron \
  --adb '/e/刷机工具/RKDevTool_Release_v2.95/bin/adb.exe'
```

脚本**只读**：手机侧只有 `getprop / cat / dd if= / ls / find / readlink` 等读取；
`dmsetup` 在本机 MIUI 上不存在，工具改为从 `/sys/firmware/fdt` 和 `/sys/block/dm-*`
读取同样的信息。所有输出写到电脑 `device/byron/live/`，不写手机任何分区。
触摸窗口的中断名已确认主屏触摸为 `msmgpio 158 / xiaomi_tpsynaptics_tcm`
（计数未跳变不影响归属判断）。

本次采集结果：25 个文件 / 1.6 MB，已解析 7 项：

| 参数 | 来源文件 | 结果 |
|---|---|---|
| `memory_banks` | `fdt.dtb`（`/sys/firmware/fdt`） | ✅ 21 段真实 RAM 窗口，不再是 `<0 0>` |
| `splash_size` | `fdt.dtb` | ✅ `0x2b00000`（base `0xfc800000`） |
| `phys_base` / `dsp_shm` | `fdt.dtb` + 人工判断 | ❌ 仍需选定干净内存块，不能靠脚本猜 |
| `touch_irq_gpio` | `interrupts_1/2.txt` | ✅ `158` |
| `thermal_table` | `thermal.txt` | ✅ 已采集，待人工审阅阈值 |
| `userdata_dev` / `userdata_lba` | `by_name.txt` + `gpt.bin` + `userdata_sector.txt` | ✅ `sda34`，`30380032..1029136343` |
| `firmware_files` | `firmware_list.txt` | ✅ 已采集 `/vendor/firmware_mnt` 清单 |

---

## 第二类：手机能提供的构建产物（2 项）

1. **`stock_boot_b_sha256`** ✅ 已只读取得：
   `cat /dev/block/by-name/boot_b` 流到电脑计算，手机端与电脑端 SHA-256 均为
   `6f148a7a...cb3`，100663296 字节，已写入 `backup/manifest.txt`。
2. **`pinned_extents`** ❌ 仍未做：需要 `mac/phone_prepare.sh` 在 `/data` 建三个临时镜像，
   属于写手机操作。按本次“只读”约束**刻意跳过**，不能伪造。

---

## 第三类：正常开机也给不了（7 项）—— 引导阶段探测

`fb_w` / `fb_h` / `fb_stride` / `fb_format`、`page_size_16k`、`abl_load_addr`、`tlmm_base_real`（真值 `0x0f100000`，DT 写的 `0x0f000000` 是错的）。

字库的 `ddr.img` / `cdt.img` 是二进制训练数据，**不含**这些运行时寄存器值——静态字库无法替代。我会做只读探测包，`fastboot boot` 一次即可，不写分区。这包还没构建（需 Mac + XNU 工具链），**现在不用你准备**。

---

## 当前状态与下一步

- 真机只读采集已完成：`device/byron/live/`（25 文件），配置已写回
  `profiles/byron.env`、`device/byron/adt_overrides.json`、`docs/byron/PORT_CHECKLIST.md`。
- 完成度：**36/42 required**，`BOARD_DATA_COMPLETE=no`，`safe_boot.sh --commit` 仍被拒绝。
- 剩余 6 项：`fb_w`/`fb_h`/`fb_stride`/`fb_format`、`abl_load_addr`（5 项需 SSPP/引导期寄存器）、
  `pinned_extents`（需重建 pinned 文件并重采）。
- 即使 42 项齐全，仍只是 `data_ready`；只有真机启动验证后显式 `--attest` 才可能变 `yes`。

## 剩余 6 项的读取方法（2026-11-21）

关键结论：原以为 10 项必须引导探测，实际从**已有真机数据**又挖出 4 项，无需再动手机：

| 参数 | 方法 | 状态 |
|---|---|---|
| `phys_base` | live FDT `/memory` 有精确 5 GiB 空块 `0x8c0000000..0x9ffffffff`，无 reserved 覆盖 | ✅ 已填 `0x8c0000000` |
| `dsp_shm` | live FDT 32-bit 空块 `0xa6980000..0xc3dd0000`，`0xb0000000` 落其中 | ✅ 已填 `0xb0000000` |
| `brightness_dcs` | live FDT 面板节点 `qcom,mdss-dsi-hbm-on-command` 含 `51 34 bc` → DCS 0x51 16-bit | ✅ 已填 |
| `page_size_16k` | Cortex-X925 (ARMv9.2) 架构强制支持 TGran16 | ✅ 已填（标 unverified） |
| `tlmm_base_real` | 同 SoC 平台常量 | ✅ 已填（标 unverified） |

真正还需要新数据的 6 项，按获取难度排序：

1. **`pinned_extents`** — 唯一方法：真机重建三个 f2fs pinned 文件（`/data`，16 GiB+8 MiB×2），
   读 FIEMAP 后**保持文件不删**。`tools/pinfile/pinprobe.c` 已备好、已验证可用。需你明确授权写 `/data`。
2. **`fb_w`/`fb_h`/`fb_stride`/`fb_format`** — ~~必须读 SSPP 源寄存器 / 走 USB 探测~~。
   **2026-11-21 更新**：USB 探测真机试验失败（设备从未枚举，`dwc3_init` 在 byron 失败），
   四条回传通道全部证伪。但已从**正常安卓只读 debugfs** 拿到实证数据：
   `fb370 = 1216×2608 / AB24(BGRA8888,0x34324241) / pitch 4864`，`splash_region @ 0xfc800000 size 0x2b00000`。
   详见 `USB_PROBE_RESULT.md`，脚本 `tools/port/collect_live_framebuffer.py`，
   证据 `device/byron/live/live_framebuffer.json`。仅 `fb_w` 1216 vs 1200 与 format 字节序待真机启动确认。
3. **`abl_load_addr`** — 探测程序 `start.S` 用 `adr` 自定位（position-independent），
   此值对 loader 可能非硬依赖；是唯一没有替代数据源的项。

**诚实边界**：以上 4 项推导值（phys_base/dsp_shm/brightness_dcs/page_size_16k）
来自真机 FDT 和架构资料，比"同 SoC 猜测"可靠，但**未经引导期寄存器独立验证**。
它们已写入配置并标注 `derived:*`；闸门仍 `no`，不会因此触发真机启动。

## 复现字库提取

```bash
python3 tools/port/extract_stock_dump.py \
    --dump "<local firmware dump>" --device byron
# → device/byron/stock_dump.json（被 .gitignore 忽略，不提交）

python3 tools/port/gen_byron_config.py \
    --firmware device/byron/firmware.json \
    --stock-dump device/byron/stock_dump.json \
    --check
```

## 引导期探测尝试（2026-11-20 晚，结论：byron 上屏幕/内存回传通道不可用）

用 `fastboot boot shim/hello/out/hello-boot.img` 做了真实引导探测（纯 RAM、不写分区）。
探测程序工作正常（能启动、读寄存器、12 秒后 PSCI 重启回安卓），但**结果无法回传到电脑**：

| 通道 | 结果 | 根因 |
|---|---|---|
| 屏幕显示大字 | ❌ 全屏雪花 | 面板 `qcom,mdss_dsi_byron_42_0d_0a_dsc_cmd` 是 **DSC 压缩 + command mode**（`qcom,mdss-dsi-bpp=0x18`、`dsc-bit-per-pixel=0x8`），framebuffer 存的是压缩流，按 ARGB8888 写像素必然花屏。上游 popsicle 的非压缩屏幕可直写，byron 不行。 |
| `/dev/mem` + `devmem` | ❌ 节点不存在 | 高通强化内核未编译 `/dev/mem`；`devmem` 工具在但打不开。 |
| pstore / ramoops (`0xff400000`) | ❌ 导出失败 | 探测写入的裸 ASCII 破坏了 ramoops console 记录结构，重启后 `/sys/fs/pstore/` 为空。 |

探测程序源码 `tools/../shim/hello/hello.c` 已加过多版回传逻辑（大字 / splash 尾部二进制 / ramoops ASCII）；
镜像编译命令（本机无 NDK，用 WSL 交叉工具链）：

```bash
# WSL 内，无 libc、裸 syscall 风格，禁 ABS64 重定位（Image 加载到任意地址）
aarch64-linux-gnu-gcc -O2 -ffreestanding -fno-builtin -nostdlib -fno-pic \
  -fno-stack-protector -mgeneral-regs-only -mstrict-align -Wall -Wextra \
  -c start.S -o out/start.o
aarch64-linux-gnu-gcc ... -c hello.c -o out/hello.o
aarch64-linux-gnu-ld -T hello.ld --build-id=none out/start.o out/hello.o -o out/hello.elf
aarch64-linux-gnu-objcopy -O binary out/hello.elf out/Image
python3 ../../tools/mkbootimg_v4.py out/Image out/hello-boot.img
```

**下一步若要真拿这 6 项**：唯一可行的是移植 `wsl/qcomusb/usb/Dwc3.c`（自包含、647 行、回调式 IO）
到裸机，让探测程序用 CDC ACM 把寄存器值发到电脑 COM 口。上游实测 `fastboot boot`
后 USB 处于 device mode、时钟开、halted（`wsl/qcomusb/README.md`），可直接接管。
工作量大、首次成功率不确定，需用户显式选择才做。

**当前采取的策略（更新 2026-11-21）**：改为 USB CDC ACM 回传探测。
屏幕/pstore/devmem 三条通道已证伪，唯一可行的是移植 `wsl/qcomusb/usb/Dwc3.c` 到裸机
探测程序，用 CDC ACM 把寄存器值发到电脑串口。已完成：

- `shim/usbprobe/`：裸机 USB 探测程序，DWC3 核心原样复用（`Dwc3.c` 纯 C、无 libc），
  只写 platform 回调；DMA 物理地址直通；幂等 PHY/VBUS 准备。
- 硬件前提实证：byron FDT 的 `ssusb@a600000`/`dwc3@a600000`/SMMU stream 0x40 与 pandora
  的 `Sm8850.h` 完全一致，寄存器常量可直接复用。
- `shim/usbprobe/out/usbprobe-boot.img`：已编译（WSL `aarch64-linux-gnu-gcc`），无 ABS64 重定位。
- `tools/port/capture_usb_probe.py`：电脑端捕获+解析（pyserial 3.5 已装）。
- 操作指南：`docs/byron/USB_PROBE_GUIDE.md`。

一次 `fastboot boot` 即可拿到剩余 5 项（`LOAD`/`W`/`H`/`STRIDE`/`FMT`）+ USB 交接自检。
**尚未执行**：需用户在真机上 boot 并抓串口。完成度仍 **37/42**，`BOARD_DATA_COMPLETE=no`。

## 安全与许可

- 采集脚本零写入、不额外解锁 BL 或改锁状态（设备当前 root/解锁状态是既有事实）；`phone_prepare.sh` 只在 `/data` 建临时文件；
- 字库备份含 IMEI/MAC/校准等**设备唯一数据**，不要公开上传或提交（`device/*` 已被忽略）；
- 这是研究性移植，蜂窝/Apple ID/App Store 不可用，iOS 许可不允许在非苹果硬件上商用。
