# byron 关 UBWC 验证：线性显示能否成立

> fbflip 已证明"链路通、纯格式问题"（见 `FBFLIP_GUIDE.md` 真机结果节）。
> 本验证直接编程 SDE/SSPP 寄存器关掉 UBWC，再写线性图案，判定根治路径是否可行。

## 原理

花屏根因：SSPP 按 UBWC 压缩解读 CPU 写的线性像素。若把那一路 pipe 的 UBWC 关掉，
它就会按线性像素解读——这正是 popsicle 上游的工作方式。

寄存器依据（mainline `dpu_hw_sspp.c` / `dpu_hwio.h`，跨代稳定）：

| 寄存器 | 偏移（相对 pipe base） | 作用 |
|---|---|---|
| `SSPP_SRC0_ADDR` | `0x14` | 源地址低 32 位 → 用来定位扫描 `0xfc800000` 的 pipe |
| `SSPP_SRC_FORMAT` | `0x30` | bits[31:30] FRAME_FORMAT，`0` = linear |
| `SSPP_SRC_OP_MODE` | `0x38` | **bit0 = BWC_EN**，清 0 即关 UBWC |
| `SSPP_UBWC_ERROR_STATUS` | `0x138` | 写 BIT31 清 UBWC 错误 |

pipe 基址来自 byron live FDT 的 `qcom,sde-sspp-off`（相对 MDP `0x9800000`）：
VIG `0x2c000/0x35000/0x3e000/0x47000`，DMA `0x98000/0xa1000/0xaa000/0xb3000/0xbc000/0xc5000`。

## 镜像

`shim/ubwcoff/out/ubwcoff-boot.img`（9969 字节，纯 RAM，不写分区）
SHA-256 `b20324b41ce1b9ebac2d4b3f56c01c8c3fa84f46e8c9eeffee47be41c8b5bfc6`

流程（约 40 秒，然后自动重启回安卓）：
1. 扫描 10 路 SSPP pipe，把每路的 `SRC0_ADDR` 画到屏幕顶部；绿色 = 命中 `0xfc800000`。
2. 显示 5 秒诊断：找到则显示该 pipe 的原 OP_MODE/FORMAT 值；没找到显示 `NO PIPE`。
3. 关 UBWC（清 OP_MODE bit0 + FRAME_FORMAT + 清错误），写线性色带 + 大字。
4. 色带循环换色 4 轮，确认持续刷新。

## 操作（不需要 root）

```bash
ADB='/e/刷机工具/RKDevTool_Release_v2.95/bin/adb.exe'
FASTBOOT='/d/软件/搞机助手/fastboot.exe'
"$ADB" reboot bootloader
"$FASTBOOT" devices
cd "<repo>"
"$FASTBOOT" boot shim/ubwcoff/out/ubwcoff-boot.img
```

## 判定表

boot 后前 5 秒先看屏幕顶部诊断，再看后面的色带：

| 屏幕显示 | 含义 | 结论 |
|---|---|---|
| `FOUND P<n>` (绿色) + 色带**纯正、无斜纹** | 找到 pipe 且关 UBWC 后线性显示成立 | **根治路径可行**，可将关 UBWC 集成进 loader/XNU |
| `FOUND P<n>` + 色带**仍花** | 找到 pipe 但关 UBWC 不够（可能 stride/DSC/其他层也要配） | 显示路径还有更多环节，需继续排查 |
| `NO PIPE ...` (红色) | 没有 pipe 的 SRC0_ADDR 等于 0xfc800000 | splash 用的是 IOVA（SMMU 映射后地址），需改判据（见下） |

**如果显示 `NO PIPE`**：说明源地址经 SMMU 映射成了 IOVA。下一步改判据为
"SRC0_ADDR 的高位不等于 0、且各 pipe 中唯一指向 splash region 的那一路"，
或直接对全部 10 路 pipe 都清 UBWC bit（幂等，无副作用），再写图案。

## 安全边界

- 全程 `fastboot boot`（RAM），不 flash、不写分区、不动 AVB。
- 约 40 秒后 PSCI 自动重启回安卓；长按电源可提前重启。
- 不需要 root。改的是运行时寄存器，重启即恢复，不影响系统。
