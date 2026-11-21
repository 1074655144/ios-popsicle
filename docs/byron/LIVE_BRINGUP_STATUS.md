# byron 真机启动进展（2026-11-21）

> 这是当前阶段的状态记录。早期离线/封存结论见
> [PHASE_CLOSEOUT.md](PHASE_CLOSEOUT.md)；相机采集步骤见
> [PHONE_DATA_CAPTURE.md](../PHONE_DATA_CAPTURE.md)。
>
> **仓库只保存工具和步骤，不保存真机实时采集文件。** `incoming/`、`*.raw`、
> `pandora_shot_*.png`、`device/byron/extents/*.json`、`device/byron/live/*`
> 均为本地数据，已由 `.gitignore` 排除。

## 已打通的链路

| 阶段 | 现象 / 根因 | 处理 | 结果 |
|---|---|---|---|
| 初始 | `iosroot.img` 只是 fallocate 占位 | 电脑端复刻镜像工具链：`apfs-fuse` → 暂存树 → `guestfish tar-in` → 非 journaled HFS+ | 本机构建出 16 GiB 真实根镜像 |
| stride | 4864 导致花屏 | `FB_STRIDE=4800`，同步 DTB/ADT/shim | 画面链路通过 |
| root extents | ADT 缺 pinned extents | `fuxi-root-extents` / `fuxi-log-extents` | 内核能按物理块访问 root/log |
| FBE | 物理块是密文（签名 `cb34`） | 用户授权 `rawwrite`，`pinwrite` 把明文写进 pinned 物理块 | 物理签名变 `HX` |
| fix5 | keybag 阶段重启 | `systembag.kb` 改为 plain binary plist，目录 0777、文件 0600 | root 挂载、`launchd`、dyld cache 映射均成功 |
| fix6 | `launchd_cache_loader[22]` namespace 7 / subcode 0x21，`Unable to find AMFI` | 补 `launchd_unsecure_cache=1` | `Cache sent to launchd successfully` |
| fix7 | `SpringBoard`、`backboardd` 启动并点亮背光，但停在苹果 Logo；backboardd 一直找不到 `IOAcceleratorES / AGXAccelerator` | 按项目首启 CPU 渲染基线补齐 boot args | 进入 fix8 |
| fix8 | 加入首启 CPU 渲染参数后仍是白苹果 Logo | 固定 boot args：`unentitled_ios_sim_launch=1 ignition_level=1 wdt_test=no_user_checkin wdt=-1 sweetfb_hz=30 sweetfb_fill=1 sweetnoexec=bluetoothd,fairplayd.H2` | `fastboot boot` 成功，无 panic |
| fix9 / fix10 | `backboardd` 找到 `IOAcceleratorES`（`0 found`），但仍找不到 `AGXAccelerator`（`none`）；`pandora_gpu_metal=1` 未能保留到最终 cmdline | 补丁 0184 改为无条件发布 `AGXAccelerator`；提交 `66718c4`，触发 xnu CI run `44920089727` | 新内核编译成功（`535466b6`） |
| fix11 | panic：`launchd failed to start -- exit(1)`，`Library not loaded: /usr/lib/libSystem.B.dylib (no such file, no dyld cache)` | 清晰 panic 照片读出原因；逐项排除内核/打包差异后，定位为 **root extents 漂移** | rawwrite 重写 + 重采 extents，见下 |
| fix12 | 新内核 + 新 extents，无 panic，跑到 229 s | rawwrite 16 GiB 重写 root；重采 extents（2004→5531 段）；重建 ADT/payload/loader | **launchd 恢复，AGXAccelerator 从 `none` 变 `found` 并注册成功**；仍卡苹果 Logo |

## fix11 根因：root extents 漂移（重要）

fix11 只换了内核，cmdline / 内核 dyld+AMFI 字符串（241 项）/ PANDORA 补丁（除 AGX 两行诊断外 742 项）
全部与 fix10 一致。 panic **不是** AGX 补丁引起，而是 root 镜像的 pinned 物理块发生了漂移：

- 仓库 `device/byron/extents/iosroot.json`（fix10 用）：**2004 段**，首块 `116004737024`。
- 手机当前 `pinfile extents /data/local/tmp/iosroot.img --json`：**5531 段**。
- 前 26 段相同，从文件偏移 **211 MiB** 起物理块位置完全不同且严重碎片化
  （例：偏移 `221249536` 旧为物理 `120261820416` 连续 5.6 MiB，现为 `27112755200` 仅 40 KiB）。
- 内核拿旧 extents 读 root，211 MiB 之后的卷数据（dyld cache / libSystem 所在）全部读错，
  launchd 找不到 `/usr/lib/libSystem.B.dylib` → panic。
- 这也解释了为什么抓到的内核环日志与 fix10 逐字节相同：fix11 在写日志前就 panic 了。

修复（fix12）：
1. `pinwrite rawwrite` 把 `/data/local/tmp/iosroot.src2.img`（含 binary plist keybag，SHA 与本机
   `/opt/work/iosroot.img` 一致）写回 `iosroot.img` 的 pinned 物理块。
2. `pinfile extents --json` 重新采集 `iosroot` / `ioslog`，覆盖 `device/byron/extents/*.json`。
3. 用新 extents 重建 ADT / payload / loader，只换内核 + extents，boot args 不变。
4. `fastboot boot` 后回安卓抓日志，确认 launchd 不再 panic，再看 AGX 诊断。

**结论**：每次 iOS 侧 `rootrw=1` 写入都可能改变 F2FS 物理布局；下一次 boot 前必须重采 extents。

## fix12 结果：两个核心目标达成（2026-11-22）

fix12 = 新内核 `535466b6` + 重采 extents（5531 段）+ fix10 boot args。内核环日志
`165439 bytes, flush 48`，SHA `54b886cd`，与 fix10/fix11 的 `15a3c566` 完全不同（真实新日志），
无 panic，跑到 229 秒。

**突破 1 — extents 修复生效**：
- `Using unsecure cache: /System/Library/xpc/launchd.plist` → `Cache sent to launchd successfully`
- `exec SpringBoard` / `exec backboardd` 成功；不再有 `no dyld cache` panic。

**突破 2 — AGX 补丁生效**（fix9/fix10 一直卡在这里）：
- `[0.126] PANDORA GPU UC: AGXAccelerator::start metal arg=1`（诊断日志落盘，证明这次 metal arg 保留住了）
- `[0.126] PANDORA GPU UC: AGXAccelerator (IOAcceleratorES) registered, plugin NativeAdrenoMetal`
- `IOService::start FAILED` **没有出现** → start 成功。
- backboardd 从 fix10 的 `AGXAccelerator -> none` 变成 `-> 1 found` / `-> AGXAccelerator`，
  内核侧匹配与注册链路完全打通。

**新的卡点（仍在苹果 Logo）**：
- `[19.386] IOK backboardd: open AGXAccelerator type 1 -> 0xe00002c7`（`kIOReturnError`），
  backboardd 反复 matching（14–24 s 间几十次）但 open 失败。
- 全日志**没有任何** `NativeAdrenoMetal.bundle` / Metal 插件加载记录——root 镜像里没装这个插件，
  内核只发布 `MetalPluginName=NativeAdrenoMetal` 属性，用户态找不到对应 bundle。
- `SWEET FB: swap ... -> 0xe00002d5`（`kIOReturnTimeout`）反复出现，合成表面排队但交付超时。
- 仍然没有 `exec loginwindow`（只有 xpcproxy 周期性启动），登录会话没进入。
- `bluetoothd` / `fairplayd.H2` 周期性 CRASH 属于既定 sweetnoexec 基线。

结论：内核侧 AGX 已打通，白苹果卡点转移到**用户态 Metal 插件缺失**。下一步需在 root 镜像安装
`NativeAdrenoMetal.bundle`（Turnip Darwin 后端）并确认其 `MetalPluginClassName` 与内核属性匹配，
再做一次 rawwrite + 重采 extents + boot。不要把登录会话排查与插件安装混进同一轮。

## fix7–fix10 关键日志结论（不提交原始日志）

- `launchd_unsecure_cache=1` 生效：`Cache sent to launchd successfully`。
- `exec SpringBoard`、`exec backboardd` 成功；fix7 中 backboardd 完成 5 次 CPU 合成并点亮背光。
- fix10 中 `backboardd` 能匹配到 `IOAcceleratorES`（`0 found`），但 `AGXAccelerator` 一直是 `none`，没有进入 Metal 设备发现。
- fix10 有 `UMD_INIT: failed to read nextsession dict`、`UMD_INIT: FAILED to Set Foreground ID`，之后没有 `exec loginwindow`；这是当前白苹果卡点的第二个可疑用户态阻塞项。
- fix10 有 `exec DumpPanic` 和一次 `CRASH driverkitd`，但没有新的内核 panic 行；截图仍是纯黑底白苹果 Logo。
- `bluetoothd` / `fairplayd.H2` 周期性重启，属于已设置的 `sweetnoexec` 基线，不是本轮新增阻塞。
- 当前 root 镜像未安装 `NativeAdrenoMetal.bundle` / Turnip；内核侧 AGX 打通后仍需单独处理用户态 Metal 插件。

## 当前产物（仅本机）

- CI run `44920089727` 编译成功；新内核 `kernel.development.pandora` SHA256 `535466b6…`（AGX 无条件发布补丁）。
- fix11 loader SHA256：`d509aa57…`（备份在 `incoming/loader-boot.img.fix11.bak`），已证实因 extents 漂移 panic。
- fix10 及之前 extents 备份：`incoming/iosroot.json.fix10.bak`、`incoming/ioslog.json.fix10.bak`。
- 所有镜像、日志、截图、实时 extents 均在 `incoming/` / `device/byron/extents/`，被 `.gitignore` 排除，不入库。

## Metal 插件安装链路调研（2026-11-22）

fix12 确认内核侧 AGX 已打通，白苹果卡点转移到用户态 Metal 插件缺失。仓库里已有完整链路：

- **内核文件安装器**：内核含 `pandora_files` / `PANDORA FILES:` 字符串（`bsd/dev/pandora_files.c`）。
  它从 pinned 的 `adspfw.img`（byron 上 8 MiB）里的 fwpack.img 读 `files.txt`，把文件装进 root。
  fix10 / fix11 内核都含此机制，**不需要重编内核**。
- **打包脚本**：`mac/gpu_pack.sh FWDIR` 生成 `fwpack.img` + `gpu.tc`。把
  `NativeAdrenoMetal.bundle`（`NativeAdrenoMetal` + `Info.plist`）、`NativeAdrenoMetal.clients`、
  `libvulkan_freedreno.dylib`、`vktest`、`mtltest`、`com.apple.backboardd.plist` 装进 root，
  并把这些二进制的 trust cache 合并进静态模块。脚本头注释写的是 17 Pro Max，但机制通用。
- **插件来源**：`.github/workflows/turnip.yml` 交叉编译 `NativeAdrenoMetal`（UniXNU NativeMetal
  经 `tools/metal/adapt_ios16.py` 适配 iOS 16）和 Turnip，发布到 `turnip-ci` pre-release。
  fork 和上游目前**都没有** `turnip-ci` release；本地 `/opt/work/gpu/turnip` 为空。
- **硬件匹配**：byron GPU = `Adreno840v2`（DT `qcom,gpu-model`），手机有
  `gen80200_gmu.bin` / `gen80200_sqe.fw` / `gen80200_aqe.fw`，与 gpu_pack.sh 的 gen80200 一致。
  唯一缺口：byron **没有** `gen80200_zap.mbn`（gpu_pack.sh 必需），需确认是否可用 aqe.fw 替代或另行提取。

**阻塞点：turnip CI 构建失败**（run `44882253512`，步骤 Build）：
meson 交叉编译报 `UTIL_ARCH_LITTLE_ENDIAN unset`、`PIPE_FORMAT_RG88_UNORM undeclared`、
`Dl_info/dladdr undeclared`（19 errors）。属工具链版本漂移导致的配置问题（cross-file 已写
`endian = 'little'`，但新版 meson 未转成编译宏），非源码缺陷。修 `tools/turnip/build_ios.sh`
的 cross-file / meson 配置后可重试。

下一步顺序（每步单独验证，不要混在一起）：
1. 修 turnip CI 编译配置 → 重跑 `turnip.yml` → 从 `turnip-ci` release 下载插件产物。
2. 按 byron 固件调整 `gpu_pack.sh`（zap.mbn 缺口）→ 生成 fwpack.img + gpu.tc。
3. rawwrite fwpack.img 到 adspfw.img 的 pinned 物理块 + 重采 adspfw extents + 重打 loader。
4. `fastboot boot` → 内核安装器把插件装进 root → 抓日志确认 NativeAdrenoMetal.bundle 加载。

全程约束：小米17 Max `byron`；不刷分区、不改 AVB、不做额外解锁。
