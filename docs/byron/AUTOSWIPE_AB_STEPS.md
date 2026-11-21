# byron：AUTOSWIPE 桌面判定 A/B（执行步骤，需真机，未执行）

> 目的：一次 boot 区分白苹果的两个根因分支——**显示层（Apple Logo overlay 没移除，系统其实已进桌面）**
> 还是 **用户态卡死（SpringBoard 真卡在首启）**。依据见 `LIVE_BRINGUP_STATUS.md`
> "对照上游" 一节：2026-10-22 无 GPU 时自检曾真实进入主屏幕，11 月加 GPU 后白苹果。
>
> 全程 `fastboot boot` RAM boot，不刷分区、不解锁、不改 AVB。抓取产物留在 WSL，不入库。
> 本文件只是步骤，未在任何机器执行。

## 原理（为什么会得到判别）

`pandora_autoswipe`（内核补丁 0224）从开机 `pandora_autoswipe_at` 秒起，在内核线程里直接调用
`sweet_hid_touch`/`sweet_hid_key` 注入"按侧键亮屏 + 底部上滑解锁 + 左右翻页"。
这条路径**不经过 backboardd 的用户态 client 连接**，所以即使 unified log 里那 10973 条
`no client connection for port` 存在，内核注入的上滑仍会送达 SpringBoard。
`pandora_fbdump`（补丁 0159）周期性把"当前显示的图层 + 面板内容"转储进日志文件，无需人按音量键。

- 若日志出现 `PANDORA AUTOSWIPE: ... swipes` 且 fbdump 帧里出现主屏幕（图标/Dock/壁纸变化）：
  **系统已进桌面，卡点只在 Apple Logo overlay 未移除** —— 后续主攻显示层/BKBootUIPresenter。
- 若 autoswipe 跑完但 fbdump 始终是白苹果、主屏幕帧从不出现：
  **SpringBoard 确实卡在首启** —— 回到用户态/D A 框架方向。

## 参数（已核算：整条 cmdline 271/607 字符，余量充足）

在 `ios_test.sh` 的 BASE 之上，通过第 4 个参数 EXTRA 追加：

```
pandora_autoswipe=90 pandora_autoswipe_at=45 pandora_fbdump=30
```

- `pandora_autoswipe=90`：从 `at` 秒起持续注入上滑/翻页 90 秒（约 45s–135s）。
- `pandora_autoswipe_at=45`：开机 45 秒开始（上游默认；backboardd 约 20s 出首帧）。
- `pandora_fbdump=30`：每 30 秒转储一次显示帧（无需人工按键）。
- `SECS`（ios_test.sh 第 3 个参数）取 **240**：必须大于 45+90=135，留出抓帧余量；到点自动重启回安卓。

## 执行（电脑前有人，一条命令跑完；此处仅记录，未执行）

在 Git Bash、仓库根目录：

```bash
# 1) 启动 + 自动重启回安卓 + 自动抓内核日志并解 fbdump PNG（约 4 分钟）
FW=/data/local/tmp/adspfw.img tools/ios_test.sh autoswipe_a 60 240 \
  "pandora_autoswipe=90 pandora_autoswipe_at=45 pandora_fbdump=30"
```

说明：`ios_test.sh` 内部会核对 root 镜像 pinned extents（f2fs 移动过会拒绝启动）、
构建 payload、打印最终 cmdline（`PANDORA AUTOSWIPE`/`FBDUMP` 三个参数必须出现在打印行里，
否则 boot args 被截断，需缩短）、`fastboot boot`，然后等待安卓回来，抓取
`device/logs/autoswipe_a.txt` 并用 `fbdump.py` 解出 `device/logs/autoswipe_a-*.png`。

```bash
# 2) 回安卓后，全套只读抓取（内核环 + unified log + 截图 + summary），产物在 WSL
tools/byron_capture.sh autoswipe_a 8
```

```bash
# 3) 判定用的关键证据（byron_capture.sh 的 summary 不含 autoswipe 标记，补这两条 grep）
WSL='//wsl$/Ubuntu-24.04/opt/work/captures/autoswipe_a'
grep -nE 'PANDORA AUTOSWIPE|SWEET THUMB|PANDORA FBDUMP' "$WSL/kernel_ring.txt" | head -40
ls -la device/logs/autoswipe_a-*.png "$WSL/shots" 2>/dev/null
```

## 判定表

| 证据 | 含义 | 后续方向 |
|---|---|---|
| `PANDORA AUTOSWIPE: N swipes`（N>0）+ fbdump/截图出现主屏幕 | 已进桌面，overlay 未移除 | 显示层：BKBootUIPresenter / removeOverlay |
| autoswipe 有 N，但帧始终是白苹果 | SpringBoard 卡首启 | 用户态：DA 框架 buddy 判定源 |
| 没有 `PANDORA AUTOSWIPE` 行 | boot args 未生效（被截断或 patch 缺失） | 先查 cmdline 打印行，重跑 |
| 内核日志止于 panic | 与本次判别无关，先修 panic | 单独处理 |

## 对照实验（可选，验证"GPU 引入回归"假设）

`gpu_test.sh:240-241` 是带 `pandora_gpu=15` 启动的（fix14/15 白苹果即此路径），
而 `ios_test.sh` 的 BASE 不含 GPU 参数。所以两次对照就是：

```bash
# 有 GPU（复现白苹果）：用 gpu_test.sh，它内部再调 ios_test.sh 并注入 pandora_gpu=15
#   注意 gpu_test.sh 的位置参数是 NAME TURNIP_ZIP，见其头部；autoswipe 参数经 --args 传入：
tools/gpu_test.sh autoswipe_gpu <TURNIP_ZIP> --secs 240 --args "pandora_autoswipe=90 pandora_autoswipe_at=45 pandora_fbdump=30"

# 无 GPU（对照 10 月进桌面）：直接用 ios_test.sh（BASE 无 GPU 参数）
FW=/data/local/tmp/adspfw.img tools/ios_test.sh autoswipe_cpu 61 240 \
  "pandora_autoswipe=90 pandora_autoswipe_at=45 pandora_fbdump=30"
```

若 `autoswipe_cpu` 能翻动主屏幕而 `autoswipe_gpu` 不能，即证实 GPU/渲染链路是白苹果的引入因素。
（`<TURNIP_ZIP>` 是之前用的 Turnip 包，路径在 WSL，不入库；`gpu_test.sh --args` 的具体开关见其头部注释。）

## 边界

- 本步骤不修改内核、root 镜像、boot 分区；仅用现有 fix15 产物 + boot 参数。
- `pandora_reboot_after=240` 由 ios_test.sh 注入，到点自动回安卓，无需长按电源。
- 所有日志/截图/镜像留在 WSL 与 `device/`（`.gitignore` 已挡），不提交、不上传。
