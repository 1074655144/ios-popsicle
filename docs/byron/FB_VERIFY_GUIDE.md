# byron framebuffer 参数肉眼验证指南

> ## ✅ 2026-11-21 14:57 最终结论（本文件下方旧候选值已作废）
>
> **花屏根因 = stride 写错，真值 `fb_w=1200 / fb_stride=4800`（popsicle 原值），不是 UBWC。**
>
> - `shim/stridescan` 四带照片实证：只有 band0(4800) 竖条笔直，4864 折半、4928 棋盘格。
> - 改回 1200/4800 重编 fbverify 后真机照片：标题 `1200x2608 STRIDE 4800` 锐利可读、色条纯净、
>   棋盘格方正、边框平直（照片 `clipboard-2026-11-21T06-57-01-563Z-ea3613cb.jpg`）。
> - 字节序确认 = **ARGB word 0xAARRGGBB**（ROW A 正确），loader.c 硬编码无需改 BGRA。
> - 1216/4864 是 Android 运行时 UBWC 帧缓冲 `fb370` 的参数，**不适用于 fastboot 后的线性 splash FB**。
> - 之前"UBWC/DSC 架构级不可解"是误判（fbflip 纯色对 stride 不敏感，误导了判断）。
>
> 下方是历史验证流程记录，其中 1216/4864 候选值已被上面结论取代。

## 目的（原始记录，参数已由上文定稿）

确定 XNU loader 写屏用的三个参数，一次性用肉眼判定：

| 参数 | 候选值 | 判定方式 |
|---|---|---|
| `fb_w` / `fb_stride` | **1200 / 4800（定稿）** | 棋盘格和边框是否倾斜、右侧是否留黑边 |
| `fb_format` 字节序 | ARGB8888 vs BGRA8888 | 两组色条里哪组"红是红、蓝是蓝" |
| `fb_h` | 2608 | 已知（面板 vactive），边框到底部是否完整 |

这取代了之前失败的引导期寄存器探测——参数已从正常安卓的只读 debugfs + FDT 拿到，只需真机确认写屏效果。

## 验证镜像

`shim/fbverify/out/fbverify-boot.img`（kernel 9288 字节，纯 RAM，`fastboot boot`，不写任何分区）
SHA-256 `c135ae38c733b694066b6af6b0612d343ebf3f574f2e8d402195a87b96e5c869`（2026-11-21 改 1200/4800 后重编）

屏幕内容（从上到下）：
1. **标题条**：`BYRON FB VERIFY 1200x2608 STRIDE 4800`
2. **ROW A 色条**：红/绿/蓝，用 ARGB word 语义 `0xAARRGGBB` 写
3. **ROW B 色条**：红/绿/蓝，用 BGRA word 语义 `0xAABBGGRR` 写（R/B 位对调）
4. **棋盘格区**：白黑格，检查 stride/倾斜
5. **1200 参考线**：黄色竖线，标出物理面板宽度位置
6. **整屏紫色边框**：画到 x=1200、y=2608

约 25 秒后 PSCI 自动重启回安卓；长按电源键可提前重启。

## 操作步骤

### 1. 手机进 fastboot

```bash
ADB='/e/刷机工具/RKDevTool_Release_v2.95/bin/adb.exe'
FASTBOOT='/d/软件/搞机助手/fastboot.exe'
"$ADB" reboot bootloader
"$FASTBOOT" devices     # 确认出现 <serial> fastboot
```

### 2. boot 验证镜像（纯 RAM，不 flash）

```bash
cd "<repo>"
"$FASTBOOT" boot shim/fbverify/out/fbverify-boot.img
```

### 3. 拍照（关键）

boot 后屏幕会显示测试图案约 25 秒。**用手机/相机拍一张完整屏幕照**，要能看清：
- ROW A 和 ROW B 两组色条各自的颜色
- 棋盘格是否倾斜、右侧有没有多出的黑边
- 底部紫色边框是否完整

拍完发给我，我会据图判定字节序和 width/stride。

### 4. 自动重启

25 秒后手机自动回安卓。确认：

```bash
"$ADB" wait-for-device shell 'getprop sys.boot_completed'
```

## 判定标准

**字节序**：
- 若 ROW A（上组）显示"红绿蓝"正确 → 用 ARGB 语义，loader.c 无需改颜色字节序
- 若 ROW B（下组）显示"红绿蓝"正确 → 用 BGRA 语义，需改 loader.c 颜色字节序

**width/stride**：
- 棋盘格是正方格、竖线垂直、无倾斜 → 1200/4800 正确（2026-11-21 真机已确认通过）
- 棋盘格被拉斜/出现错位条纹 → stride 错
- 边框右侧超出可见区一段（黄色 1200 线在边框内侧）→ 面板只有 1200 宽，属正常裁剪；此时 fb_w 是否取 1200 需结合 XNU 侧再看

## 安全边界

- 全程 `fastboot boot`（RAM），不 flash、不写分区、不动 AVB/vbmeta
- 失败也不影响系统：最长 25 秒自动重启回安卓
- 唯一副作用：期间 adb/fastboot 断开，属预期
