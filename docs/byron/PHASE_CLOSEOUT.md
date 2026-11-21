# byron 移植阶段性封存报告

> ## ⚠️ 2026-11-21 14:57 重大修正——下方"UBWC 架构级障碍"结论已被推翻
>
> 封存后继续真机验证，**花屏根因已查明并解决**：是 `fb_stride` 写成 4864 所致（每行多 16 像素
> 逐行累积成斜纹/棋盘），真值为 **1200/4800**（popsicle 原值）。stridescan 四带照片 +
> 改参后 fbverify 真机照片双重实证（详见 `FB_VERIFY_GUIDE.md` 顶部 + 工作日志 2026-11-21.md）。
> 字节序 = ARGB 0xAARRGGBB（loader.c 本来就对）。
>
> 因此本报告第 1 节、第 5 节、第 5.3 节中"UBWC/DSC 架构级不兼容、参数微调无效、只能编程 MDP/SSPP"
> 等表述**全部作废**。显示路径障碍已解除；剩余工作回到正轨：用 1200/4800 重编带 XNU payload 的
> loader 镜像并推进启动。安全闸门 `BOARD_DATA_COMPLETE=no` 仍保持（与显示参数无关，是另外 5 项板级参数）。
>
> 以下为历史封存记录，供追溯判断演变，勿作为当前结论引用。

> 日期：2026-11-21
> 目标机型：小米 17 Max（`byron`，SM8850-AC / 骁龙 8 Elite Gen 5）
> 上游：`OctoDevStudios/ios-popsicle`（原适配小米 17 Pro Max `popsicle`）
> 状态：**阶段性封存**。研究性成果已固化，未达成真机启动 XNU，安全闸门保持 locked。

---

## 1. 一句话结论

板级参数采集完成 **37/42**，官方 OTA + 原装字库 + 真机 root 三方交叉验证的数据已全部落盘；
剩余 5 项（framebuffer 四参数 + ABL 装载地址）的获取路径经四类回传通道实测后证伪，
并在最后一次真机验证中发现 **byron 的显示链路是 UBWC 压缩 + DSC command-mode**，
与 popsicle 的线性直写架构不兼容——这是比"缺参数"更前置的**架构级障碍**。
据此封存，不再继续真机试探。

---

## 2. 安全边界（全程遵守）

- 手机 BL 本就已解锁、已有 root（KSU）——这是用户既有状态，非本项目所为。
- 本项目**从未**再解锁、**从未** flash 任何分区、**从未**写系统分区、**从未**动 AVB/vbmeta。
- 唯一写操作是用户明确授权的 `pinned_extents` 临时文件（`/data/local/tmp/`，16 GiB，已保留）。
- 所有真机启动均为 `fastboot boot`（纯 RAM，掉电即恢复），最长 25–150 秒自动重启回安卓。
- 备份：`backup/manifest.txt` 记录 `boot_b` SHA-256 `6f148a7a…d1cb3`，操作前后一致。
- 安全闸门 `BOARD_DATA_COMPLETE=no`，`safe_boot.sh --commit` 全程拒绝真实启动。

---

## 3. 已完成的工作（按阶段）

### 3.1 调研与方案
- 调研开源社区（HackiOS/XNU、UniXNU、touchHLE、Project Sandcastle），定位 SM8850 社区分支。
- 明确 `popsicle`（17 Pro Max）与 `byron`（17 Max）是两款不同机型，全程锁定 byron。
- 设计 DSU 式安全边界：DSU 不能替换 XNU 内核，改为「RAM Boot + dry-run + 备份校验 + 超时回安卓」。

### 3.2 固件分析（离线，零手机风险）
- 官方 OTA `byron-ota_full-OS4.0.4.0.XAFCNXM`（8.81 GiB, ZIP64）通过 HTTP Range 断点取包解析。
- `payload.bin` → 提取并解析真实 DTB / DTBO；字库备份与 OTA 哈希交叉验证一致。
- 产出：`FIRMWARE_DIFF.md`、`FIRMWARE_PROVENANCE.md`、`device/byron/firmware.json`。

### 3.3 板级参数采集（37/42）
- 三类来源交叉验证：firmware（OTA/DTB）、live（真机只读 sysfs/debugfs/FDT）、manual（同 SoC 推导）。
- 关键板级值：`phys_base=0x8c0000000`、`tlmm_base_real=0x0f100000`、`dsp_shm=0xb0000000`、
  `ufs_base=0x1d84000`、触摸 IRQ158/reset66、电池 gauge `bq27z561`、Wi-Fi `wcn786x`、无副屏。
- 工具链：`tools/port/analyze_firmware.py`、`gen_byron_config.py`、`collect_board.sh`、
  `board_overlay.py`、`mkadt_pandora.py`、`collect_live_framebuffer.py`。

### 3.4 真机只读采集
- 原装字库备份提取校准/硬件数据；确认 `byron / 2605EPN8EC`、当前槽位 `_a`。
- 从 FDT（须用 `adb exec-out`，`adb shell cat` 会破坏二进制）确认：
  `splash_region = 0xfc800000 / 0x2b00000`，与 loader 基址一致。
- 从非标准 debugfs 路径 `/dev/okqaeuzc/wz_rmhpt` 读到 DRM framebuffer 实证。
- `pinned_extents`：arm64 裸机 `pinprobe`（裸 syscall + FIEMAP），三个文件 iosroot(16GiB/2008 extents)、
  ioslog(8MiB)、adspfw(8MiB) 已 pin 并保留，JSON 校验通过。

### 3.5 安全启动脚本
- `tools/safe_boot.sh` / `safe_recover.sh`：默认 dry-run，`--commit` 需 12 项运行时检查 + `--attest`。
- 核心回归 `tools/tests/test_safe_boot.sh`：**45/0 全绿**。

---

## 4. 剩余 5 项与为什么拿不到

| 项 | 状态 | 说明 |
|---|---|---|
| `fb_w` / `fb_h` / `fb_stride` / `fb_format` | 有候选值但未定稿 | 见第 5 节架构障碍 |
| `abl_load_addr` | 无数据源 | loader 用 `adr` 自定位，可能非硬依赖；baseline 保守列为必需 |

四类回传通道在 byron 上**全部实测证伪**：
1. **屏幕大字**：DSC command-mode 面板花屏（hello 探测）。
2. **`/dev/mem`**：节点不存在；`/system/bin/devmem` 指向 `mi_memory_device`/`membuf` 均 mmap 失败。
3. **pstore/ramoops**：写死地址 `0xff4ff800` 在 byron 不对，被 console 环形缓冲淹没。
4. **USB CDC ACM**：`fastboot boot` 后 DWC3 交接状态与 pandora 不同，`dwc3_init` 失败，设备从未枚举。

相关产出保留供参考：`shim/usbprobe/`（探测程序）、`tools/port/capture_usb_probe.py`（串口捕获）、
`docs/byron/USB_PROBE_GUIDE.md`、`docs/byron/USB_PROBE_RESULT.md`。

---

## 5. 核心发现：架构级障碍（本次封存的关键结论）

### 5.1 证据链
- `device/byron/live/drm_framebuffer.txt`：**17 处** `modifier=0x500000000000001`
  = `DRM_FORMAT_MOD_QCOM_COMPRESSED`（**UBWC 压缩**）。
- FDT 面板节点：`qcom,mdss_dsi_byron_42_0d_0a_dsc_cmd` → DSC + **command mode**。
- 真机 `fbverify`：按实测候选 `1216×2608 / stride 4864 / 线性 BGRA/ARGB` 写 `0xfc800000`，**依旧花屏**
  （与 hello、usbprobe 两次线性写屏结果一致，三次独立印证）。

### 5.2 结论
popsicle 能"往 splash buffer 线性写就显示"，依赖的是线性、自刷新的显示链路。
byron 的 framebuffer 走 **UBWC 压缩 + DSC command-mode**：CPU 按线性像素写、SSPP 按压缩格式读 → 花屏。
因此花屏**不是** `fb_w` 1216/1200 或字节序的参数问题，**参数微调无法解决**。
"接管 splash buffer 线性直写"这一 popsicle 核心显示路径**不能直接移植到 byron**。

### 5.3 判断演变（如实记录）
1. 原始判断："DSC 压缩流，ARGB 直写必花屏"。
2. 第一次修正（**已被真机证伪**）："DSC 在 DSI 后端对 CPU 透明，花屏只是 stride 错配"→ 据此做 fbverify。
3. 当前结论："UBWC/DSC 架构级不兼容，参数微调无效"。
4. **fbflip 定性（2026-11-21）**：整屏红蓝翻转 4 阶段全部正常显示。进一步确认
   **链路本身是通的**（排除断点 B：command-mode 会持续刷新），花屏纯粹是 **SSPP 按 UBWC
   解读线性像素**（断点 A），且上下半屏分界居中证明 `fb_h/stride` 几何正确。
   障碍从"参数未定"精确为"单一工程问题：让 SSPP 接受线性源"。
详见 `USB_PROBE_RESULT.md` 第 4/5 节、`FBFLIP_GUIDE.md` 真机结果节、`manual.json` 的 `fb_w_h` 来源说明。

---

## 6. 交付物清单

### 配置与数据
- `profiles/byron.env` — byron 配置，37/42，`BOARD_DATA_COMPLETE=no`
- `device/byron/manual.json`、`adt_overrides.json`、`firmware.json`、`stock_dump.json`
- `device/byron/extents/{iosroot,ioslog,adspfw}.json` — pinned 范围（手机文件仍在位）
- `device/byron/live/` — DRM/FDT/framebuffer 实证快照
- `backup/manifest.txt` — boot_b 哈希存证

### 工具
- `tools/safe_boot.sh`、`safe_recover.sh`、`tests/test_safe_boot.sh`（45/0）
- `tools/port/` — 固件分析、配置生成、只读采集、framebuffer 采集、串口捕获
- `tools/pinfile/pinprobe.c` — arm64 裸机 FIEMAP 探测

### 探测镜像（保留，未成功但有价值）
- `shim/hello/out/`（大字探测）、`shim/usbprobe/out/usbprobe-boot.img`（USB）、
  `shim/fbverify/out/fbverify-boot.img`（framebuffer 验证，花屏）

### 文档
- `docs/DSU_STYLE_SAFE_BOOT.md`、`docs/byron/PORTING_GUIDE.md`、`WHAT_TO_COLLECT.md`、
  `PORT_CHECKLIST.md`、`FIRMWARE_DIFF.md`、`FIRMWARE_PROVENANCE.md`、
  `USB_PROBE_GUIDE.md`、`USB_PROBE_RESULT.md`、`FB_VERIFY_GUIDE.md`、**本报告**。

---

## 7. 若日后重启，建议路线（按推荐度）

1. **攻克 UBWC/DSC 显示**：在 loader/XNU 侧编程 MDP/SSPP/DSC，把链路配成线性源或按 UBWC 写入。
   根治方向，但需高通显示寄存器级开发，工作量大、周期长。
2. **绕开 command-mode**：确认 byron 是否有外部显示输出（HDMI/DP over USB-C DisplayPort Alt Mode），
   或能否把面板切到 video mode，从而绕开 DSC command-mode。
3. **封存/转研究**：保持现状作为研究性成果；本项目不以"真机跑通 iOS"为已达成目标。

无论哪条路，重开时都应先读 `USB_PROBE_RESULT.md` 第 4/5 节和本报告第 5 节，避免重复走已证伪的四条回传通道。

### 最低成本的下一步验证（2026-11-21 补充）

封存后又做了一个**红蓝翻转**诊断镜像 `shim/fbflip/out/fbflip-boot.img`（指南见 `FBFLIP_GUIDE.md`）。
它用整屏纯色（对 stride/width/字节序不敏感），只需一次 boot 就能区分花屏的两种根因：
- 屏幕红蓝整体翻转 → 数据上了屏，是格式问题（断点 A，UBWC）；
- 屏幕始终不变色 → 数据没上屏，是 command-mode 刷新/buffer 地址问题（断点 B）。

这个验证**不需要 root**、不写分区、36 秒自动重启，是继续之前最划算的一步。

**已真机执行（2026-11-21，用户目视确认）**：4 个阶段全部按预期显示——全屏红↔全屏蓝、
上下半屏红蓝交替，分界平直居中。结论：

- **断点 B 排除**：CPU→显存→DSI→面板链路通，command-mode 在 fastboot boot 后持续刷新。
- **断点 A 确认**：花屏是格式问题——SSPP 按 UBWC 压缩解读线性像素，非 stride/字节序。
- **几何参数间接证实**：上下半屏分界居中 → `fb_h=2608`/`fb_stride=4864` 布局正确。
- 纯色能上屏、复杂图案花屏，正是 UBWC 对纯色 tile 有快速路径的典型表现。

**这把障碍进一步收窄**：从"4 个 framebuffer 参数未定 + 架构障碍"收窄为
"几何参数已定稿，只剩 1 个明确的工程问题——让 SSPP 按线性源显示（关 UBWC 或按 UBWC 写入）"。
详见 `FBFLIP_GUIDE.md` 的"真机结果"节。

---

## 8. 当前状态快照

- 完成度 **37/42**；安全闸门 `BOARD_DATA_COMPLETE=no`；`safe_boot.sh --commit` 仍拒绝。
- XNU 内核**未编译**；真机系统分区**未改动**；手机已正常回到安卓、在线。
- 核心回归 **45/0**；所有实证数据可离线复现（`collect_live_framebuffer.py` 等）。
