# 目标 iOS 版本决策：最终 16.7.16 (20H392)

> 用户先于 2026-11-21 指定 16.5，随后**主动回退**到项目原生的 16.7.16。本文记录决策依据与已验证事实。

## 1. 最终版本（已本地 + 联网双重核实）

| 项 | 值 |
|---|---|
| 版本 / build | iOS **16.7.16** / **20H392** |
| IPSW 文件 | `iPhone10,3,iPhone10,6_16.7.16_20H392_Restore.ipsw` |
| SHA256 | `ece1194f7e233e9109c5790a8d23a4564a10a254e15ec5b09978a343265568fb` |
| 本地路径 | `F:/i4Tools9/Firmware/iPhone10,3,iPhone10,6_16.7.16_20H392_Restore.ipsw`（WSL: `/mnt/f/i4Tools9/Firmware/...`） |
| 校验结果 | ✅ 本地 SHA256 与 Apple 官方值一致；文件完整；**当前仍被 Apple 签名** |
| 设备 / 板 | iPhone X (Global/GSM) / D22AP, t8015 (A11) |
| 内核系列 | xnu-8796（iOS 16 era） |
| 发布日期 | 2026-05-11（仍在签名窗口内） |

## 2. 为什么放弃 16.5、回到 16.7.16

2026-11-21 用户一度指定 iOS 16.5 (20F66)。核对两份 IPSW 的 `BuildManifest.plist` 后发现：

| 项 | 16.7.16 (项目原生) | 16.5 |
|---|---|---|
| cryptex dmg | `087-86698-044` / `087-86593-047` / `087-86715-047` | `096-04088-077` / `096-04666-078` / `096-03536-083` |
| static trustcache | `087-86698-044.dmg.trustcache` | `096-04088-077.dmg.trustcache` |
| 项目硬编码 | ✅ 完全匹配 | ❌ 全部不匹配 |

虽然两者同属 xnu-8796，但 16.5 的构建号与项目脚本/文档里硬编码的值完全不同，需要全链路重新适配且未经项目作者验证。权衡后用户决定回退到项目原生、已验证、且仍签名的 16.7.16。

## 3. 已验证资产（从 16.7.16 IPSW 自动发现）

`device/byron/ipsw_assets.env`（由 `tools/port/discover_ipsw_assets.py --verify-sha256` 生成）：

```
IPSW_VERSION='16.7.16'
IPSW_BUILD='20H392'
CRYPTEX_DMGS='087-86698-044.dmg 087-86593-047.dmg 087-86715-047.dmg'
TRUSTCACHE_FILES='087-86698-044.dmg.trustcache 087-86593-047.dmg.trustcache 087-86715-047.dmg.trustcache'
```

trustcache 顺序 = Static / SystemOS / AppOS，第一个为 static cache（module 0），与 `addtrustcache.py` 约定一致。已用 16.5 与 16.7.16 两份真实 IPSW 交叉验证发现工具（均解析正确）。

## 4. 构建号发现工具（本次修正）

`tools/port/discover_ipsw_assets.py` 最初的实现假设 trustcache 挂在 dmg 条目的 `TrustCache` 字段下——**这是错的**。真实 iOS 16 BuildManifest 结构：

- `ProductVersion` / `ProductBuildVersion` 在 plist **顶层**（不是 `BuildIdentities[i].Info`，后者是 `BuildNumber` / `BuildTrain`）
- trustcache 是**独立 manifest 条目**：`StaticTrustCache`、`Cryptex1,SystemTrustCache`、`Cryptex1,AppTrustCache`，其 `Info.Path` 指向 `Firmware/NNN-NNNNN-NNN.dmg.trustcache`
- 明确排除 `RestoreTrustCache`（恢复模式 RAMDisk 专用，启动流程不需要）

工具已按此修正，两版 IPSW 实测通过。

## 5. 当前阻塞 / 下一步

- IPSW ✅ 已就位并校验通过。
- 本机仍**没有编译好的 XNU kernel**（需 GitHub CI `xnu.yml` + Apple Silicon Mac 本地 relink）；带 XNU payload 的 `loader-boot.img` 尚无法生成，XNU 未实测。
- 下一步可推进：把 IPSW 侧资产（kernelcache / d22ap.adt / applelogo / cryptex dmg+trustcache）按项目流程解包到 WSL 工作目录，为 kernel prelink 与 payload 打包做准备。
- 安全闸门 `BOARD_DATA_COMPLETE=no` 不变；未刷任何分区、未动 AVB。
