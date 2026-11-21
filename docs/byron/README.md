# byron 移植文档（小米17 Max）

## 机型口径（唯一）

**本仓库适配的目标机型只有一个：小米17 Max，代号 `byron`，SoC 为 SM8850-AC / 骁龙 8 Elite Gen 5。**

小米17 系列有多款不同后缀的型号：

| 中文型号 | 代号 | 本仓库关系 |
|---|---|---|
| 小米17 | `pudding` | 无关 |
| 小米17 Pro | `pandora` | 无关 |
| 小米17 Pro Max | `popsicle` | **仅上游来源** |
| **小米17 Max** | **`byron`** | ✅ **本仓库唯一适配目标** |

本目录所有文档中的 `byron` 均指小米17 Max。文中出现的 `popsicle` / 小米17 Pro Max 只表示上游来源或对比对象，**不是**本仓库的适配目标。

## 来源 / Upstream

本项目 fork 自 **[OctoDevStudios/ios-popsicle](https://github.com/OctoDevStudios/ios-popsicle)**。
原仓库适配小米17 Pro Max（`popsicle`）；本 fork 在其基础上改适配小米17 Max（`byron`）。
更上游的工作见主 [README](../../README.md#credits) 的 Credits 段（Data A Live、ios-sweet、ios-fuxi、UniXNU 等）。

## 文档索引

| 文档 | 内容 |
|---|---|
| [CI_KERNEL_BUILD.md](CI_KERNEL_BUILD.md) | XNU kernel 云端编译（GitHub Actions）+ 本机组装 payload + RAM 启动 |
| [PHASE_CLOSEOUT.md](PHASE_CLOSEOUT.md) | 阶段性封存报告、花屏根因结论、判断演变 |
| [PORTING_GUIDE.md](PORTING_GUIDE.md) | 移植可行性与板级差异 |
| [PORT_CHECKLIST.md](PORT_CHECKLIST.md) | 逐项参数清单 |
| [FIRMWARE_PROVENANCE.md](FIRMWARE_PROVENANCE.md) | 官方 OTA / 字库备份取包存证 |
| [FIRMWARE_DIFF.md](FIRMWARE_DIFF.md) | byron 相对 popsicle 的固件 diff |
| [WHAT_TO_COLLECT.md](WHAT_TO_COLLECT.md) | 需要从手机采集什么 |
| [FB_VERIFY_GUIDE.md](FB_VERIFY_GUIDE.md) | framebuffer 参数肉眼验证（stride 4800 定稿） |
| [FBFLIP_GUIDE.md](FBFLIP_GUIDE.md) | 显示链路红蓝翻转定性验证 |
| [UBWC_OFF_GUIDE.md](UBWC_OFF_GUIDE.md) | 关 UBWC 诊断（已封存） |
| [USB_PROBE_GUIDE.md](USB_PROBE_GUIDE.md) / [USB_PROBE_RESULT.md](USB_PROBE_RESULT.md) | 引导期 USB 探测指南与失败结论 |
| [IOS_VERSION.md](IOS_VERSION.md) | 目标 iOS 版本决策（16.7.16 / 20H392） |
