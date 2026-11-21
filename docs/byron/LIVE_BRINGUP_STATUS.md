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
| fix9 / fix10 | `backboardd` 找到 `IOAcceleratorES`（`0 found`），但仍找不到 `AGXAccelerator`（`none`）；`pandora_gpu_metal=1` 未能保留到最终 cmdline | 补丁 0184 改为无条件发布 `AGXAccelerator`；提交 `66718c4`，触发 xnu CI run `44920089727` | 等待新内核编译 |

## fix7–fix10 关键日志结论（不提交原始日志）

- `launchd_unsecure_cache=1` 生效：`Cache sent to launchd successfully`。
- `exec SpringBoard`、`exec backboardd` 成功；fix7 中 backboardd 完成 5 次 CPU 合成并点亮背光。
- fix10 中 `backboardd` 能匹配到 `IOAcceleratorES`（`0 found`），但 `AGXAccelerator` 一直是 `none`，没有进入 Metal 设备发现。
- fix10 有 `UMD_INIT: failed to read nextsession dict`、`UMD_INIT: FAILED to Set Foreground ID`，之后没有 `exec loginwindow`；这是当前白苹果卡点的第二个可疑用户态阻塞项。
- fix10 有 `exec DumpPanic` 和一次 `CRASH driverkitd`，但没有新的内核 panic 行；截图仍是纯黑底白苹果 Logo。
- `bluetoothd` / `fairplayd.H2` 周期性重启，属于已设置的 `sweetnoexec` 基线，不是本轮新增阻塞。
- 当前 root 镜像未安装 `NativeAdrenoMetal.bundle` / Turnip；内核侧 AGX 打通后仍需单独处理用户态 Metal 插件。

## 当前产物（仅本机）

- `incoming/loader-boot.img`：fix8 loader（被 `.gitignore` 排除）。
- fix8 loader SHA256：`c8c85091a25d483f669246d34d708f9fe50a0405d602dbb77e467091cb7f7341`。
- fix8 payload SHA256：以本机 `wsl/make_phone_payload.sh` 输出的 `sha256sum` 为准；产物不入库。
- fix10 日志与截图：本地 `incoming/`，不入库。
- CI run `44920089727` 正在重编内核；监控脚本写在 `/tmp/watch_ci.sh`，结果写 `/tmp/ci_result.txt`。

## 下一步

详细可执行清单见 [POST_KERNEL_VALIDATION.md](POST_KERNEL_VALIDATION.md)。

1. 等 CI run `44920089727` 完成，用 `tools/byron_fetch_ci_kernel.py` 下载 `xnu-kernel` artifact 并核对 SHA256。
2. 只替换内核重新打包 payload / loader；沿用 fix10 的 extents 和 boot args，不同时改用户态变量。
3. `fastboot boot` 后回安卓，用 `bash tools/byron_capture.sh fix11 20` 抓内核环、unified log 和截图。
4. 优先确认 `AGXAccelerator` 是否从 `none` 变成 `found`；再判断 `UMD_INIT` / `loginwindow` 是否仍是白苹果卡点。
5. 若 AGX 已出现但仍卡 Logo，下一步专查登录会话链路；不要把 GPU 插件安装混进同一轮。

全程约束：小米17 Max `byron`；不刷分区、不改 AVB、不做额外解锁。
