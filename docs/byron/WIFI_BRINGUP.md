# byron Wi-Fi 驱动 bring-up（可正常开机基线，Wi-Fi 功能未修复）

本文档只保留可复现的工具、步骤和已纳入的驱动层改动。**Wi-Fi 功能并未修复**：这里只记录让内核能启动到桌面的阻塞项处理，不代表扫描、连接或设置开关可用。**不包含**任何从手机提取的镜像、固件、日志、extents、序列号、截图或设备隐私数据；这些产物一律留在本机并被 `.gitignore` 排除。

全程只使用 `fastboot boot` 做 RAM 启动：不 `flash`、不 `unlock`、不改 AVB、不刷写系统分区。

## 1. 复现基线

可正常进入 iOS 桌面的内核包含以下 Wi-Fi 相关驱动层改动（**不等于 Wi-Fi 可用**）：

1. Ath12kWifi / WCN7880 `peach` 真实驱动替代 no-op stub。
2. `nw_all.o` 仅导出 `xnu/patches/0361*` 需要的 27 个 ABI 符号，其余内部符号 internalize。
3. host 侧 WMI HTC credit flow-control 检查关闭，firmware 侧计数保持不变。
4. `xnu/patches/0348-popsicle-wlan-firmware.patch` 在没有音频 group 时建立 SMMU bypass fallback。

复现时固定在这个基线；不要叠加后续的单信道扫描实验补丁。WiFi 扫描/QMI 超时仍是后续待解项，不影响本文档所述“能进桌面”的基线。

## 2. 需要的工具

### 仓库内已有

| 路径 | 用途 |
|---|---|
| `tools/wlan/pull_peach_firmware.py` | 从已 root 的 Android 只读取出 `peach` 固件到本机；输出不入库 |
| `tools/wlan/peach.py`、`tools/wlan/peach2.py` | 处理固件、生成驱动构建所需产物 |
| `tools/wlan/build_nw.py` | 从上游 Ath12kWifi 构建本地驱动树 |
| `tools/wlan/ath12kwifi-local.diff` | 与上游一致的本地驱动差异 |
| `tools/wlan/build_nw_bc.py` | 把驱动源码编译为 LLVM bitcode |
| `tools/wlan/link_nw_all.sh` | 合并 bitcode、internalize、生成 `nw_all.o` |
| `tools/wlan/abi.txt`、`tools/wlan/check_abi.py` | 固定并验证 27 个 ABI 符号 |
| `tools/wlan/patch_credit.py` | 关闭 host 侧 WMI credit 检查 |
| `tools/wlan/verify_patch.py` | 严格 dry-run 验证补丁 hunk |
| `tools/byron_fetch_ci_kernel.py` | 从 CI 取回内核产物 |
| `tools/byron_fetch_artifact_resume.py` | 大产物分片续传 |
| `tools/swap_kernel_payload.py` | 只替换 payload 中的内核段，保留 ADT/cmdline/TrustCache |
| `tools/wlan_payload.py` | 生成 WiFi 相关 payload |
| `tools/usb_diag_payload.py` | 只改 payload 的 cmdline 区块，用于开关 boot-arg |
| `tools/usbserial_capture2.ps1` | Windows 下采集 USB CDC ACM 调试串口 |
| `tools/usb_diag_check.py` | 从串口日志检查 USB/GPU/WiFi 关键标记 |
| `tools/boot_desktop_diag.sh` | 桌面引导与诊断辅助 |
| `tools/setup_restore_skip_pack.py` | 生成跳过 Setup Assistant 恢复页的 firmware pack |
| `tools/inject_serial.py` | 把用户自己的序列号注入 ADT；序列号只在命令行传入，不写仓库 |
| `tools/metal_clients_pack.py`、`tools/replace_pack_entry.py` | Metal 插件与 firmware pack 条目替换 |

### 外部依赖

- 已 root 的 Android 环境、`adb`、`fastboot`。
- macOS CI 或具备 `clang`、`llvm-link-18`、`opt-18`、`llvm-nm-18` 的构建环境。
- 用户自己的 IPSW / cryptex DMG / root 镜像构建产物。
- 用户手机上的 `peach` 固件，仅在本机使用。

## 3. 设备侧准备（只在本机执行）

1. 手机进入 Android，确认 `adb devices` 可见且 shell 为 root。
2. 只读拉取固件，输出目录保持本地 ignored：

   ```bash
   python3 tools/wlan/pull_peach_firmware.py
   ```

3. 按 `docs/PHONE_DATA_CAPTURE.md` 生成本机的 `iosroot.img`、`ioslog.img` 和 pinned extents。extents JSON、镜像和日志都不要提交。
4. 若需要让 Setup Assistant 跳过“传输/恢复应用与数据”，用 `tools/setup_restore_skip_pack.py` 从已有 firmware pack 派生新包，再用 `pinwrite rawwrite` 写入手机上已固定的固件文件；写入后回读校验，extents 不变。

## 4. 构建 `nw_all.o`

在用户自己的 Ath12kWifi 源码树上执行：

```bash
export ATH12K_ROOT=/path/to/Ath12kWifi
export NW_BC_DIR=/path/to/work/wl/bc
export NW_OUT_DIR=/path/to/work/wl

python3 tools/wlan/patch_credit.py
python3 tools/wlan/build_nw_bc.py
bash     tools/wlan/link_nw_all.sh
python3 tools/wlan/check_abi.py
```

`check_abi.py` 输出必须是 `ABI symbols: 27/27 defined`。生成的 `nw_all.o` 放到 `xnu/vendor/nw_all.o` 参与 CI；该路径已被 `.gitignore` 排除。

补丁验证：

```bash
python3 tools/wlan/verify_patch.py xnu/patches/0348-popsicle-wlan-firmware.patch
```

## 5. 内核 CI 与产物取回

1. 按 `docs/byron/CI_KERNEL_BUILD.md` 触发 XNU 云端构建，启用 WiFi 驱动补丁链。
2. 用 `tools/byron_fetch_ci_kernel.py` 取回 `xnu-kernel` 产物；网络不稳时用 `tools/byron_fetch_artifact_resume.py` 续传。
3. 检查产物中存在 `kernel.development.pandora`，不要提交 CI 下载目录。

## 6. 组装 payload 与 RAM 启动

1. 从一个已能开机的 payload 派生，使用 `tools/swap_kernel_payload.py` 仅替换内核段。必须整段复制 cmdline 字段，不要只写回截短字符串，否则后续段偏移会错位。
2. 生成 ADT 时按上游 `mac/build_boot.sh` 传 `--amp`，保持双 cluster（E/P）。这是桌面能起来的必要条件。
3. 若需要 iOS“关于本机”显示序列号，用 `tools/inject_serial.py IN OUT "$USER_SERIAL"` 注入用户自己的值；不要把序列号写进脚本、文档或提交。
4. 在 cmdline 中保留 WiFi 与已验证的显示/调试开关，例如：

   ```text
   rd=ufsroot0 ufsrw=1 rootrw=1 unentitled_ios_sim_launch=1 ignition_level=1
   wdt_test=no_user_checkin launchd_unsecure_cache=1 wdt=-1
   sweetfb_hz=30 sweetfb_fill=1 sweetnoexec=bluetoothd,fairplayd.H2
   pandora_gpu=15 pandora_gpu_metal=1 pandora_usb=2 qcom-usb-debug=1
   pandora_gauge=3 pandora_battery=1 pandora_wlan=2
   ```

   cmdline 总长必须低于引导行限制；不要提交含本机 RTC 偏移或序列号的最终 payload。
5. 用 WSL/本地 loader 构建脚本重建 `loader-boot.img`，确认 payload 偏移和 `_payload_end` 正确。
6. 手机进入 bootloader 后仅执行：

   ```bash
   fastboot boot loader-boot.img
   ```

## 7. 已纳入的驱动层改动（非 Wi-Fi 修复）

- **双 cluster 调度**：ADT 使用 `--amp`，避免 P-cluster 推荐线程无 cluster 可调度。
- **USB 调试通道**：`pandora_usb=2 qcom-usb-debug=1` 启用 CDC ACM 串口，用于取内核日志；它不是 Apple 官方设备端口。
- **硬件 scanout**：`pandora_gpu=15 pandora_gpu_metal=1` 让 DPU 做缩放，避免 CPU 最近邻缩放造成花屏。
- **SMMU fallback**：0348 补丁在没有音频 group 时用最后一个 context bank 建立 bypass bank。
- **WMI credit**：只关闭 host 侧 credit 检查，firmware 侧 wire flag 与计数不变。
- **符号隔离**：`nw_all.o` 只保留 27 个 ABI external，避免与 XNU 内部符号冲突。
- **Setup Assistant**：通过 firmware pack 注入跳过恢复页所需的 plist 与安装规则。
- **Metal 能力应答**：`tools/metal/adapt_ios16.py` 回答 QuartzCore/CoreImage 查询的六项设备能力，并支持 `pandora_devcaps=KEY=VAL` 覆盖。

## 8. 验证标准

正常基线应满足：

- `fastboot boot` 返回 OKAY，设备进入 iOS，不回退 Android。
- USB 串口出现 `QCOM XNU USB CDC ACM v1` 与 `PANDORA USB: serial started`。
- SMMU 不再因缺少音频 group 返回 `ENOENT`。
- 出现 `radio on applied`，说明驱动自检完成。
- 出现 `exec SpringBoard`，屏幕进入桌面。
- **Wi-Fi 未修复**：扫描超时、搜不到网络、设置开关与状态图标未接通，README 中 Wi-Fi 各项保持 0%。这只代表“能进桌面”的基线成立，不代表 Wi-Fi 功能完成。

## 9. 隐私边界

本仓库只同步方法、脚本和源码改动。以下内容一律只在本地保存，不进入提交、不上传远端：

- 手机提取的固件、root 镜像、日志镜像、firmware pack。
- 串口日志、统一日志、崩溃报告、截图。
- extents JSON、payload/loader 最终镜像、CI 下载产物。
- 序列号、UDID、ECID、RTC 偏移、设备 ID 等任何设备标识。
