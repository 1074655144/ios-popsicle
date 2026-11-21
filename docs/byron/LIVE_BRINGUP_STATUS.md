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
- **硬件匹配**：byron GPU = `Adreno840v2`（DT `qcom,gpu-model`），与 gpu_pack.sh 的 gen80200 一致。
  三个必需固件齐全（更正早前误判）：`gen80200_gmu.bin` / `gen80200_sqe.fw` 在 `/vendor/firmware/`，
  `gen80200_zap.mbn` 在 `/odm/firmware/`（不是 vendor，之前只搜了 vendor 才误判缺失）。

**turnip CI 构建失败根因（已定位并修复，提交 `73799a0`）**：run `44882253512` 步骤 Build 报
`UTIL_ARCH_LITTLE_ENDIAN unset`、`PIPE_FORMAT_RG88_UNORM undeclared`、`Dl_info/dladdr undeclared`，
全部出自 flex 生成的 `ir3_lexer.c` 一个编译单元（同批 `ir3_parser.c` 正常）。根因：cross-file 让
meson 在 macOS host 探测到 `HAVE_ENDIAN_H=1`，但实际用 iOS SDK 编译，`<endian.h>` 无 `__BYTE_ORDER`
→ `u_endian.h` 字节序宏未定义 → 连带字节序依赖的 PIPE_FORMAT 别名和 dladdr 分支全崩。
修复：`tools/turnip/build_ios.sh` 的编译参数注入 arm64 恒定小端宏
`-DUTIL_ARCH_LITTLE_ENDIAN=1 -DUTIL_ARCH_BIG_ENDIAN=0`，并对编译单元 `-include dlfcn.h`；
链接参数保持不变。纯编译配置，不改源码。重跑 run `44924717465`（head `73799a0`）在 2026-11-22 复查时确认**僵死**：该 run 的 Build 步骤从 `16:31:42Z` 起 `in_progress` 超过 8 小时，`updated_at` 一直停在 `16:30:59Z`，步骤自身的 20 min / job 的 90 min 超时都没触发，说明 macOS runner 失联（同一流程健康时约 3 min 即报错）。GitHub API 显示 Build 之前的 checkout/Deps/Sources 都 success，只有 Build 卡住，后续 Summary/Pre-release/Metal 全 pending，`turnip-ci` release 不存在。已通过 `workflow_dispatch` 重新触发新 run `44925174949`（head `76d96bd3`，含 turnip 修复固件路径两处提交），新 run 正常推进（Deps → Sources → Build），后台监控中。旧 run 因并发组 `cancel-in-progress: true` 会被新 run 取代。

**CI 一次成功即可拿到全部插件产物**：turnip.yml 先构建 Turnip（`libvulkan_freedreno.dylib`
+ `vktest`）并发布 `turnip-ci` pre-release；随后 `continue-on-error` 的 Metal plugin 步骤构建
`NativeAdrenoMetal` + `Info.plist` + `mtltest` 并上传到同一 release。上一轮因 Build 失败（set -e）
两步都被跳过，所以必须先修通 Build。gpu_pack.sh 所需的 6 个签名文件会全部齐备。

打包工具链：`tools/mkfwpack.py`、`tools/pgputest/mktc.py` 均纯 Python 标准库，WSL 可跑，
插件二进制从 release 下载后 fwpack.img 打包可在本机完成，无需 macOS。

下一步顺序（每步单独验证，不要混在一起）：
1. 等新 run `44925174949`（旧的 `44924717465` 已判定僵死并被取代）：先确认 Turnip 的 Build + Pre-release 成功，再确认 Metal plugin 成功。
2. 从 `turnip-ci` release 下载 6 个文件（libvulkan_freedreno.dylib / vktest / NativeAdrenoMetal /
   NativeAdrenoMetal.Info.plist / mtltest / SHA256SUMS*.metal）到 `/opt/work/gpu/turnip`，校验 SHA256。
3. 从手机 pull 三个 gen80200 固件（gmu/sqe 在 vendor，zap 在 odm）到 FWDIR，跑 `gpu_pack.sh`
   （或 WSL 下等价的 mkfwpack + mktc 流程）生成 fwpack.img + gpu.tc。
4. rawwrite fwpack.img 到 adspfw.img 的 pinned 物理块 + 重采 adspfw extents + 重打 loader。
5. `fastboot boot` → 内核安装器把插件装进 root → 抓日志确认 NativeAdrenoMetal.bundle 加载。

全程约束：小米17 Max `byron`；不刷分区、不改 AVB、不做额外解锁。

## fix15 白苹果卡点分析（2026-11-22，方向 A 结论）

fix13/14/15 的 `exec xpcproxy` 每 10 s 循环**不是新阻塞**：紧跟其后的只有
`bluetoothd` 与 `fairplayd.H2` 被 SIGKILL，属于 `sweetnoexec=bluetoothd,fairplayd.H2`
基线的预期行为；3 次后还打印 `sweetcrashstop` 停止重启。GPU 链路也确认是活着的：
`backboardd` client 0 经 AGXAccelerator 打开成功，`pipeline_libraries_made +33`、
`pipelines_linked +17`，SWEET FB 实际 swap 多层且 `shown` 计数推进，渲染真实发生。
白苹果的直接疑点收敛到两处：

- `Failed to handle the new encryption key. Error 0xe00002d8`（34.030 s）。配套
  `securityd sel 10 ... -> 0xe00002c7`（`kIOReturnUnsupported`，ProtectedCloudKeySyncing /
  cdpd 钥匙串同步链路）。`0xe00002d8` = `kIOReturnNotReady`，同一错误码也出现在
  `IONVRAMCHRPHandler.cpp:sync:894 - serializeVariables failed`，指向 NVRAM/keybag 写入失败。
- `UMD_INIT: FAILED to Set Foreground ID + multiuser in commpage successfully`
  （13.465 s）。`curFG:502, nextID:-1`、`BootedUser is:501`，会话表有 user 501 但取不到
  next-session dict，退回 Loginwindow UID。此后始终没有 `exec loginwindow`。
  该现象 fix13/14/15 完全一致，是稳定基线，不是 fix15 引入。

### unified log 抓取链路：已修复工具，但数据侧不可用（重要）

方向 A 原计划用 unified log 看 SpringBoard 侧详情，排查中发现两处历史缺陷并修复：

1. `tools/ioslog_fetch.py` 的 `--parse` 写死调用
   `/opt/work/macos-UnifiedLogs/examples/target/release/unifiedlog_iterator`，但该工具**从未安装**，
   所以 fix11–fix15 每次抓取的解析步骤都静默失败，`ul_*.jsonl` 从未生成。本次已用 rsproxy
   镜像装 Rust 1.88（apt 的 1.75 因 `edition=2024` 编不了），克隆
   `mandiant/macos-UnifiedLogs` 并以 `cargo build --release -p unifiedlog_iterator` 编译成功。
2. iOS 16 的 diagnostics 是「migrated」布局（UUID 文件名 + hex 桶），解析器只认传统
   `Persist/*.tracev3`。新增 `tools/ul_adapt.py` 按 chunk tag 分类并硬链成标准布局。
   可用（无实时数据入库）：
   `python3 tools/ul_adapt.py la_fix15 la_fix15_std` → `unifiedlog_iterator -m log-archive -i la_fix15_std`。

但**数据侧不可用**：按首 4 字节 magic 重新分类三个 archive，fix13/14/15 都只有
~226 个 uuidtext（`0x66778899`）+ 2 dsc（`0x64736368`）+ 1 timesync（`0xbbb0`），
**没有任何 tracev3**（顶层 chunk tag `0x1000`/`0x600b`/`0x600d`）。因此无论布局如何适配，
解析结果都是 0 行。根因是 `ioslog_fetch.py` 的 `--minutes` 过滤按 HFS mtime 排除掉了
tracev3，或 iOS 把本次启动的 trace 写在未纳入 root 镜像的卷上。要在 unified log 里继续，
需先修抓取脚本的 tracev3 识别（按 magic 而非扩展名/时间过滤），这是独立任务。

结论：方向 A 暂不能提供新证据，转方向 B——先攻 `0xe00002d8` 的 NVRAM/keybag 写入失败与
`usermanagerd` 前台会话失败。两者可能是同一根因：系统卷 `rootrw=1` 下 NVRAM 持久化失败，
导致 keybag 新 key 无法登记、user session 无法置为 foreground，loginwindow 因此不启动。
