# XNU kernel 云端编译 + 本机组装操作清单（小米17 Max / byron）

> 日期：2026-11-21　目标：拿到项目原生 iOS 16.7.16 (20H392) 的 XNU kernel，组装 payload，`fastboot boot` RAM 启动验证。
>
> **适配机型：小米17 Max（`byron`）——本仓库唯一目标机型。** 小米17 系列有多款后缀型号（小米17 / 17 Pro / 17 Pro Max / 17 Max），本文所有内容仅针对小米17 Max。
> **来源**：fork 自 **[OctoDevStudios/ios-popsicle](https://github.com/OctoDevStudios/ios-popsicle)**（原项目适配小米17 Pro Max / `popsicle`），本 fork 改适配小米17 Max。
>
> **不需要买苹果电脑。** 真正需要 macOS/Xcode 的编译步骤设计上就跑在 GitHub 云端 `macos-15` runner（原为 `macos-14`，已于 2026-11-02 退役）；本机（Windows + WSL）只负责触发、下载、组装。

## ✅ 实际执行状态（2026-11-21 17:30：编译成功）

- **已用用户提供的 PAT（fine-grained，账号 `1074655144`，admin 权限）通过 GitHub API 全程代办**，用户无需手动操作。
- Fork 已建：`1074655144/ios-popsicle`（**public**，macOS runner 免费无时长上限）。URL: <https://github.com/1074655144/ios-popsicle>
- 关键坑：新 fork 的 Actions 未自动注册 workflow（`actions/workflows` 返回空、单 workflow 端点 404）。通过 API 创建占位提交 `CI-ENABLED.md` 触发扫描后，`xnu` workflow 才出现。
- 已删除 fork 上写坏的 `ping.yml`（`\n` 被写成字面 `/n`，导致 422 / push failure）。现仅剩 `turnip` + `xnu` 两个 workflow。
- **✅ 根因已定位**：`macos-14` runner 镜像已于 **2026-11-02 退役**，GitHub 报错
  `The configuration 'macos-14-arm64-us-default' is not supported`。所以 job 在分配 runner 前被瞬间
  `cancelled`（`runner_id=0`、零 step、1 秒内结束、无 job 日志）。**不是**并发竞态（实测关掉
  `cancel-in-progress` 仍然瞬间取消）、**不是**权限、也**不是** workflow 语法问题。
- **已修复**：`.github/workflows/xnu.yml` 的 `runs-on` 由 `macos-14` 改为 **`macos-15`**（当前 arm64 镜像）。
- 历史 run（均为旧 `macos-14`，全部 cancelled）：`44881039790` / `44881101899` / `44881225533` /
  `44881739797` / `44881846665`。
- **✅ 内核已发布到 Releases**：<https://github.com/1074655144/ios-popsicle/releases/tag/xnu-16.7.16-byron-20261121>
  （tag `xnu-16.7.16-byron-20261121`，含 `kernel.development.pandora` 17.4MB + `SHA256SUMS`，永久保存、免登录直链）。
  由 `release-kernel.yml` workflow 从 CI artifact 自动发布。
- **✅ 编译成功：run `44885849346`（`macos-15`，约 10.5 分钟）全部 13 步 success**，runner_id=1000000017。
  产物：`xnu-kernel` 62,781,131 B / `xnu-objects` 54,789,712 B / `xnu-buildtree` 23,959,099 B。
  URL：<https://github.com/1074655144/ios-popsicle/actions/runs/44885849346>
- **编译失败→修复完整链条（供复现）**：
  1. `macos-14` 退役 → job 秒取消 → 改 `macos-15`（`xnu.yml` / `turnip.yml`）。
  2. run `44882262020`：Build 1 分钟失败于 `0361-stage-nw-all.sh` 复制未入库的 `xnu/vendor/nw_all.o`
     → 改为"缺 `nw_all.o` 时用 `xcrun clang` 生成 no-op `nw_wifi_*` 符号 stub"（Wi-Fi 默认关闭，仅满足链接）。
  3. run `44882569858`：跑满 7.5 分钟后链接失败，缺 2 个符号 `nw_mhi_crash_report` /
     `nw_wifi_control_transport_set`（来自 0363/0366 补丁 extern 声明）→ stub 补全。
  4. run `44885849346`：✅ 全绿。Xcode 16 的 `iig` 未出问题，无需补 `IORPC.kernelContent`。
- 监控 URL：<https://github.com/1074655144/ios-popsicle/actions>
- **下一步**：下载 `xnu-kernel` artifact → SHA256 校验 → 放到 `incoming/` → 本机组装 payload → `fastboot boot` RAM 验证。产物 retention 7 天。

---

## 0. 当前状态（已就绪 / 待办）

| 环节 | 状态 |
|---|---|
| iOS 16.7.16 IPSW 校验 | ✅ SHA256 与官方一致、仍签名 |
| IPSW 资产解包（7GB）到 WSL `/opt/work/ipsw/` | ✅ 全部 SHA384 校验通过 |
| `d22ap.adt` + `kernelcache.thin.macho` 转换 | ✅ 在 `/opt/work/ipsw/ext/` |
| 本机 payload 工具链（adt.py/mkadt.py/mkpayload.py/mkadt_pandora.py/addtrustcache.py/bootlogo.py） | ✅ 已部署并用占位 kernel 端到端演练成功 |
| **XNU kernel 编译** | ✅ 云端 CI 已成功（run `44885849346`），`xnu-kernel` artifact 62MB 已产出 |
| payload 组装 + `fastboot boot` | ⬜ kernel 下载 + 校验中，完成后本机可做 |

**一句话**：kernel 已编译成功，本机组装链此前已用占位 kernel 端到端演练过（49MB payload.bin 验证），现在正在下载真 kernel，到位后即可组装 + RAM 启动验证。

---

## 1. 你在浏览器要做的事（约 5 分钟操作 + 等云端编译）

### 1.1 Fork 仓库
1. 打开 <https://github.com/OctoDevStudios/ios-popsicle>
2. 点右上角 **Fork** → 选你自己的账号 → 等几秒完成
3. 你会得到 `https://github.com/<你的用户名>/ios-popsicle`

> 说明：fork 原仓库即可。我们本地的 byron 改动（stride 4800、profiles、shim、porting 文档）都在 shim/profile/tools/docs，**不在 `xnu/patches/`**，而 CI 编译只读 `xnu/patches/`——所以原版 fork 编出来的 kernel 与本地改动无关，正是我们要的 PANDORA kernel。

### 1.2 触发编译
4. 在你的 fork 页面点 **Actions** 标签
5. 左侧选 **xnu** workflow
6. 点右侧 **Run workflow** 下拉，参数保持默认：
   - `macos_version` = `13.5`（= xnu-8796，iOS 16 era）
   - `kernel_config` = `DEVELOPMENT`
   - `machine_config` = `PANDORA`
   - `keep_going` = `true`
7. 点绿色 **Run workflow**

### 1.3 等待并下载产物
8. 编译跑在云端 macOS，约 **20–60 分钟**（超时上限 120 分钟）。点进 run 可看实时日志。
9. 跑完（即使某步失败，`xnu-kernel` 等产物也会上传）后，页面底部 **Artifacts** 区会列出 3 个：
   - **`xnu-kernel`** ← 必需，里面是 `kernel.development.pandora`
   - `xnu-objects`（本机 relink 用，可选先不下）
   - `xnu-buildtree`（改源码重编用，可选先不下）
10. 下载 `xnu-kernel`（点击会打包成 zip），解压得到 `kernel.development.pandora` 和 `SHA256SUMS`。

> 私有仓库 macOS runner 每月约 190 分钟额度，单次编译 <120 分钟够用；公开仓库免费无时长上限。若额度不够，把 fork 设为 Public 即可。

---

## 2. kernel 下载后 —— 交给我做（你只需把文件放到指定位置）

把 `kernel.development.pandora` 放到这个项目目录下：

```
<repo>/incoming/kernel.development.pandora
```

然后告诉我一声，我会依次完成：

1. **校验**：用 artifact 里的 `SHA256SUMS` 核对 kernel 完整
2. **放到位**：复制到 `/opt/work/run1/xnu-kernel/kernel.development.pandora`
3. **组装 payload**：跑 `make_phone_payload.sh`，用本地 IPSW 的 trustcache（3 个，`087-86698-044` / `087-86593-047` / `087-86715-047`）+ logo，生成 `/opt/work/run1/payload.bin`
4. **打 boot.img**：用 `shim/loader/build.sh` 把 payload + loader 打成 `loader-boot.img`
5. **RAM 启动验证**：`fastboot boot`，屏幕应显示 iOS 启动 logo / 内核日志；按项目流程读日志、看是否进 launchd
6. 全程 **不刷任何分区、不动 AVB**，失败自动重启回安卓

---

## 3. 参考：本机已验证的组装链（演练记录）

用 `kernelcache.thin.macho` 的 arm64 slice 作占位 kernel，在 WSL `Ubuntu-24.04` 中跑通：

```
KERNEL=<thin-macho> RD=ufsroot0 bash make_phone_payload.sh /opt/work/runTEST 'debug=0xc'
  → phone.adt  22,704 bytes   ✅
  → payload.bin  49 MB        ✅  (mkpayload 正确解析 __PRELINK_DATA/__LINKINFO/__LINKEDIT 段)
```

工具链落点（仓库内已就位）：
- `tools/adt.py`、`tools/mkadt.py`、`tools/mkpayload.py`
- `tools/mkadt_pandora.py`、`tools/addtrustcache.py`、`tools/bootlogo.py`
- `wsl/make_phone_payload.sh`
- `/opt/work/ipsw/` ← 本机 IPSW 解包资产（不入库）

> 注：占位演练用的是 `rd=ufsroot0`（byron 的实际 root 路径，靠 pinned extents 指向 userdata 里的 iOS root），不依赖 `sweet-init` RAM disk。默认 `rd=md0` 才需要 `/opt/work/init/sweet-init`（本机无，但不影响 byron 路径）。

---

## 4. 可选后续（kernel 跑通后再考虑）

- **Wi-Fi**：`xnu/vendor/nw_all.o` 需从 Ath12kWifi + 你手机的 `peach` 固件编译（BUILDING.md 第 2 节）。基础启动不需要 Wi-Fi，先跑通再补。
- **本机 relink**：下载 `xnu-objects` + `xnu-buildtree`，用 `mac/relink_kernel.py` / `wsl/local_relink.py` 在 WSL 改源码重编，无需再跑 CI。
- **安全闸门**：`BOARD_DATA_COMPLETE=no`，`safe_boot.sh --commit` 仍拒绝真实启动；本流程全是 RAM boot，未触及该闸门。

---

## 6. 真 Wi-Fi 驱动内核

- 目标：把 `xnu/vendor/nw_all.o` 从 no-op stub 换成 Ath12kWifi / WCN7880 `peach` 的真实驱动，并保留 `pandora_wlan=2` 启动参数。
- 构建脚本：`tools/wlan/build_nw_bc.py` 把驱动源码编成 LLVM bitcode，`tools/wlan/link_nw_all.sh` 合并 bitcode 后只保留 `xnu/patches/0361*` 所需的 27 个 ABI 符号为 external，内部符号全部 internalize，再编成 Mach-O object；`tools/wlan/check_abi.py` 验证 ABI 27/27。
- `tools/wlan/patch_credit.py` 关闭 host 侧 WMI credit flow control，保留 firmware 自己的计数不变。
- CI：`xnu/vendor/nw_all.o` 是本地生成物，不入库；用 `tools/byron_fetch_ci_kernel.py` 取回内核产物。
- 组装：`tools/swap_kernel_payload.py` 只替换 payload 中的内核段，复用旧 payload 的 ADT、完整 cmdline 区块和 TrustCache 段。cmdline 字段必须整段复制，不要只写回截短字符串。
- 可复现步骤与启动参数见 `docs/byron/WIFI_BRINGUP.md`。全程 `fastboot boot`，不刷分区。

---

## 5. 关键事实备查

- CI workflow: `.github/workflows/xnu.yml`，`runs-on: macos-15`（原 `macos-14` 已退役），`timeout-minutes: 120`，`workflow_dispatch` 手动触发
- 产物 artifact 名：`xnu-kernel` / `xnu-objects` / `xnu-buildtree`，`retention-days: 7`（**下载要趁早，7 天后失效**）
- 目标版本：iOS 16.7.16 / 20H392（项目原生，IPSW 已校验仍签名）
- IPSW：`iPhone10,3,iPhone10,6_16.7.16_20H392_Restore.ipsw`，SHA256 `ece1194f7e233e9109c5790a8d23a4564a10a254e15ec5b09978a343265568fb`
