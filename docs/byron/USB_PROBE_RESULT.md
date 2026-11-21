# USB 引导期探测 —— 真机试验结果（2026-11-21）

> ## ⚠️ 2026-11-21 14:57 修正
> 本文件第 4/5 节"1216/4864 定稿 + UBWC 架构级不可解"的结论**已被真机证伪并推翻**。
> 线性 splash FB 真值 = **1200/4800**（popsicle 原值），花屏是 stride 写错，非 UBWC。
> fb370 的 1216/4864/UBWC 是 Android 运行帧缓冲参数，不适用于 fastboot 后的线性 splash FB。
> 实证见 `FB_VERIFY_GUIDE.md` 顶部与工作日志 2026-11-21.md（stridescan + 改参 fbverify 双证据）。

> 结论先行：**USB CDC ACM 探测失败**（设备从未枚举）。但意外找到一条**正常安卓只读通道**，
> 直接拿到了原本要靠引导期探测的 framebuffer 参数。无需再冒险 boot 探测镜像。

## 1. 做了什么

1. 加固 `shim/usbprobe`：改为每 3 秒循环重发完整帧、窗口延长到 ~150 秒，给 Windows 装 usbser 驱动留时间。
   重编译产出 `out/usbprobe-boot.img`（18 KB，无 ABS64 重定位，SHA256 `c204b538…`）。
2. 手机 `adb reboot bootloader` → `fastboot boot shim/usbprobe/out/usbprobe-boot.img`（纯 RAM，未 flash）。
   `fastboot boot` 本身 **OKAY**，镜像已载入执行。
3. 电脑端 `capture_usb_probe.py --wait 200` 后台监听。

## 2. 结果：失败

- Windows **从未枚举**出 `VID_1209&PID_316D` 设备（设备管理器、pyserial 均无）。
- 手机约 1 分钟内自动重启回安卓 → 探测程序走了**失败分支**（`dwc3_init` 返回非 0 → 写 ramoops → 2 秒重启），
  不是成功的 150 秒循环分支。

**根因**：`fastboot boot` 后 byron 的 USB 控制器交接状态与 pandora（Sm8850.h 的来源机型）**并不一致**——
DWC3 基址/stream ID 虽同，但时钟/GDSC/SMMU 或 core role 的继承条件不满足 `QcomUsbQualify.c` 的
严格前置检查（`QcomUsbInspectInherited` / `QcomUsbQualifyIdentityDma` / `core_halted`），`dwc3_init` 直接失败。

**诊断为何丢失**：失败分支把 ASCII 写到硬编码 `0xff4ff800`，这个地址在 byron 上不对（FDT 里 ramoops
由 `ramoops-region` 动态定义），写进去的内容被内核 console 环形缓冲淹没，`/sys/fs/pstore/` 里只剩乱码。
所以三条回传通道（屏幕 / `/dev/mem` / pstore）加 USB，**在 byron 上全部证伪**。

## 3. 意外收获：正常安卓只读通道拿到了 framebuffer 参数

排查过程中发现两个此前被忽略的只读入口：

1. **debugfs 挂在非标准路径** `/dev/okqaeuzc/wz_rmhpt`（不是 `/sys/kernel/debug`，所以之前查 `debugfs/dri` 是空的）。
   其中 `dri/9800000.qcom,mdss_mdp/framebuffer` 和 `/state` 直接暴露活动 framebuffer 的 format / size / pitch。
2. **`/system/bin/devmem` 存在**，但默认 `/dev/mem` 节点不存在、`-f` 指向 `mi_memory_device`/`membuf` 均
   `mmap: No such device`，此路不通（与既有结论一致）。
3. **`/sys/firmware/fdt` 必须用 `adb exec-out cat` 读**（用 `adb shell cat` 会把 `\n`→`\r\n` 破坏二进制 DTB，
   导致解析失败——这正是之前 FDT 解析反复出错的原因）。

### 实证数据（已固化到 `device/byron/live/`）

从 DRM debugfs（`drm_framebuffer.txt` / `drm_state.txt`）：
- 主 framebuffer `fb370`：**1216 × 2608，format AB24 = BGRA8888 little-endian (`0x34324241`)，pitch 4864**（=1216×4）

从精确 FDT（`fdt_final.dts`，`dtc -f` 解析）：
- `splash_region` (label `cont_splash_region`)：**`reg = 0x0 0xfc800000 0x0 0x2b00000`** → 基址 `0xfc800000`，大小 43 MiB

这与上游 `shim/loader/loader.c` 的 framebuffer 基址 `0xfc800000` 完全一致。采集脚本
`tools/port/collect_live_framebuffer.py` 可离线复现，输出 `device/byron/live/live_framebuffer.json`：

```
ADT override: FB=0xfc800000  FB_SIZE=0x2b00000  FB_W=1216  FB_H=2608  FB_STRIDE=4864
fb_format (LE) = 0x34324241
```

## 4. 判断的演变（两次修正，以真机为准）

**原始判断**：`manual.json` / `PORTING_GUIDE.md` 记录"byron framebuffer 存 DSC 压缩流，按 ARGB8888 写必然花屏"。

**第一次修正（已被真机证伪）**：曾改为"DSC 在 DSI 后端，对 CPU 线性写透明；花屏只是 stride/width 错配
（1200/4800 vs 1216/4864）"，据此做了 `shim/fbverify` 验证镜像。

**第二次修正（当前结论，2026-11-21 真机验证后）**：用户选方案 A 后，把 loader.c / ADT 改成 1216/4864
并 boot `fbverify-boot.img`（往 `0xfc800000` 按线性 BGRA/ARGB 画色条+棋盘格+边框，25s 自动重启）。
**结果依旧花屏**。结合新证据，第一次修正过度外推了 popsicle 经验：

- `drm_framebuffer.txt` 中 17 处 `modifier=0x500000000000001` = `DRM_FORMAT_MOD_QCOM_COMPRESSED`（**UBWC 压缩**）
- 面板节点 `qcom,mdss_dsi_byron_42_0d_0a_dsc_cmd` —— DSC + **command mode**
- popsicle 的 `self-refreshing 线性直写` 前提（video mode / 线性 splash）在 byron 上不成立

**结论**：花屏不是 1216/1200 或字节序这类参数微调能解决的，根因是 **byron 的 framebuffer 走 UBWC 压缩 /
DSC command-mode 链路**。CPU 按线性像素写 `0xfc800000`，SSPP 按压缩格式解读 → 花屏。这是**架构级差异**，
popsicle 那套"接管 splash buffer 线性直写"的核心显示路径不能直接搬到 byron。see `docs/byron/FB_VERIFY_GUIDE.md`。

## 5. 仍待定 / 诚实边界

- **显示路径本身未打通**：fbverify 真机花屏证明，在 byron 上"往 0xfc800000 线性写像素即显示"不成立。
  这是比 `fb_w`/字节序更前置的问题。需要先解决 UBWC/DSC 显示链路，才能谈参数微调。
- **`fb_w` 1216 vs 1200 / `fb_stride` 4864 / `fb_format` 字节序**：这些参数都来自压缩的 DRM framebuffer；
  在显示路径打通前无法用肉眼验证，暂不据此定稿。
- **`abl_load_addr`**：仍是唯一没有替代数据源的项。但 loader 用 `adr` 自定位（position-independent），
  此值对启动可能非硬依赖，baseline 列为必需项是保守要求。

### 下一步可选方向（需用户拍板）

1. **在 XNU/loader 侧处理 UBWC/DSC**：让显示链路输出线性帧（关闭 UBWC / 配置 SSPP 线性源），
   或按 UBWC 格式写入。这是真正根治的方向，但需 MDP/SSPP/DSC 寄存器编程，工作量大。
2. **借第二台设备拍屏 + 换非 DSC 显示接口**：若有 HDMI/DP 或能把面板切到 video mode，可绕开 command-mode DSC。
3. **封存为阶段性成果**：把 37/42 现状 + 所有实证（含架构级障碍结论）整理成报告，不再继续真机试探。

## 6. 闸门状态（未改）

`BOARD_DATA_COMPLETE` 仍为 `no`，`safe_boot.sh --commit` 仍拒绝真实启动。
上述数据已作为 **实证证据** 落盘，但是否写入 `manual.json` / 是否据此把完成度推进到 42/42，
**需用户拍板**——尤其 `fb_w` 的 1216/1200 之争和 format 字节序，只有真机启动能最终确认。
