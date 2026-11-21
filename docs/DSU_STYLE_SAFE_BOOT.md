# DSU 式安全启动（以及为什么不能用真的 DSU）

本目录里的改动面向 **小米 17 Max（byron）**，从上游 `popsicle`（小米 17 Pro Max）派生。  
**安全闸门原文保留如下；当前真机进展以 [byron/LIVE_BRINGUP_STATUS.md](byron/LIVE_BRINGUP_STATUS.md) 为准。**  
最初交付的是安全启动框架与采集清单；后续已按真机数据推进到 RAM 引导阶段，但本文的闸门规则不变。

## 1. 结论：真 DSU 启动不了 iOS

Android 官方对 [Dynamic System Updates](https://developer.android.com/topic/dsu) 的定义是：把新的  
GSI（Android system 镜像）装进动态分区、作为 guest OS 启动，方便在不破坏当前系统的前提下试用 GSI。  
它的几个硬性质决定了本项目用不了：

| DSU 的性质                                                      | 对本项目的后果                                                                                      |
| ------------------------------------------------------------ | -------------------------------------------------------------------------------------------- |
| 只替换 system/GSI，**沿用原厂 boot、dtbo、vbmeta、ramdisk 里的 Linux 内核** | ios-popsicle 的核心是**换掉内核**：`fastboot boot` → shim → UEFI → iBoot 替身 → 自编译 XNU。内核换不了，iOS 就无从谈起 |
| GSI 需由 Google/OEM 签名、依赖 super 动态分区                           | 我们要加载的是 Apple 的 iOS root + trust cache，不是 Android GSI                                        |
| 会写 metadata/misc 的一次性启动标记，可开 sticky 跨多次启动                    | 反而不是「零写入」，且卡在 GSI 启动循环时更难收拾                                                                  |
| 冷启动回原系统、可 Discard                                            | 这些**安全语义**可以照搬，且与 XNU 不冲突                                                                    |

所以：**「把 iOS 塞进 DSU 分区」不成立；「用 DSU 的安全语义包住 fastboot boot」成立。**

## 2. DSU 语义 → 本方案的对应实现

| DSU 语义           | 本方案                                                                                                                                      |
| ---------------- | ---------------------------------------------------------------------------------------------------------------------------------------- |
| 一次性、不启用 *sticky* | 不安装 `bootmgr/` 开机菜单；脚本全程不出现 `fastboot flash`；每次启动都要求显式 `--commit`                                                                        |
| 不破坏当前系统          | 主脚本 `mac/boot_ios.sh` 本来就是纯 RAM 启动（README: "Normal testing writes nothing to the phone's partitions"）；iOS root 只写 `/data` 里的固定 pinned 文件 |
| 冷启动即回原系统         | 内核 `pandora_reboot_after=<秒>` 到点自动重启；兜底长按 电源+音量下 ~10 秒                                                                                   |
| Discard / 回滚     | `tools/safe_recover.sh`：关 DSU sticky、核对 `boot_b`、必要时用原装备份恢复                                                                              |
| 安装前校验            | `tools/safe_boot.sh` 的 12 项前置检查（见下）                                                                                                      |

`tools/safe_boot.sh` 的前置检查：profile 板级数据已采集 / 内核文件存在 / 超时在 60–900 秒 /  
启动器存在 / adb 在线 / `ro.product.device` 匹配 / 分区备份 manifest 无 MISMATCH /  
`boot_b` 哈希与备份一致（证明没装过 bootmgr）/ 无 bootmgr guard 模块 / 无激活的 DSU 会话 /  
两个 pinned 文件已钉住且未被 f2fs GC 移动 / extents 记录存在。

**默认 dry-run**，只检查并打印将执行的命令。真实启动需要 `--commit` 且  
`SAFE_BOOT_CONFIRM=1`（或交互式输入 `YES`）。任何一项检查失败都会以退出码 3 拒绝启动。

## 3. 机型：byron ≠ popsicle

|     | `popsicle` 小米 17 Pro Max     | **`byron` 小米 17 Max**                                     |
| --- | ---------------------------- | --------------------------------------------------------- |
| 发布  | 2025-09-25                   | **2026-05-21**                                            |
| 型号  | —                            | 2605EPN8EC                                                |
| SoC | SM8850 (canoe)               | **SM8850-AC (kaanapali)**，同为骁龙 8 Elite Gen 5 / Adreno 840 |
| 屏幕  | 6.9" 2608×1200 + **2.9" 背屏** | 6.9" 2608×1200 超级像素 M10，**无背屏**                           |
| 电池  | 7500mAh                      | **8000mAh 金沙江，P3/G2 充电芯片**                                |
| 影像  | 光影猎人 950L 三摄                 | 2 亿 HP9 主摄 + 3x 潜望                                        |

来源：[小米官网规格](https://www.mi.com/prod/xiaomi-17-max/specs)、  
[mifw.pro/devices/byron](https://mifw.pro/devices/byron)、[XiaomiTime](https://xiaomitime.com/smartphones/xiaomi-17-max)、  
[PhoneDB](https://phonedb.net/index.php?d=detailed_specs\&id=25817\&m=device)。

社区现状：GitHub 上搜不到任何 byron 的 XNU / UniXNU 设备分支，  
[unixnu.com/devices/byron](https://unixnu.com/devices/byron) 也是 404——**这是第一份 byron 骨架**。

同 SoC 家族是好消息（`xnu/patches/`、`shim/loader`、UniXNU 的 4K 页/NativeAdreno/NativeMetal  
可复用），但板级参数全部要重采。

## 4. 新增/改动的文件

| 文件                              | 作用                                                                                            |
| ------------------------------- | --------------------------------------------------------------------------------------------- |
| `profiles/byron.env`            | byron 设备配置骨架，`BOARD_DATA_COMPLETE=no`（**故意**拒绝真实启动）                                           |
| `profiles/popsicle.env`         | 上游已跑通机型的对照配置                                                                                  |
| `tools/safe_boot.sh`            | DSU 式安全启动封装（默认 dry-run、12 项前置检查、会话记录）                                                         |
| `tools/safe_recover.sh`         | 回滚/收尾（默认 dry-run；`--restore-bootb` 才可能写分区）                                                    |
| `tools/tests/test_safe_boot.sh` | mock adb/fastboot 的 45 项本地回归测试                                                                |
| `mac/boot_ios.sh`               | **最小改动**：新增 `IOS_DEVICE` / `IOS_EXTENTS_DIR` / `ADB_BIN` / `FASTBOOT_BIN`，默认值仍是 popsicle，行为不变 |

## 5. 用法

```bash
# 0) 先做只读分区备份（上游脚本，生成 backup/manifest.txt）
tools/backup.sh

# 1) byron：默认 dry-run，看检查结果和将执行的命令
tools/safe_boot.sh --device byron --kernel /path/to/kernel.macho --seconds 180

# 2) 确认板级数据采集完、所有检查通过后，才允许真实启动
SAFE_BOOT_CONFIRM=1 tools/safe_boot.sh --device byron \
    --kernel /path/to/kernel.macho --seconds 180 --commit --watch

# 3) 收尾 / 异常回滚
tools/safe_recover.sh --device byron                 # dry-run
SAFE_BOOT_CONFIRM=1 tools/safe_recover.sh --device byron --restore-bootb --commit

# 4) 本地回归测试（无需真机）
bash tools/tests/test_safe_boot.sh
```

`--adb` / `--fastboot` / `--launcher` / `--backup-manifest` / `--state-dir` 可注入，  
便于在 CI 或没有 Mac 的环境里跑 mock 测试。

## 6. byron 移植清单（离线固件部分已完成）

> 后续进展见 **`docs/byron/PORTING_GUIDE.md`** 与 **`docs/byron/FIRMWARE_DIFF.md`**：  
> 已用官方 OTA `OS4.0.4.0.XAFCNXM` 跑完真实固件 diff，工具链现有  
> 固件取包 / DTB 拆分 / diff、真机只读采集、配置生成，**82 项离线回归通过**。  
> 用真实 `firmware.json` 跑 `--check` 得到 **21/42 必需项已解析**；  
> 缺的 21 项基本都要真机或构建产物，闸门仍为 `BOARD_DATA_COMPLETE=no`。

- [ ] `device/byron/extents/`：用 `mac/phone_prepare.sh` 在 byron 上生成  
  `iosroot.json` / `ioslog.json`（以及 GPU 用的 `adspfw.json`）；  
  **该脚本已改造完成**：`IOS_DEVICE` / `IOS_EXTENTS_DIR` / `ADB_BIN` 可配置，  
  默认值仍是 popsicle。用 `IOS_DEVICE=byron IOS_EXTENTS_DIR=device/byron/extents` 调用。  
  这些是真机私有数据，上游 `.gitignore` 的 `/device/*` 会忽略它们，不要提交
- [ ] `device/byron/stock/boot_b.img`：原装 `boot_b` 备份与 SHA-256
- [ ] `backup/manifest.txt`：`tools/backup.sh` 的输出，且必须包含 `ok boot_b ...`
- [x] DTBO/FDT 的 SoC 常量：GICD/GICR/stride、timer、UFS/SID、SPMI、MDP、TLMM(DT)、  
  MPIDR、PSCI 已由官方固件确认与 popsicle 一致（`docs/byron/FIRMWARE_DIFF.md`）。  
  例外：`/memory` 与 `splash_region` size 是 ABL 运行时填的占位符，**仍须真机读取**；  
  TLMM **真实**基址（0x0f100000）也仍需本机确认
- [x] 面板参数：byron 主屏 1200×2608 / 30bpp / DSC / 1–120Hz、无背屏、  
  触摸 IRQ158/reset66、TDM 2 slot、WCN786x 已从 DTBO 读出
- [ ] `/vendor/firmware_mnt` 下的 ADSP、WCN786x、功放固件（`vendor` 分区尚未解包）
- [ ] 电量计/温控：8000mAh + P3/G2，popsicle 的 `pandora_gauge` / `pandora_therm` 参数不适用
- [x] `mac/phone_prepare.sh` 的机型校验与 extents 输出目录已改为可配置
- [ ] 用 `python3 tools/port/gen_byron_config.py --firmware device/byron/firmware.json \     --live device/byron/live --manual device/byron/manual.json --check --strict`  
  确认 42 项**必需**板级数据齐全；  
  它只在数据齐全时给 `data_ready`，只有人工 `--attest`（真机启动已验证）才写 `yes`。  
  不要手工改这个闸门。先跑 dry-run 全绿，再用短超时（60–120 秒）做第一次真机验证

**注意**：`BOARD_DATA_COMPLETE=no` 是安全闸门，不是为了好看。在没有真机 extents 的情况下  
强行启动，XNU 会按编译期记录的物理块地址写 root/log，而 f2fs 上文件位置若不同，  
**会写坏 Android 的 userdata**（上游 `bootmgr/README.md` 的「保护」一节也是同一个风险）。

## 7. 仍未解决 / 风险

- 真机部分完全没有验证：本工作区没有 byron 本机、没有它的 extents，也没有 Mac + IPSW 构建环境。  
  **官方固件已解析**（`docs/byron/FIRMWARE_PROVENANCE.md`），但离线 diff 不等于真机启动。  
  所有测试都是离线/mock 层面的：`bash tools/tests/test_safe_boot.sh`（45 项）+  
  `python3 tools/port/test_port_tools.py`（82 项，含原有 45 项回归），全部通过；  
  其中构造的 FDT/payload 只用于验证解析器逻辑，真实固件条件检查单独列出。
- `--commit` 之后真正干活的是上游 `mac/boot_ios.sh` → `mac/build_boot.sh`，  
  它要求 macOS、Xcode/LLVM、`$HOME/17pm-work` 里的 IPSW 与 trust cache；这些不在本改动范围内。
- DSU 属性检测用的是 `ro.gsid.image_running` / `ro.boot.dsu`，属于保守探测；  
  若厂商改了属性名，请以 `adb shell gsi_tool disable` + 冷启动为准。
- 无论多安全，这仍是解锁 Bootloader 的实验性移植： Cellular、Apple ID、App Store 不可用，  
  安全模型被关闭，有变砖与数据丢失风险，且 iOS 许可不允许在非苹果硬件上运行、禁止商用。
