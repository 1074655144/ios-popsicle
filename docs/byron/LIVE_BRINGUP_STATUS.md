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

## 上游现状核对：上游已开机进桌面（2026-11-22 更正此前判断）

此前"上游只到白苹果 20%"的判断是**错的**——那读的是 fork 分叉时（origin 是孤立单提交
`a4ef4ed`，2026-11-07）的旧 README。抓取上游当前 `origin/main` 后确认：

- 上游 README 状态表：**Boot/lock screen/home screen/built-in apps = 80% 🟢**，
  备注 "Slow boot, occasional UI freezes"；Display/GPU = 70% 🟡（"Whole UI composited by
  the GPU"）；CPU 85% 🟢；Wi-Fi/调制解调器/音频均已在推进。上游**早已开机进桌面**，
  并有 `pandora_autoswipe`（EXPERIENCE：开机 45 s 自动解锁、翻页）作为无人值守桌面验证手段。
- 键盘：上游 README 标题写 "Xiaomi 17 Pro Max"，但按用户约束本机是小米17 Max `byron`
  （`ro.product.device=byron`），同芯片同 patch 集，机型名差异不影响技术判断。
- **关键对比结论**：上游 370 个内核补丁与 fork **逐一相同**（`comm` 差集为 0）；
  `mac/boot_ios.sh` 的 boot 参数也**一字不差**（`BASE`+`GPUARGS` 完全相同），fork 的差异
  只有 byron 适配（设备名/profile、extents 目录可配置、shim/profiles/docs、loader 重编）——
  也就是说"进桌面所需的内核与启动参数，我们手上已经和上游完全一样"。

因此白苹果**不是缺补丁或缺 boot 参数**，而是运行时/流程问题。上游 EXPERIENCE 第 1 节与
SWEET_LESSONS 第 13/29 条都写着：**第一次开机 lsd 重建 LaunchServices 数据库，停在苹果
标志 25 分钟以上（单核甚至 1 小时+）是正常的**，进入桌面靠耐心等待，不是靠某个开关。
而我们 PORT_CHECKLIST 一直用 `pandora_reboot_after` 60–120 s 短超时，fix15 内核日志也只到
121.6 s 就自动重启回安卓——**从未让首启跑够时间**。这是当前最可能、零成本、一次 RAM boot
即可验证的方向：拉长 `pandora_reboot_after` 到 ≥30 分钟跑一次，中途不操作，看是否自行进桌面；
若配合 `pandora_selftest`/`pandora_autoswipe` 还能在无人值守下确认解锁后的桌面。

下一步（待执行）：按上游做法做一次长时首启验证，不动镜像/内核/extents/boot 参数本身，
只把秒数拉长；期间按上游经验观察 lsd 是否持续在跑，结束时抓截图判定是否进桌面。

## 长测首启（fix15-long，2026-11-22 02:01:30 发起）

验证"上游已进桌面、我们只是等得不够"这一假设。不重编内核/镜像，直接复用 fix15 产物：
- 从 `shim/loader/wsl-out/loader-boot.img`（SHA `bdcfee4b`，fix15 全成果：GPU 插件/固件/trustcache）
  复制出 `loader-boot.long.img`（SHA `8b6f29ce`），仅在 cmdline 首个 NUL 填充处（偏移 0x3a174）
  追加 ` pandora_reboot_after=1800`（26 字节，填充区有 309 字节余量），其余字节完全不变。
  bootimg v4 header 只有 kernel_size、无内容校验，改动安全。
- `fastboot boot` 于 02:01:30 成功（Sending/Booting OKAY），15 s 后已离开 fastboot、内核在运行。
- 内核将在约 02:31（+1800 s）自动重启回安卓。全程 RAM boot，不刷分区、不改 AVB。
- 早上回来看：若手机已回安卓 → 抓 `kernel_ring` 看这 30 分钟 lsd/登录会话是否推进
  （重点：`exec lsd` 后是否有 `exec loginwindow` / SpringBoard 前台 / FB swap 持续增长）；
  若仍白苹果 → 同样抓日志确认 reboot_after 是否生效、卡在哪。

## fix15long 长测结果：等待假设被证伪，白苹果与时长无关（2026-11-22 早）

抓取：`captures/fix15long`，内核环 635309 字节 / flush 482 / 9359 行，日志时间到 **1800.863 s**
（参数 `pandora_reboot_after=1800` 确认生效并按时自重启，uptime 亦吻合）。截图
`pandora_shot_1_000249.png`（249 s）仍是**黑底白苹果 logo**。

**判定：等够 30 分钟依然白苹果，"只是等得不够/lsd 重建要 25 分钟"假设不成立。**

关键证据：
- `exec lsd` 15.886 s，之后**仅 18.180 s 两条 sandbox/AKS 调用**，此后 30 分钟再无 lsd 痕迹——
  lsd 不是"慢速重建数据库"，而是**停住/空转**；上游"首启 25 分钟"的经验在 byron 不成立。
- 60 s 之后**除了 348 次 `exec xpcproxy`（每 10 s 循环，sweetnoexec 基线）没有任何新进程**。
  `exec loginwindow` = 0，`exec SpringBoard` 13.705 s（有），但系统从此不再前进。
- 帧缓冲在 20–25 s 推进到 `shown 5`（真实渲染过），之后完全静止——与"SpringBoard 卡在首帧"一致。
- `UMD_INIT: failed to read nextsession dict / FAILED to Set Foreground ID`（13.452 s，
  curFG 502 / BootedUser 501）仍在——**loginwindow 不启动的直接原因**：会话无法置前台。
  该现象 fix13/14/15/long 四次完全一致，是稳定根因候选。
- 无新 panic（`panic(` = 0）；`CRASH driverkitd` 4 次、`DumpPanic` 1 次均为早期连带。

**下一步方向**：放弃"等待"路线。收敛到 `UMD_INIT` 前台会话失败这一稳定根因：
查 usermanagerd 为何取不到 nextsession dict（curFG 502 vs BootedUser 501 不匹配），
对照上游 patches 中与 usermanagerd / multiuser / commpage / keybag 相关的补丁和 root 文件
（systembag.kb、容器目录），确认 byron 是否缺某个 root 文件导致会话字典缺失。

## fix15long 日志深挖：修正"loginwindow/前台会话是根因"的判断（2026-11-22 06:40）

逐行深挖 fix15long 内核日志后，**撤回**此前"UMD 前台会话失败 → loginwindow 不启动是白苹果根因"
的推断。三点反证：

1. **iOS 16（iPhone）根本没有 `loginwindow` 进程/文件**。全 root 镜像 321300 个文件里
   grep 不到任何 `loginwindow` 路径；登录/锁屏由 SpringBoard + CheckerBoard +
   PurpleBuddy(CheckerBoardRemoteSetup.app) 实现。`exec loginwindow = 0` 是**正常的**，不是故障。
2. **UMD_INIT 实际成功了**：`FAILED to Set Foreground ID` 之后紧接着
   `booting with default id to be Loginwindow UID` → `Regular mode Setup for user:501`
   → `Loaded persona manifest` → `setup kernel personas` → `DONE EARLYBOOT SETUP` → `DONE UMD_INIT`。
   这是回退到默认 UID 的正常路径，不是致命错误。session 表 `UserSessionOther`/curFG 502
   在 fix13/14/15/long 四次一致，属稳定基线。
3. **GPU/Metal 也正常**：backboardd 14.898s `open AGXAccelerator type 16711 -> 0x0`（client 0），
   20.058s `type 1 -> 0xe00002c7` 只是不支持的可选 user client，非致命；之后 surface 创建、swap
   正常，`pandora-metal wrapped` 计数在推进，真实渲染发生。

**日志真正显示的卡点**：系统启动到 20–25 秒后**完全静止**。最后一个用户态进展是 backboardd
在 ~25.5s 的 pandora-metal 统计（渲染桥接在工作），此后 30 分钟内只有内核周期诊断
（每 30 s `PANDORA IO`、触摸报告 0 touch）。磁盘每 30 s 写 ~400 KB 是 ReportCrash 循环写崩溃
日志（bluetoothd/fairplayd 每 10 s sweetnoexec 被杀 → exec xpcproxy 重启 → 再被杀），
不是进展。**没有任何新的 exec、SpringBoard 无任何前进**——SpringBoard 卡在首帧白苹果。

结论：白苹果卡在 **SpringBoard 首启阶段**（渲染已通、会话服务已起，但 SpringBoard 没有继续
走完 setup → 解锁 → 桌面）。内核日志看不到 SpringBoard 内部为何停住，需要 unified log /
SpringBoard 侧日志。下一步应聚焦拿到 SpringBoard 的实际卡点（这是 fix15long 之前 unified log
数据侧缺 tracev3 的要害），而不是继续攻已排除的会话/GPU 方向。

## 突破：unified log 链路修复 + 首次拿到 SpringBoard 日志（2026-11-22 06:45）

### 1. 抓取脚本根因（已修）
此前 fix13/14/15/long 的 archive 全部缺 tracev3，根因**不是**路径/压缩/解析器，而是
`tools/ioslog_fetch.py` 的 **mtime 过滤 bug**：iOS 16 写 tracev3 时把 mtime 留在 HFS 纪元
（≈1970-01-01，实测 5 个文件 mtime 全是 `01-01 00:01`~`00:29`），而脚本用 `version.plist` 的
真实时间（2026）算 `since`，导致每个真日志都比 since 早 56 年 → 全被当 "too old" 跳过。
- 用 `tools/diag_diagnostics.py --phone`（只读 pinfile）证实：手机 `Persist/` 下确有 5 个
  tracev3（共 ~3MB），未压缩、路径正常，全部 `SKIP-too-old`。
- 修复：`ioslog_fetch.py` 对 `mtime < 1971` 的 trace 文件视为「未设置/本次启动」豁免时间过滤。
- 端到端验证 `ioslog_fetch.py fix15long2 --minutes 60 --parse`：**抓到 5 个 trace，解析出
  `ul_fix15long2.jsonl` 107424 行 / 80MB**——历史上首次拿到真正的 unified log 正文。

### 2. unified log 首次揭示的白苹果机制（重大修正）
此前内核日志判断「SpringBoard 卡在首帧静止」**不准确**。unified log（覆盖 boot 后 10.9–67.5 s）
显示的是**崩溃重启循环**：
- `exec SpringBoard` 共 **5 次**：11.239 → 14.412 → 14.535 → 15.428 → 19.613 s
  （每 1–4 s 重启一次），对应 `exec backboardd` 5 次。每次 SpringBoard 起来 → 连上 backboardd
  （`System shell connected ... com.apple.springboard`）→ backboardd 显示 Apple Logo
  （`Current bootUI is an Apple Logo` + `Presenting overlay: BKDisplayRenderOverlayAppleLogo`）→
  几秒后 `system activity assertion timed out: BKBootUIPresenter`（4 次）→ SpringBoard 退出 → 重启。
- `true SpringBoard.app logs = 0`：SpringBoard 自己一条内部日志都没写；**没有它的崩溃报告**、
  没有 watchdog/jetsam 杀死记录 → 它是**主动退出/初始化失败退出**，不是被杀。
- backboardd 反复报 `updateOverlay: No explicit screen owner`——SpringBoard 从未真正接管屏幕。
- 伴随可疑错误：`securityd: homeDirPath starts with /var/empty`（用户 home 不对）、
  `All kCFPreferencesCurrentUser domains ... will be volatile`（偏好无法持久化）、
  `volume does not support data protection`、`keychain-2.db - No such file or directory`、
  大量 `failed activation ... error = 1: Operation not permitted`（XPC 权限）。

### 3. 下一步
白苹果 = **SpringBoard 在 user session 初始化阶段反复失败退出**。由于 SpringBoard 自身不写日志，
下一步看它崩溃时是否留下 `.ips` 崩溃报告（在 `/private/var/mobile/Library/Logs/CrashReporter/`，
需从手机镜像单独抓），或对照上游 patches 中 SpringBoard 首启/激活/容器相关的处理。

## 06:47–07:11 深挖 unified log + 三方向电脑端调研（含对上段结论的重大修正）

### 新工具（只读，不入库实时数据）
- `tools/ul_probe.py` 新增 3 个模式：`life`（exec/exit 生命周期）、`bootui`（bootUI/assert/ALS/swap）、
  `sim`（Software renderer/Simulating crash/ReportCrash 合成）。
- 新增 `tools/ul_sb_timeline.py`：按进程名而非 pid 抓 SpringBoard 链路（**重要更正：pid 25 是
  runningboardd，pid 26 才是 SpringBoard**，旧 `sb` 模式按 pid==25 抓错了对象）。
- 新增 `tools/crash_fetch.py`：只读从手机 pinned root 镜像（`adb` + `pinfile rawreadat`，经 FBE
  之下裸读）列出/dump `/private/var/mobile/Library/Logs/CrashReporter/` 的 `.ips`。

### ⚠️ 对上一版"崩溃循环触发器"结论的修正（2026-11-22 07:11，作废原定性）
上一版本段把 `Software renderer! Simulating crash!` 定性为"白苹果反复重启循环的直接触发器"。
经逐行核对时间线 + 三方向交叉调研，**该定性作废**。三点硬反证：
1. 那些 `launchd: exited with exit reason (namespace 9 code 0xe) OS_REASON_EXEC` 全是
   **`xpcproxy`**（launchd 每次 launch/exec 的临时代理）的正常退出，是基线噪声，不是
   SpringBoard/backboardd 崩溃。
2. `Software renderer! Simulating crash!` 只有 **3 次**（25.713 / 29.083 / 30.466 s），
   32.8 s 最后一次 `exec backboardd` 后**再无 crash**——不是无限循环。
3. 34.5 s 起系统实际**全面启动**：`System shell connected ... SpringBoard.app` ×5、
   `searchd: SpringBoard is unlocked`、大量 daemon 注册 activity、67 s 仍有 `PANDORA GPU IRQ`。
   `SpringBoard started = NO`（mediaserverd ×5）经核对元数据为
   `subsystem=com.apple.voicetrigger` 的普通 Default 日志，全文无 YES，**是语音触发框架噪声，
   不是 SpringBoard 启动状态**。
→ **系统并没有"起不来"，而是起来了、已解锁，但屏幕停在 Apple Logo。**

### 真正的卡点：Apple Logo overlay 从未被移除（呈现/屏幕归属层，非渲染能力）
- 全日志 `removeOverlay` = **0**；`Current bootUI is an Apple Logo` 与
  `Presenting overlay: <BKDisplayRenderOverlayAppleLogo level -1/2999>` 反复出现；
  `updateOverlay: No explicit screen owner` **15 次**；
  `system activity assertion timed out: BKBootUIPresenter` **4 次**。
- 34.564 s backboardd 明说 `Enabling framebuffer changes on display (1) because we don't have
  any overlays that require disabled updates`，随后立刻又 `Presenting overlay: AppleLogo` →
  `updateOverlay: No explicit screen owner` → `addOverlay waiting for activity assertion`
  （assertion 实际 0.0005 s 就拿到，并非卡在 assertion）。
- **判断**：SpringBoard 进程已连上 shell、已解锁，但没成为 explicit screen owner，
  BKBootUIPresenter 的 assertion 超时，backboardd 因此不移除 Apple Logo overlay。
  这是 backboardd ↔ SpringBoard 的**纯用户态角色协商**，全部 XNU 补丁无内核侧处理，
  boot-arg/ADT 都无法直接让 SpringBoard 声明 started 或设置 screen owner。
  证据等级：现象中高；"为何没成为 screen owner"低（SpringBoard 自身日志为 0）。

### 崩溃报告侧（只读抓取结果）
`crash_fetch.py` 从 pinned root 镜像列出 `/private/var/mobile/Library/Logs/CrashReporter/`
共 76 个 `.ips`，**全部是 `bluetoothd` / `fairplayd.H2`**（`sweetnoexec` 基线里被 SIGKILL
的进程），**没有 SpringBoard / backboardd / kernel 的崩溃报告**——无真实 crash dump。

### 三方向电脑端调研结论（07:0x–07:11，均未改文件、未动真机）

#### 方向1 — Software renderer / `default.pipelinelib`：**pipelinelib 不是诱因**
- **否证** pipelinelib 缺失假设：HFS 直读证实 `/System/Library/Frameworks/QuartzCore.framework/
  default.pipelinelib` 存在且完整（functions / pipelines.desc / pipelines.g4–g15）。
  `docs/GPU_PLAN.md:37,162`：该库是 AGX 机器码用不上；设备名不认识时 QuartzCore 自动回退
  AIR 现场编译（苹果自己的虚拟机也走这条路）。内核日志 `pipeline_libraries_made +33`、
  `pipelines_linked +17`、`command_buffers_submitted +20` 证明回退后真实渲染发生。
- **判定来源（强推断）**：3 次 `Software renderer! Simulating crash!` 与内核
  `IOK backboardd: open AGXAccelerator type 1 -> 0xe00002c7 (kIOReturnUnsupported)`
  **时间戳 3/3 精确对齐**。该条 UnifiedLog 元数据 `subsystem=com.apple.coreanimation` /
  `category=WindowServer` / `library=QuartzCore.framework` / `message_flags=[SharedCache,...]`，
  是系统原生字符串非注入。返回点 `xnu/patches/0184-pandora-gpu-metal-accelerator.patch:25`
  `if (type != PANDORA_GPU_OPEN_TYPE=0x4147) return kIOReturnUnsupported;`，
  运行时源码 `wsl/PandoraAdrenoGpu.cpp:550-551`。
- type=1 与 0x4147 **共用同一 AGXDeviceUserClient 与 struct-in/struct-out ABI**
  （`PandoraAdrenoGpu.cpp:586-644`、`:389-415`），接口本身兼容；风险是 CA 可能按 Apple
  原生 AGX ABI 发 externalMethod（selector 编号语义不同）被误当 method number。
- **下一步（未做）**：方案 A 先补 `docs/GPU_PLAN.md:171` 列的 4 个未实现能力查询
  （`isMsaa32bSupported` / `isFloat32FilteringSupported` / `supportsASTCTextureCompression` /
  `supportsBCTextureCompression`），看 crash 是否消失；方案 B 才让 type=1 通过并加 selector 日志。
  **验收指标是 Simulating crash 是否消失、type=1 是否仍返回 0xe00002c7，不是 overlay/started
  （二者已被证伪为非因果）。**

#### 方向2 — ALS 等待：**非致命，正式结案**
- **直证**：`ALS sync ready in 0.00179s`（25.714）在 timeout（25.712）后仅 2 ms 完成；
  `ALS is not supported on this device -> ignore DisplayBrightnessAuto` 是正常降级分支；
  `overall 5.274s` 吻合上游 `EXPERIENCE.md:42` 已知"等 ALS ~5 s 超时"常态，上游照样进桌面。
- 无 boot-arg / ADT override 可跳过（`CBU_ShouldWaitForALS` 不在任何源码/补丁，是闭源 backboardd
  逻辑；ADT 白名单仅 10 个数值键，加 ALS 节点还需 IOKit personality = 内核改动）。
  `wdt=-1` / `BKNoWatchdogs` / `wdt_test=no_user_checkin` byron 已全部具备。
- ALS 与 crash 的 1 ms 相邻是同阶段独立事件非因果（ALS 25.714 才 sync ready，crash 25.713 已发生）。
- **结论：ALS 非根因（高置信），不作为改动目标。**

#### 方向3 — GPU "client window 耗尽"：**不成立，是 boot-arg 注入问题**
- **勘误**：`0xe00002d8` = **`kIOReturnNotReady`**（`IOReturn.h` `iokit_common_err(0x2d8)`），
  **不是** kIOReturnNoResources（0xe00002be），更不是"window 耗尽"。直接来源
  `wsl/PandoraAdrenoGpu.cpp:553-556`：`pandora_gpu_open()` 返回 -1 时
  `IOLog("... open refused (GPU not up or no free window)")` + `return kIOReturnNotReady`
  ——把 `!gpu_ready` 和"窗口满"合并成同一条模糊日志，是误判来源。
- 全日志 `open refused` 仅 1 次（28.614 s）；5 次成功的 type 16711 open **全是 client 0 且每次
  紧跟 `client 0 closed`**，从未出现 client 1..14，`GPU_MAX_CLIENTS=15` 从未占满。
- **真正原因**：`pandora_gpu.c:4030-4037` `pandora_gpu_init()` 读 boot-arg `pandora_gpu=N`，
  `N<=0 直接 return` → GPU hw_init 不跑 → `gpu_ready=false`。逐 boot 核对：5 个 boot 中
  BDA71D4F(24.581s)、8B465632(28.584s) **缺 `pandora_gpu=15`**，正好对应 25.7 s 第一次 crash
  与 28.614 s open refused；其余含该参数则 GPU 正常。
- 后期 GPU 完全正常（32.793 s `client 0 opened -> 0x0`、34.569 s GPU IRQ），
  **0xe00002d8 是早期瞬态、不致命**。不需要 kernel patch + CI 重编修"耗尽"（该问题不存在）。
- **勘误（dir1 撤回两条附带推断）**：`gpu 0` 不是 CPU 渲染指标——`gpuFrame=true` 唯一置位在
  `0096-fuxi-adreno.patch:2911-2918` 的 `#if defined(FUXI)` 内，byron 是 PANDORA 平台该段不编译，
  `gpuFrame` 结构性恒 false；`pandora_gpu_metal=1` 5/5 boot 均存在，"依赖不一致"担心不成立。

### 下一步建议（修正后）
1. **主攻 overlay / screen owner 交接**（真正卡点）：查 `No explicit screen owner` 与
   `BKBootUIPresenter` assertion 超时的触发条件，为何 SpringBoard shell 连上且解锁却没成为
   explicit screen owner。纯用户态，需反汇编/符号化或对照上游；无现成 boot-arg/ADT。
2. **次攻方向1 方案 A**（低成本、插件层）：补 4 个 MTLDevice 能力查询答案，验证 Simulating
   crash 是否消失。与 overlay 是两条**独立线**，不可互相作为验收指标。
3. **低成本附带**：修 `pandora_gpu=15` boot-arg 注入稳定性，消除早期 open refused 瞬态。
4. **结案不做**：ALS 方向、pipelinelib 拷贝、"窗口耗尽"内核 patch + 重编。

---

## 2026-11-22 主攻 overlay/screen owner：日志侧决定性实证

### 新工具
- `tools/ul_probe.py` 新增 `owner` 模式：一次性输出 Apple Logo overlay / screen-owner 交接链、
  按 boot_uuid 分组摘要（每 boot 的 no-owner/removeOverlay 计数 + gpu15 有无）、SpringBoard 静默统计。

### 实证 1：失败是确定性的，与 GPU/竞态无关
按 `boot_uuid` 分组（`ul_fix15long2.jsonl`，107424 行 / 5 个 boot）：
```
BDA71D4F  14004 行  NO-gpu15  no-owner=3  removeOverlay=0
7E7F019D  12685 行  gpu15     no-owner=3  removeOverlay=0
7127CAB2  14805 行  gpu15     no-owner=3  removeOverlay=0
8B465632  12597 行  NO-gpu15  no-owner=3  removeOverlay=0
39FA7311  53333 行  gpu15     no-owner=3  removeOverlay=0   （持续到 67 s）
```
**每个 boot 都是 no-owner=3 / removeOverlay=0**，与 gpu15 有无无关。
→ overlay 交接失败是**结构性、确定性**缺陷，不是竞态、不是 GPU window、不是时序问题。

### 实证 2：SpringBoard 完全静默（关键）
- `exec SpringBoard` **5 次**（11.239/14.412/14.535/15.428/19.613 s），
  但全日志 process/image/library/subsystem/category **全字段 SpringBoard 自身日志 = 0 行**。
- 对照：`/usr/libexec/backboardd` 17733 行，`/usr/libexec/runningboardd` 3680 行。
- SpringBoard 连上了 system shell socket（backboardd 侧 5 次 `System shell connected ... pid 25/26`），
  但它自己一条 unified log 都不写——**进程被 exec、socket 连上，但主初始化没有真正执行到写日志/声明
  screen owner 的阶段**。
- 内核侧确认 SpringBoard 二进制存在且合法：`/System/Library/CoreServices/SpringBoard.app/SpringBoard`
  cnid 278950，112960 B Mach-O stub（`__PAGEZERO`，真身在 dyld shared cache）。
  不是文件缺失。

### 实证 3：shell 连上与 screen-owner 失败精确同刻
每次 `System shell connected` / `systemShellChangedWithPrimary` 的同一毫秒，紧跟
`updateOverlay: No explicit screen owner` + `addOverlay(...): Overlay pending or already`；
`BKBootUIPresenter` activity assertion 超时 4 次。
→ backboardd 在 shell-changed 回调里检查 explicit screen owner 失败 → 保留 Apple Logo overlay。

### 实证 4：display swap_end 错误（每 boot 固定 3 条）
`backboardd: display 2/3/4 swap_end returned error 0xFFFFFFFFE00002D7` ×15（5 boot × 3）。
内核侧 `SWEET FB: swap wait ... -> 0x0` 显示主 display swap 成功。
0xe00002d7 疑为 display 2/3/4 这些 secondary/不存在的 display 的正常失败，暂不作为根因，
记录备查（见代码侧 agent 复核）。

### 实证 5：镜像侧 home 配置正常；`/var/empty` 是误导线索（已排除）
- `/private/etc/passwd` 中 mobile 用户 home = `/var/mobile`（正确），
  `/private/var/mobile/Library/Preferences` 存在（cnid 3745），
  `/var -> private/var` 符号链接正确（11 B 相对链接）。→ 镜像打包无问题。
- **勘误**：日志里的 `homeDirPath starts with /var/empty` + 偏好 volatile（10 条）**只出现在
  `mDNSResponder` / `securityd` 两个系统 daemon**，是 `containermanagerd` 给 uid=-2
  （4294967294，"无用户"系统服务）建容器的**正常行为**，与 mobile(uid 501)/SpringBoard 无关。
  不能当作"SpringBoard home 被重定向"的证据，此线索排除。

### 实证 6：仓库零覆盖，上游不需要此处理
- 全仓（fork + upstream-ref 共 1145+ 文件）搜 `screen owner` / `screenowner` /
  `BKBootUIPresenter` / `removeOverlay` / `updateOverlay` / `bootUI`：
  **除本轮新增的日志探针工具外，源码/补丁/脚本/文档零命中**。
- upstream（README 80% 🟢、已进桌面）能正常移除 Apple Logo 却没有任何 screen-owner 处理代码
  → 说明**上游环境里 SpringBoard 正常初始化、自动成为 screen owner，无需补丁**。
  byron 卡点不在"缺某个 screen owner 补丁"，而在 **SpringBoard 自身没初始化完成**
  （与实证 2 的 0 自身日志一致）。内核/XNU 侧无此逻辑，boot-arg/ADT 也无法干预。

### 结论与下一步
- 白苹果 = **SpringBoard 进程 exec 了但内部初始化没跑完**（0 自身日志），
  因此既没声明 explicit screen owner、也没移除 Apple Logo overlay；backboardd 每 boot 都确定性地
  保留 Apple Logo。不是崩溃循环、不是 ALS、不是 pipelinelib、不是 GPU 耗尽、不是镜像损坏、
  不是缺补丁（上游同样无补丁但正常）。
- 下一步（**未执行，需用户拍板 + 真机 A/B**）：
  1. 上机抓 SpringBoard 的 crash/容器日志或反汇编其 screen-owner 声明路径（根因层，成本最高）；
  2. 代码侧 agent 正在查 fork/upstream 是否有可复用的用户态/screen-owner 修正（见后续补充）；
  3. `/var/empty` home 线索已排除，不作为改动方向。

## 2026-11-22 收尾：首启 buddy 状态未跳过（根因方向收敛，实证矛盾）

### 新实证：系统每 boot 确定性认为"仍在首启"
核实 `ul_fix15long2.jsonl`（agent 报告 + 我逐条复核）：
- `remindd: DAAgentManager: Device PastBuddy is 0` ×10（5 boot ×2）；
- `remindd: RDAccountInitializer: We are still in buddy` + `Can't start yet, device is still in buddy` ×15（5 boot ×3）；
- `backboardd: First boot: systemShellWillBootstrap` ×5（每 boot 一次）——与 `System shell connected` 同刻。
→ **每个 boot 都确定性地处于"首启 / Setup Assistant（buddy）未完成"状态**，
这是 SpringBoard 不成为 explicit screen owner、overlay 不移除的上游原因。

### 决定性矛盾：跳过首启的偏好在镜像里写得正确，但运行时没生效
用 HFS 只读解析 `/opt/work/iosroot.img` 核实 `tools/imgbuild/sweet-root-tweaks.py` 的产出：
```
/private/var/mobile/Library/Preferences/com.apple.purplebuddy.plist (130 B):
    SetupDone=True, SetupFinishedAllSteps=True, SetupVersion=11
/private/var/mobile/Library/Preferences/com.apple.migration.plist (145 B):
    LastSystemVersion=20H392
com.apple.purplebuddy.notbackedup.plist (257 B) 存在；springboard.plist (171 B) 存在
（activation() 另在 mobileactivationd 容器写 data_ark.plist: -ActivationState=Activated）
```
即 `sweet-root-tweaks.py:57-61` 的 `merge_pref` **确实把跳过首启的偏好写进了镜像**。
但运行时 `Device PastBuddy is 0` / `still in buddy` 每 boot 复现，全日志搜 `SetupDone` /
`ActivationState` / `DataMigration` 命中 **0**（没有任何进程读到/提到这些键）。
→ **"镜像写了、运行时没读到"是实证矛盾**：根因方向从"SpringBoard 静默"收敛为
**首启跳过偏好未被 cfprefsd / DA 框架加载**（可能 owner/mode、偏好域路径或 container 解析问题）。
这是可动手的明确方向，但具体是哪一环失效，静态材料无法确定，需上机 A/B。

### 勘误（更正 agent 报告的一处归因）
agent 把 `/var/empty` → volatile prefs 当作"偏好未生效"的根因证据；我已核实那 10 条
`homeDirPath starts with /var/empty` **只来自 mDNSResponder/securityd 系统 daemon（uid=-2）的正常容器行为**，
与 mobile(501)/SpringBoard 无关。但"偏好未生效"本身由上面**镜像文件正确 vs 运行时 buddy=0 的直接矛盾**
独立成立，不依赖 `/var/empty` 那条。两条要分开看。

### swap_end 定性（agent 复核，采纳）
`0xe00002d7 = kIOReturnOffline`（非 NotReady）。内核 `IOMobileFramebufferCreateDisplayList: FB Count = 1`
（×60），display 2/3/4 mode=(0x0) 无有效模式，是 backboardd 枚举的虚拟/占位屏；
`mkadt_pandora.py` 只生成 1 个 disp0 节点。swap_end Offline 是良性预期，**与 overlay 无因果，不追**。

### 新的下游症状（功能层确证 owner 缺失）
`no client connection for port 0x4xxx` 共 10973 条（39FA boot 9894 / 7127 boot 1069），
紧跟 `SWEET HID: touch ... down` —— 内核触摸事件到了，backboardd 找不到 client 连接投递。
端口名每 boot 不同（动态 Mach port）。这是"无 screen owner / HID client 未注册"的功能层表征，
把 owner 缺失从一条日志升级为"屏幕既不能接管、也不能收输入"的实证。

### 证据等级与下一步（未执行，需上机 A/B）
- 实证：buddy 状态每 boot=0、镜像偏好写得正确、运行时未读到、FB Count=1、触摸投递无主。
- 强推断（因果未证）：首启偏好未加载 → SpringBoard 停在 buddy 初始化 → 不声明 screen owner
  → overlay 不移除 + 自身日志 0 行。
- 最小 A/B（低优先先做）：核对/修正 mobile(501) home 与 Preferences 目录 owner/mode，重建镜像跑一次；
  验收指标：`Device PastBuddy` 是否变 1、`still in buddy` 是否消失、`removeOverlay` 是否 >0。
- 不要做：改 0184 / boot args / swap_end / 重做 ALS/pipelinelib/窗口耗尽（均与本卡点无因果）。

## 2026-11-22 A/B 前提核验：owner/mode 无误，结论修正（电脑端只读，未改镜像）

上一轮最小 A/B 的第一步是"核对/修正 mobile(501) home 与 Preferences 目录 owner/mode"。本轮在**已构建镜像
`/opt/work/iosroot.img`** 上做了纯只读核验（新增 `tools/imgbuild/check_owner.py`，直接读 HFS catalog 的
BSD info：ownerID/groupID/fileMode），结论是**前提不成立，不做任何 owner/mode 修改，不重建镜像，不刷机**。

### 实证 1：关键路径 owner/mode 全部正确
```
/private/var/mobile                          501:501 0711   (cryptex 原生值，正确)
/private/var/mobile/Library                  501:501 0711   (同上)
/private/var/mobile/Library/Preferences      501:501 0755   OK
/private/var/mobile/Library/Preferences/com.apple.purplebuddy.plist  501:501 0600  OK
/private/var/mobile/Library/Preferences/com.apple.migration.plist    501:501 0600  OK
/private/var/mobile/Library/Preferences/com.apple.springboard.plist  501:501 0600  OK
```
0711 = owner rwx / group x / other x，是 iOS mobile home 的原生 mode；owner(501) 可正常遍历读取。
上一轮 A/B 里"0711 需改 0755"的假设是我凭空设的期望值，**不是故障**——已把工具里的 EXPECT 修正为 0711。
→ **owner/mode 这条 A/B 分支证伪，不能靠改权限修好白苹果。**

### 实证 2：偏好内容与 marker 齐全，无覆盖冲突
dump 镜像内 plist（check_owner.py --cat）确认：
- `com.apple.purplebuddy.plist`: `SetupDone=True, SetupFinishedAllSteps=True, SetupVersion=11, daemonizeNeedsToRun=False`；
- `com.apple.migration.plist`: `LastSystemVersion=20H392` + `SyntheticDidUpgrade=False`；
- `com.apple.purplebuddy.notbackedup.plist`: 七个 mini-buddy 开关全 False；
- 无 `ByHost` 目录（cfprefsd 无 byhost 覆盖）；`.GlobalPreferences` 只有语言/区域；
- `SetupAssistant.framework/com.apple.purplebuddy.plist` 是 logging 子系统配置（DEFAULT-OPTIONS/TTL），
  **不是偏好默认值**，不含 `SetupDone=NO`，不构成冲突。

### 实证 3（重要修正）：偏好域被读取，但不同进程对 buddy 状态判定相反
上一轮结论"全日志搜 SetupDone 命中 0 = 偏好完全没被加载"**过强，需修正**。同一 boot 25.66–25.79 s 时间线：
```
25.663 nanoregistryd  notification com.apple.purplebuddy.setupexited.enabled prefs value: 0
25.663 nanoregistryd  enabling launch notification com.apple.purplebuddy.setupexited
25.663 nanoregistryd  notification com.apple.purplebuddy.setupexited.enabled prefs value: 2   <- 域被读写
25.739 remindd        DADBuddyStateObserver: Start observing buddy finished notification.
25.757 remindd        RDAccountInitializer: We are still in buddy
25.758 remindd        DAAgentManager: Device PastBuddy is 0
25.789 cloudpaird     DeviceManager buddy is done            <- 与 remindd 相反
```
5/5 boot 同构。`nanoregistryd` 读到了 `com.apple.purplebuddy.setupexited.enabled`（0→2），说明 **cfprefsd
确实在处理 com.apple.purplebuddy 偏好域**；`cloudpaird` 判定 `buddy is done`，而 `remindd` 的 DataAccess
框架判定 `PastBuddy is 0`。两者用的判定源不同——问题从"偏好没加载"收敛为
**"DA 框架判定 buddy 完成所依据的那一个状态源没被置位"**，具体是哪个源（某个通知 marker /
`/private/var/buddy` 空目录里的文件 / data_ark 另一字段）静态材料无法确定。

### 结论与下一步（未执行）
- **本轮不改镜像、不刷机**：owner/mode 正确，plist 正确，改权限的 A/B 分支已证伪。
- `tools/imgbuild/check_owner.py` 固化为只读自检工具：默认列关键路径 uid/gid/mode + 判定，`--cat` dump 偏好内容。
- 回归：`test_port_tools.py` 91/0 绿；两文件 py_compile 通过；仅提交工具+文档，实时日志/镜像未入库。
- 真机 A/B（低优先，需用户在场）：若要继续验证"DA 判定源"假设，方向是 buddy-done 通知 marker，
  而非 owner/mode；但收益低、成本高（上次 boot 已证实系统确定性停在 buddy），**建议先搁置**。
- 不要做（沿用上一轮）：改 0184 / boot args / swap_end / 重做 ALS/pipelinelib/窗口耗尽。

## 2026-11-22 对照上游：别人是怎么跳过首启 / 验证进桌面的（只读研究，未改内核/镜像）

用户要求"看别人怎么做"。读了 fork/upstream-ref 的 `docs/EXPERIENCE.md`、`SWEET_LESSONS.md`、
`device/DT_FINDINGS.md`，并联网核对三个源头项目（ios-sweet / data-a-live / ios-fuxi）的 README。
结论：**我们没有缺任何"进桌面"的补丁或开关，反而发现一个更可靠的验证方向。**

### 上游做法逐条对照
| 环节 | 上游怎么做 | byron 现状 | 是否差异 |
|---|---|---|---|
| 跳过 Setup Assistant / buddy | `sweet-root-tweaks.py` 写配置文件（SetupDone 等） | 同一脚本、同一逻辑，镜像实测写对（见上节） | **一致，非差异** |
| 激活 | seed data_ark 激活状态 | 同一脚本，已写 | 一致 |
| 首次开机 root 可写 | boot args 带 `ufsrw=1 rootrw=1`（HFS+ 日志区首次可写挂载才初始化） | `ios_test.sh BASE` 已含 | 一致 |
| 首次 lsd 重建慢 | 上游说白苹果停 25 分钟正常 | 长测 30 分钟仍白苹果，已证伪 | 上游经验不适用 |
| GPU/Metal | Turnip + NativeMetal 插件 + metal2vulkan | fork 与 upstream 366 个补丁完全相同、boot args 一字不差 | 一致 |
| 验证进桌面 | `pandora_selftest` / `pandora_autoswipe`（开机自动按键上滑翻页，无人值守） | 补丁 0142/0224 + 源码都在内核里 | **一致，机制已具备** |

### 决定性对照证据（此前被忽略）
`device/DT_FINDINGS.md:119`（2026-10-22，补丁 0128–0142，t17–t19）：内核自检通过
`sweet_hid_touch` 从底边上滑，**iOS 真实进入了主屏幕**（小组件/图标/Dock），下拉开了控制中心，
亮度滑块拖动生效。`pandora_autoswipe.c` 注释同样写明测试机无密码、backboardd 约 20 s 出首帧。
→ **10 月这套系统（无 GPU/Metal）能完整进桌面、过 buddy、声明 screen owner。**
→ 11 月 fix14/15 打通 GPU/Metal 后反而白苹果。结合上三节（owner/mode 正确、偏好被读取、
不同进程 buddy 判定相反），白苹果更可能是 **GPU/渲染链路影响 SpringBoard 首帧/屏幕接管**，
而不是 buddy 偏好未加载。证据等级：中（对照成立，但缺当次 GPU boot 的桌面判定实测）。

### 下一步：低成本真机 A/B（无需重编内核/镜像，需用户在场）
用现有 fix15 全成果 loader（`loader-boot.img`，含 autoswipe 补丁）+ 在 boot args 追加
`pandora_autoswipe=SECS`（例如 90），长测一次并抓缩略图/截图：
- 若自动上滑后能翻动主屏幕 → 系统其实已进桌面，问题只在 **Apple Logo overlay 没移除**（显示层）；
- 若上滑完全无反应 → SpringBoard 确实卡在首启（回到 buddy 方向）。
该 A/B 直接区分"显示层 vs 用户态卡死"两个根因分支，比改 owner/mode 或 buddy 偏好更有判别力，
且不改任何镜像/内核。另可对比：同一 loader 去掉 GPU 参数（纯 CPU 渲染）跑 autoswipe，
看是否重现 10 月进桌面结果，以验证"GPU 引入回归"假设。

### 落盘
- 仅追加本文档；无内核/镜像/工具改动，无实时数据入库。

## 2026-11-22 真机执行：无 GPU 对照 boot + AUTOSWIPE → GPU 回归假设证伪

用户要求"先用无 GPU 的方式跑看能不能进桌面"。本次**真机执行了**（Windows 本机，byron 19d05df2，
全程 `fastboot boot` RAM，不刷分区/不解锁/不改 AVB）。结论：**无 GPU 与带 GPU 白苹果完全同构，
GPU 不是白苹果原因；autoswipe 注入 104 次上滑仍进不了桌面 → SpringBoard 确实卡首启（用户态方向）。**

### 执行链（含本机环境修复，均为 byron 适配，保留原作者逻辑）
这台电脑被清理过，脚本写死的工具路径全失效，逐一修复：
- `D:/Android/platform-tools` 不存在 → 用第三方搞机助手的 adb/fastboot 33.0.1 + 全部 55 个 DLL 复制补齐。
- `tools/boot_ios.sh` 三处 byron 适配（均"保留原文+增补 byron"）：
  ① 机型检查 `ro.product.device` 接受 `byron`（真机 fastboot product 实测就是 `byron`，原 `=pandora` 会拒绝启动）；
  ② pinfile status 新格式 `pin_file=0 (0=pinned)`（原只认旧串 `pinned (GC move failures 0)`）；
  ③ `extents --json` 尾注 `# extents=N` 过滤（否则 json.load 报 Extra data）+ payload 脚本改用当前仓库
     动态 WSL 路径（原硬编码旧 `/mnt/d/work/ios_pandora`，把 payload 放进错仓库导致 loader build 找不到）。
- `tools/safe_boot.sh` 同步 pinfile status 新格式。
- NDK 目录已不存在，无法重编 loader → 新增 `tools/loader_repack.py`：从已验证的
  `wsl-out/Image` 取骨架 0x39000，拼入新 payload.bin，更新 image_size，用 mkbootimg_v4 打包。
  等价于 build.sh 的链接后步骤，绕过 NDK（loader C/汇编骨架跨 boot 不变，只有 payload 变）。

### 本次 boot 参数（无 GPU 对照）
KERNEL=/opt/work/kernel-agx/kernel.development.pandora（与 fix14/15 同一内核，隔离变量），
cmdline 398/607：`... pandora_reboot_after=240 pandora_autoswipe=90 pandora_autoswipe_at=45
pandora_fbdump=30 pandora_rtc_offset=... pandora_slot=a`，**无 pandora_gpu**。
dry-run 全链通过（pinned/extents/HFSX/payload/cmdline）。07:55:15 `fastboot boot` OKAY。
产品 `byron`（印证机型适配必须）。

### 内核日志实证（device/logs/cpu_control.txt，180KB）
- `28.2s PANDORA AUTOSWIPE: swiping the home screen for 90 s` → `71.8s 50 swipes` →
  `114.5s 100 swipes` → `118.6s done, 104 swipes`；大量 `SWEET HID touch down/up` 坐实事件送达。
- 内核层只有 5 次 `SWEET FB swap`（19.5–22.9s），之后到 240s 重启再无新帧提交 → 屏幕停在白苹果。
- `240.267s pandora_reboot_after=240 ... resetting` → reboot_after 生效（之前误判未生效）。
- fbdump 只在 21s 写 1 组（autoswipe 开始前），surface 帧是白苹果（cpu_control-surface.png）。

### unified log 实证（ul_cpu_control.jsonl，93MB/6 trace，本机只读抓自 pinned root 镜像）
关键计数 vs 带 GPU 的 fix15long2（几乎同构）：
| 指标 | 无 GPU(cpu_control) | 带 GPU(fix15long2) |
|---|---|---|
| SpringBoard exec | 6 | 5 |
| Apple Logo overlay | 12 | 10 |
| No explicit screen owner | 18 | 15 |
| BKBootUI timeout | 5 | 4 |
| still in buddy | 6 | 5 |
| removeOverlay | 0 | 0 |
SpringBoard exec 6 次（11.2/14.4/14.5/15.4/19.6s...）重启循环，自身 unified log 0 行；
25.7/29.0/30.4s 反复 Apple Logo overlay + No explicit screen owner；29.4s BKBootUIPresenter 超时。

### 意外发现（修正对照实验设计）
本次**没有** pandora_gpu 参数，但 backboardd 仍加载 pandora-metal 插件 TU_DEBUG=nocb、
`backboardd has a device`、`no pipeline library` / `native-metal device refused VkResult(-3)`。
→ Metal 用户态插件是默认加载的，与 pandora_gpu boot arg 无关（该 arg 只控制内核 AGX 硬件初始化）。
所以"去 GPU 参数 = 无 Metal 对照"这一设计前提不成立；但正因如此，两次行为同构更说明白苹果与 GPU 无关。

### 结论与方向
- **GPU 回归假设证伪**：有无 GPU 都白苹果、都 SpringBoard 重启循环、都无 screen owner、removeOverlay 恒 0。
- **显示层-only 假设也证伪**：autoswipe 真注入 104 次上滑，内核无新帧提交、桌面从未出现 → 不是"已进桌面只是 overlay 没移除"，而是 SpringBoard 真卡首启。
- 回到用户态 buddy 方向：DA 框架 PastBuddy/still-in-buddy 判定源未置位（见前几节），但 owner/mode 与偏好内容均已排除。
- 10 月 t18/t19 自检曾进主屏幕（device/DT_FINDINGS.md:119）与当前确定性卡 buddy 的差异仍未解释——
  当时是老内核/老镜像，可能是某次后续改动引入的用户态回归，静态材料无法进一步定位。
- 落盘：工具 boot_ios.sh/safe_boot.sh/loader_repack.py + 本文档；实时日志/镜像/截图未入库。
