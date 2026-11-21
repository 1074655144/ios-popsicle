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
| fix8 | 当前运行 | 加入 `unentitled_ios_sim_launch=1 ignition_level=1 wdt_test=no_user_checkin wdt=-1 sweetfb_hz=30 sweetfb_fill=1 sweetnoexec=bluetoothd,fairplayd.H2` | `fastboot boot` 成功，屏幕/日志待确认 |

## fix7 关键日志（结论，不提交原始日志）

- `launchd_unsecure_cache=1` 生效：`Cache sent to launchd successfully`。
- `exec SpringBoard`、`exec backboardd` 成功；49 秒时 backboardd 完成 5 次 CPU 合成并点亮背光。
- 无 panic、无 `FATAL KEYBAG ERROR`。
- 13–205 秒 backboardd 持续查询 `IOAcceleratorES / AGXAccelerator`，结果均为 `none`；49.9 秒后没有新画面提交。
- 从 root 镜像取出的两张截图均为纯黑底白苹果 Logo，无进度条/锁屏/桌面。

## 当前产物（仅本机）

- `incoming/loader-boot.img`：fix8 loader（被 `.gitignore` 排除）。
- fix8 loader SHA256：`c8c85091a25d483f669246d34d708f9fe50a0405d602dbb77e467091cb7f7341`。
- fix8 payload SHA256：以本机 `wsl/make_phone_payload.sh` 输出的 `sha256sum` 为准；产物不入库。
- 真机 extents 每次 rawwrite 后都会变化，必须重采；历史 JSON 不作为资产提交。

## 下一步

1. 确认 fix8 当前屏幕：锁屏/桌面视为用户态首启通过；仍为苹果 Logo 则回安卓抓 fix8 日志。
2. 若仍卡 Logo，按 `[PHONE_DATA_CAPTURE.md](../PHONE_DATA_CAPTURE.md)` 第 5 节抓 `ioslog` + unified log + screenshot，再定位下一个用户态阻塞项。
3. 当前**没有**启用 GPU/Metal/音频等功能项；这些属于后续逐项按 byron 真机推进的范围，不照抄上游结果。

全程约束：小米17 Max `byron`；不刷分区、不改 AVB、不做额外解锁。
