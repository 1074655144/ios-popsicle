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

## 06:47–07:0x 深挖 unified log：找到白苹果循环的直接触发器（重大发现）

### 新工具（只读，不入库实时数据）
- `tools/ul_probe.py` 新增 3 个模式：`life`（exec/exit 生命周期）、`bootui`（bootUI/assert/ALS/swap）、
  `sim`（Software renderer/Simulating crash/ReportCrash 合成）。
- 新增 `tools/ul_sb_timeline.py`：按进程名而非 pid 抓 SpringBoard 链路（**重要更正：pid 25 是
  runningboardd，pid 26 才是 SpringBoard**，旧 `sb` 模式按 pid==25 抓错了对象，把 runningboardd
  的日志误当 SpringBoard）。
- 新增 `tools/crash_fetch.py`：只读从手机 pinned root 镜像（`adb` + `pinfile rawreadat`，经 FBE
  之下裸读）列出/dump `/private/var/mobile/Library/Logs/CrashReporter/` 的 `.ips`。

### 决定性证据：CoreAnimation 主动模拟崩溃 = 重启循环触发器
统一日志时间线（1970 纪元 = boot 相对时间）显示反复出现的固定序列：
```
25.712  backboardd: (CBU_ShouldWaitForALS) error: timeout waiting for ALS arrival
25.712  backboardd: Current bootUI is an Apple Logo
25.712  backboardd: updateOverlay: No explicit screen owner
25.713  backboardd: CoreAnimation: Software renderer! Simulating crash!   <-- 主动模拟崩溃
25.800  launchd: exited with exit reason (namespace: 9 code: 0xe) - OS_REASON_EXEC
```
`Software renderer! Simulating crash!` 共 3 次（25.713 / 29.083 / 30.465 s），每次紧跟
launchd 的 `OS_REASON_EXEC` 退出，然后 SpringBoard/backboardd 重启（exec SpringBoard 5 次）。
**即：backboardd 的 CoreAnimation 判定自己跑在软件渲染器上，主动模拟一次 crash 来触发重启——
这就是"白苹果反复重启"的直接触发器**，解释了为什么每 1–4 秒 exec 一次 SpringBoard。

### GPU 状态的关键矛盾（内核日志 vs 统一日志）
- **内核环日志 fix15long**（第一次启动）GPU 是通的：14.898s `AGXAccelerator client 0 opened`,
  `open AGX type 16711 -> 0x0`；25.57s `pipeline_libraries_made +33`、`pipelines_linked +17`、
  `shader_modules_made +21`、`Autotune sysmem 11`、`command_buffers_submitted +20`——真实渲染发生。
- **但统一日志 fix15long2**（后续重启周期）显示 GPU 重新初始化时失败：
  - 27.783s `tu_device.cc:1752: cannot generate UUID (VK_ERROR_INITIALIZATION_FAILED)`
    （注意：**UUID 修复在第一次 boot 生效了**——内核日志里第一次没有此错；这是重启后的新实例）
  - 27.783s / 28.614s `native-metal: device refused: Vulkan(VkResultCode(-3))`
  - 28.614s `tu_knl_darwin.cc:130 IOServiceOpen(IOAcceleratorES,0x4147) failed: 0xe00002d8`
    （0xe00002d8 = kIOReturnNoResources / GPU client window 耗尽）
- **综合判断**：第一次 SpringBoard/backboardd 起来时 GPU 正常、渲染发生，但 CoreAnimation 在
  bootUI 阶段仍判定"软件渲染"（可能因 `pandora-metal refused: no pipeline library:
  default.pipelinelib` 预编译管线库缺失，QuartzCore 回退到现场编译 / 软件路径），于是主动
  `Simulating crash` → 重启；重启后 GPU client window 未及时释放，Vulkan 设备初始化失败，
  形成"软件渲染→crash→重启→GPU 耗尽"的恶性循环。这与"等 30 分钟 lsd 就能进桌面"假设被
  fix15long 证伪一致——根因不是慢，是**循环重启**。

### 崩溃报告侧（只读抓取结果）
`crash_fetch.py` 从 pinned root 镜像列出 `/private/var/mobile/Library/Logs/CrashReporter/`
共 76 个 `.ips`，**全部是 `bluetoothd` / `fairplayd.H2`**（`sweetnoexec` 基线里每 10 s 被 SIGKILL
的进程），**没有 SpringBoard / backboardd / kernel 的崩溃报告**。再次印证 SpringBoard 是
"Simulating crash 后主动 exit"，不是被 watchdog/jetsam 杀死或产生真实 crash dump。

### 下一步（三个候选方向，未擅改）
1. **消掉 `Software renderer` 判定**：查 `pandora-metal refused: no pipeline library:
   default.pipelinelib`——把预编译 pipeline library 放进 root，或让 QuartzCore 不因缺该库回退
   到软件渲染路径（对照上游 EXPERIENCE 的 Metal/plugin 部分，byron 未验证，需真机逐项做）。
2. **修 GPU client window 耗尽**：重启后 `IOServiceOpen 0xe00002d8`，查内核 `0xe00002d8` 来源
   与 client 释放路径（可能需 kernel patch + CI 重编，耗时长）。
3. **绕开 bootUI 的 ALS 等待**：`(CBU_ShouldWaitForALS) timeout waiting for ALS arrival` 后
   才走到 Simulating crash，查能否用 boot-arg/ADT 让设备声明 ALS 可用或跳过该等待。
优先级建议 1 > 3 > 2（1 可能一处修复即打破循环；2 需重编内核成本最高）。
