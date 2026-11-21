# byron 新内核回来后的验证清单

这份文档只记录**等待 xnu CI 编译期间可以提前准备的工作**，以及内核产物回来后要按什么顺序验证。它不照抄上游在其它机型上的结果；所有判断都以小米 17 Max `byron` 真机日志为准。全程约束：`fastboot boot` RAM boot，不刷分区、不改 AVB。

## 当前卡点（fix10）

- 内核已经能启动，`launchd` / dyld cache / `SpringBoard` / `backboardd` 均起来，无内核 panic；截图仍是白苹果 Logo。
- 内核日志里有 `UMD_INIT: failed to read nextsession dict` 和 `UMD_INIT: FAILED to Set Foreground ID`，之后没有 `exec loginwindow`。
- `backboardd` 能找到 `IOAcceleratorES`（`0 found`），但找不到 `AGXAccelerator`（`none`），所以没有走到 Metal/AGX 设备发现。
- fix10 曾尝试用 `pandora_gpu_metal=1` 打开补丁 0184 的门控，但该参数在最终 cmdline 打印里被抹掉，AGX 没有注册。
- 已提交 `66718c4`：把 `PandoraAdrenoGpu` 的 AGX 发布改成无条件，并加诊断日志；CI run `44920089727` 正在重编内核。
- 当前 root 镜像缺 `NativeAdrenoMetal.bundle` / Turnip 插件。即使 AGX 出现，也只能证明内核侧设备发现打通；用户态 Metal 仍是后续独立项。

## 编译等待期已完成的准备

- `tools/byron_fetch_ci_kernel.py`：从指定 Actions run 下载 `xnu-kernel` artifact，解包并把 `kernel.development.pandora` 复制到目标路径，校验 Mach-O magic 和 SHA256。
- `tools/byron_capture.sh`：手机回到 Android 后，一键抓取 PANDORLG 内核环、iOS unified log、内核截图，并生成 `summary.txt`。只读，不做 rawwrite。
- `docs/byron/LIVE_BRINGUP_STATUS.md`：状态推进到 fix10 和当前 CI。

## 新内核回来后按顺序执行

### 1. 下载并核对内核

```bash
python3 tools/byron_fetch_ci_kernel.py 44920089727 /opt/work/kernel-agx \
  /opt/work/kernel-agx/kernel.development.pandora
python3 tools/pandora_log.py --help >/dev/null 2>&1 || true   # 仅确认工具存在
```

记录脚本打印的 SHA256。不要复用旧内核；旧内核的门控仍然是 `pandora_gpu_metal=1`。

### 2. 重新打包 payload / loader

沿用 fix10 的 extents 和 boot args；内核路径换成上面下载的文件。root extents 每次 rawwrite 后都会变化，必须用当前 `/data/local/tmp/iosroot.img` 重新采集，不能复用历史 JSON。

```bash
KERNEL=/opt/work/kernel-agx/kernel.development.pandora \
NAME=fix11 \
ADTFLAGS="--root-extents device/byron/extents/iosroot.json --log-extents device/byron/extents/ioslog.json" \
TRUSTCACHE="/path/to/static.trustcache /path/to/system.trustcache /path/to/app.trustcache" \
bash wsl/make_phone_payload.sh /opt/work/run-fix11 \
  "ufsrw=1 rootrw=1 launchd_unsecure_cache=1 unentitled_ios_sim_launch=1 ignition_level=1 wdt_test=no_user_checkin wdt=-1 sweetfb_hz=30 sweetfb_fill=1 sweetnoexec=bluetoothd,fairplayd.H2"

OUT=fix11 bash shim/loader/build_wsl.sh
fastboot boot shim/loader/wsl-out/loader-boot.img
```

如果 fix10 实际使用的 boot args 与上面不同，以 fix10 为准；这一轮唯一要变的是内核，**不要同时改用户态变量**，否则无法判断 AGX 是否生效。

### 3. 启动后抓日志

屏幕停下后，让用户长按电源回到 Android，确认 `sys.boot_completed=1`，然后：

```bash
tools/byron_capture.sh fix11 20
```

`summary.txt` 里重点看：

| 检查项 | 期望 | 含义 |
|---|---|---|
| `PANDORA GPU UC: AGX...` / `PandoraAdrenoGpu` | 出现 | 新补丁进入内核并被加载 |
| `IOK backboardd ... AGXAccelerator ... -> found` | 出现 | backboardd 能发现 AGX，fix10 的主要内核侧阻塞解除 |
| `IOAcceleratorES` | 仍是 `found` | 基线不回退 |
| `UMD_INIT: failed to read nextsession dict` | 仍可能出现 | 这是用户态登录会话问题，不是本轮内核补丁的目标 |
| `exec loginwindow` | 若仍缺失 | 说明白苹果卡点还有第二个用户态原因，继续按 byron 日志定位 |
| `panic(` / `CRASH driverkitd` | 不新增 | 确认补丁没有引入新崩溃 |
| `NativeAdrenoMetal` | 仍不出现 | 符合预期：root 镜像还没装插件，不能据此判定内核失败 |

### 4. 决策分支

- **AGX 被 backboardd 找到，但仍白苹果**：内核侧这一项通过；下一轮专查 `UMD_INIT` / `loginwindow` 用户态链路，不把 GPU 插件混进来。
- **AGX 仍 `none`**：先查内核 cmdline 和 `PandoraAdrenoGpu` 诊断日志，确认补丁是否真的编进内核；再考虑是否需要板级 ATD/DT 属性，不改用户态。
- **出现 panic 或 driverkitd 新崩溃**：回退到 `66718c4` 之前的内核，只保留诊断日志，重新定位。

## 约束

- 不执行 `fastboot flash`，不改 AVB，不做额外解锁。
- 实时采集的 `*.raw`、`*.img`、`ul_*.jsonl`、`pandora_shot_*.png`、`device/byron/extents/*.json` 不入库；仓库只保留步骤和结论。
