# 其他机型 iOS 移植仓库对照（byron 白苹果问题）

日期：2026-11-22。方式：联网只读核对公开仓库 + 本地镜像/unified log 实证。**未改内核/镜像，未刷机，未上传任何实时数据。** 用户要求"参考一下其他机型仓库，看有没有新的发现"。

## 一、对照了哪些机型项目

| 项目 | 机型 / SoC | 与我们的关系 |
|---|---|---|
| ios-sweet (github.com/dipa-studio/ios-sweet) | Redmi Note 10 Pro / 骁龙732G (SM7150) | 上游祖先，366 个内核补丁与 fork 完全相同 |
| ios-topaz (github.com/MakrSas/ios-topaz) | Redmi Note 12 4G / 骁龙685 (SM6225) | ios-sweet 的移植，GPU/display/audio/wifi 起点来自 HackiOS |
| HackiOS (github.com/oosexgang/hakios-xnu-kernel) | POCO X5 Pro 5G / 骁龙778G (redwood) + QEMU | 独立实现，自己写 init/loader/用户态替代库，能进桌面、~20s 到锁屏 |
| ios-fuxi | 小米13 / 骁龙8 Gen2 (SM8550) | 本地 FUXI_NOTES.md 已记录，无首启专门处理 |

所有项目都能进 iOS 桌面，且都用**未修改的 iPhone X / iOS 16 用户态**（launchd → backboardd → SpringBoard）。

## 二、新发现（此前没查过的机制）

### 发现 1（高价值）：/private/var 的持久化方式，直接决定 buddy/migration 是否每次重跑

HackiOS 的 `userland/build.sh` 明确写：
- `/private/var` 每次 boot 由 `init` 挂一个**全新 ramfs**，按 `root/etc/var.skel` 填充；
- `var_store` 服务（`com.hakios.varstore.plist` → `/redwood/bin/var_store watch`）在会话结束时把数据卷"带回 flash"，**保留 /var/db、跳过 tmp**；
- 原文注释：Metal 编译好的 shader 放在 `/var/db/hakios-metal-cache`，"so that var_store keeps them (it leaves tmp out)"。

对照 byron：我们的 root 是 `rootrw=1` 可写 HFS+，`unique-chip-id`(PANDORA_ECID) 与 security-status 四键在 ADT 里都齐全（已从 payload.bin 验证 `unique-chip-id=Y`）。**但 unified log 里每个 boot 都 exec `com.apple.datamigrator`（6 次）、DataMigration 反复重跑**——正是 `mkadt.py:109` 注释描述的"没有 CFPreferences ByHost → DataMigration 每次都重跑"症状。镜像里确实**没有 ByHost 目录**（前几节已证）。

### 发现 2（中价值）：setupexited.enabled 键我们从未写入

byron unified log（ul_cpu_control，6 个 trace）里，`nanoregistryd` 每个 boot 都读：
```
NRLaunchNotificationController: notification com.apple.purplebuddy.setupexited.enabled prefs value: 0
NRLaunchNotificationController: notification com.apple.purplebuddy.setupexited.enabled prefs value: 2
```
而 `tools/imgbuild/sweet-root-tweaks.py:59` 只写了 `SetupDone / SetupFinishedAllSteps / SetupVersion / daemonizeNeedsToRun`，镜像 dump 的 `com.apple.purplebuddy.plist`（130 B）里**没有 `setupexited` 这个键**。上游 ios-sweet / HackiOS 的构建脚本里也没找到对这个键的处理。
→ 线索级：这可能是 buddy 判定源之一，但**不是确诊**——日志里 `cloudpaird: buddy is done` 与 `remindd: PastBuddy is 0` 判定相反，说明判定源不止一个；且上游没写这个键也能进桌面，故单独补它的收益存疑。

### 发现 3（低价值，已排除为差异）：sweetbusy 补丁我们没有，但症状不符

ios-topaz 有 `sweetbusy=N` 补丁，注释是"no IOKit-daemon busy hold (IOKit never quiesced, wifid hung boot)"。我们在 `xnu/patches/` 全树搜 `sweetbusy|busy.hold|quiesce` 无对应实现。但 byron 日志里没有 wifid 卡 boot 的症状，此补丁与当前白苹果无关。

### 发现 4（重要对照）：其它机型首启 Apple Logo 停留是正常且会自愈

- ios-sweet：README 写"停在苹果标志约 4 分钟"。
- ios-topaz：README 写"首启在 Apple Logo 停留一会儿（SpringBoard 等 LaunchServices 建库），约 3 分钟后出现锁屏"。
- HackiOS：约 20s 到锁屏。

对照 byron：长测 30 分钟仍白苹果（已证伪"等 lsd"），且本轮 autoswipe 注入 104 次上滑、内核 22.9s 后无新帧提交 → **不是"等得不够久"，是 SpringBoard 重启循环**。这一条进一步坐实前几节结论。

## 三、对白苹果结论的影响

本轮对照**没有推翻**已有结论，反而补上了机制解释：
- 白苹果 = SpringBoard 重启循环（6 次 exec → Apple Logo overlay → No screen owner → remindd PastBuddy=0 → 再 exec）；GPU 有无都同构，GPU 已证伪；
- 其它机型能进桌面的共同前提是 **/private/var 状态能被持久化并在下次 boot 复用**（HackiOS 用 var_store 写回 flash，ios-sweet/topaz 用 userdata 上可写 HFS+）；byron 是 RAM boot，虽然 root 可写但每次都是同一份 pinned 镜像、没有 ByHost、没有 var_store 式的状态回写 → 每次都从"首启未完成"开始。
- 证据等级：发现 1、4 为强（有直接代码/日志/多项目交叉印证）；发现 2 为线索级；发现 3 已排除。

## 四、下一步（未执行，需用户在场）

若继续，比"改 owner/mode"更有依据的方向是**验证 /private/var 持久化/ByHost 这条链**，而非 buddy 通知 marker：
1. 电脑端可在镜像里补 `setupexited.enabled=True`（低收益，上游没写也能进桌面，仅作排除法）；
2. 真机需在 boot 后检查 `gethostuuid` 实际返回值、cfprefsd 是否生成 ByHost 目录——但 byron 是 RAM boot，grafting HackiOS 的 var_store 需重编 init，成本高；
3. 收益/成本都低，建议**先搁置**，除非用户明确要继续 A/B。

## 落盘说明
本文档为主要产物。未改内核/镜像/工具；unified log（ul_cpu_control.jsonl）、内核日志（cpu_control.raw/.txt）、fbdump PNG 均留在本地/WSL，未入库。
