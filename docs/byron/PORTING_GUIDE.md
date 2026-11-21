# 能不能把 ios-popsicle 真正移植到小米 17 Max（byron）？

**结论：能，但不是一个"改配置"的任务，而是一个数周级的移植工程。**
本轮把其中最容易卡死的第一段——**"到底要采哪些数据、从哪儿采、采完填到哪"**——
做成了可运行的工具链，并全部离线验证过。下面说清楚可行性依据、准确路径和真边界。

> **2026-11-18 更新：阶段 A（离线固件 diff）已经用小米官方 OTA 真实跑完。**
> 用的是 `OS4.0.4.0.XAFCNXM` 完整包（8.81 GiB），按 HTTP Range 只取回所需分区，
> 拆出 12 个 SoC 基础 DTB + 2 个 byron 叠加层，结果见 `docs/byron/FIRMWARE_DIFF.md`，
> 取包存证见 `docs/byron/FIRMWARE_PROVENANCE.md`。
> 仍然**没有真机、IPSW 或 Mac 构建环境**，`profiles/byron.env` 的闸门仍是
> `BOARD_DATA_COMPLETE=no`；42 项必需板级参数现在解析出 21 项。

---

## 1. 为什么这次判断比上一轮乐观

| 依据 | 说明 |
|---|---|
| **同 SoC 家族** | byron 是 SM8850-AC（Kaanapali），popsicle 是 SM8850。GICD/GICR、UFS、SMMU SID、PSCI、timer、TLMM 偏移公式、QUP/MPIDR 这些**平台级**寄存器由 SoC 决定，大概率可直接复用。离线 diff 工具会把它们判为 `same`。 |
| **byron 反而更简单** | 它没有 2.9" 背屏，因此可以**删掉**一整套副屏 DSI 面板 + FocalTech 触摸驱动（`DT_FINDINGS.md` 里主屏是 Synaptics TCM、背屏才是 FocalTech）。少一个驱动，不是多一个。 |
| **面板分辨率已从固件确认** | byron 主屏 DT 里是 **1200×2608 / 30bpp / DSC / 1–120Hz**，popsicle 是 1220×2656。数值不同，但都是 command-mode DSC；**framebuffer 宽高/stride 仍需 `shim/hello` 实测**，不能只看面板 DT。 |
| **官方 OTA 已实际取包** | 本轮已从 `ultimateota.d.miui.com` 的 `OS4.0.4.0.XAFCNXM` 完整包按 Range 取回 `dtbo` / `vendor_boot` / `boot`，**没有下载 8.81 GiB 整包**。解出 14 个 DTB，离线 diff 已完成。 |
| **上游把采集方法写下来了** | `device/DT_FINDINGS.md` 逐条记录了 popsicle 每个寄存器是怎么从 `/sys/firmware/fdt`、SSPP 寄存器、dm 表、FIEMAP、`/proc/bus/input/devices`、`/proc/interrupts` 读出来的——照着重跑一遍即可。 |
| **有兄弟机型可抄** | UniXNU 设备目录里 SM8850 家族已有 `pandora`(17 Pro)、`pudding`(17)、`fairlady`、`lafa`、`myron`、`songyuan`、`pma120` 等仓；`UniXNU-pudding` 的 `porting.toml` 是很好的板级记录范式。**唯独没有 byron**，所以它是新分支。 |

## 2. 真正的瓶颈在哪

不是"代码写不出来"，而是三类数据：

- **固件可读**（离线能拿）：GIC、内存窗口、splash_region、面板 DSC/命令模式、触摸与按键节点、TDM slots、固件文件清单 → `analyze_firmware.py`
- **真机只读可读**：live FDT、`getprop`、input 设备、两次 `/proc/interrupts`、dm-default-key 表、GPT、温控表、电源芯片 → `collect_board.sh`
- **必须人动手探测**：`shim/hello` 里的 framebuffer 宽/高/stride/格式、16K 页支持、ABL 装载地址、**TLMM 真实基址**、触摸 IRQ 归属、按键 GPIO、面板亮度 DCS 读回 → `manual.json`

第三类里的 **TLMM 是最容易翻车的一条**：上游 `DT_FINDINGS.md` 明确写着设备树写 `0x0f000000`，
硬件实测却是 `0x0f100000`；读 `0x0f065000` 会让总线卡死、整机重启（t2 测试）。照抄 DT 值会直接变砖级事故。

另外还有**驱动改造**这个真正的硬骨头：`xnu/patches/0333–0367` 有三十多个 `popsicle-*` 补丁，
硬编码了温控表（`0340` 直接嵌入 `/data/vendor/thermal/decrypt.txt` 的表）、95°C 结温滞回、
TDM 4 slot / 6.144 MHz、扬声器 3 声道、WCN7880 PCIe RC0 的 `WL_TLMM_PA` / `WL_COMMON_PA` 等。
byron 是 8000mAh + P3/G2 + M10 面板 + 立体声双扬，这些值**全部要重新标定**，不是改个宏。

## 3. 可执行的路线（本轮已把 A/B 自动化）

### 阶段 A：离线固件 diff（已完成，不需要手机）

复现命令与构建指纹见 `docs/byron/FIRMWARE_PROVENANCE.md`。关键是**只取所需字节**：

```bash
URL='<当次有效的签名 OTA URL>'
OUT=device/byron/firmware
python3 tools/port/fetch_ota.py --url "$URL" --partition dtbo --out "$OUT/dtbo.img"
python3 tools/port/fetch_ota.py --url "$URL" --partition vendor_boot --out "$OUT/vendor_boot.img"
python3 tools/port/split_dtbo.py --dtbo "$OUT/dtbo.img" --out-dir "$OUT/dtbs"
python3 tools/port/extract_boot_dtbs.py --vendor-boot "$OUT/vendor_boot.img" \
    --out-dir "$OUT/base_dtbs"
python3 tools/port/analyze_firmware.py \
    --dtb "$OUT"/base_dtbs/*.dtb "$OUT"/dtbs/*.dtb \
    --device byron --out device/byron/firmware.json \
    --report docs/byron/FIRMWARE_DIFF.md
```

**真实结论（44 项：42 必需）**：`same 15 / different 7 / runtime_patched 2 /
expected_absent 1 / pending_live 14 / pending_build 2 / pending_firmware 1 / na 2 / missing 0`。

- **15 项可直接复用**，全部 Soc 常量实测一致：GICD `0x17000000`、GICR `0x17080000`、
  stride `0x40000`、timer 19.2 MHz、VTIMER INTID 27、8 个 MPIDR、PSCI `smc`、
  UFS `0x1d84000`、UFS SID `0x60`、SPMI `0xc400000`、MDP `0x9800000`、TLMM(DT) `0xf000000`；
  连 `splash_base 0xfc800000`、触摸 reset GPIO 66、音量+ GPIO 101 都一样。
- **7 项必须改**：面板 1200×2608（popsicle 1220×2656）、1–120Hz（popsicle 24–120Hz）、
  **无背屏**（可删副屏 DSI + FocalTech 驱动）、触摸 IRQ158/reset66、
  **TDM 4 → 2**（立体声双扬，印证了原先的猜测）、**WCN7880 → `qcom,wcn786x`**。
- **2 项不能从固件取**：`/memory` 与 `splash_region` 在 DT 里是 `<0 0>` 占位符，
  由 ABL 启动时填写；写进 ADT 会直接错。分析器新增 `runtime_patched` 判定拦住它们。
- **1 项预期缺失**：FocalTech 副屏触摸确实不存在（`expected_absent`，不是错误）。

> 高通平台的关键结构认知：**SoC 常量在 `vendor_boot` 的 12 个基础 DTB 里，
> 板级差异在 `dtbo` 的 2 个叠加层里**。只喂 dtbo 会把 GIC/内存/CPU 全判成 `missing`；
> 分析器现在对每个字段在所有树里取最可信值，不会被空叠加层遮住。

`tools/port/popsicle_baseline.json` 是 **44 项板级参数（42 项必需）**的机器可读基线：
新增了 `gicr_stride` / `vtimer_intid` / `ufs_smmu_sid` / `touch_reset_gpio` 四个提取器，
其中 14 项属于 `soc_shared`、30 项是 `board_specific`。
来源逐项标了 `DT_FINDINGS.md` / `mkadt_pandora.py` / 具体补丁号。

### 阶段 B：真机只读采集（不写任何分区）

```bash
bash tools/port/collect_board.sh --device byron --out device/byron/live
```

23 个文件全部落在**电脑**上。手机侧只有 `getprop / cat / dd if= / ls / find / dmsetup table`，
脚本里没有 `fastboot`/`flash`/`setprop`/`dd of=`/`rawwrite`，测试用 mock adb 逐条核对过调用日志。
采集时会提示摸主屏 2 秒，用两次 `/proc/interrupts` 判断哪个 IRQ 属于主屏触摸。

> 注意与 `mac/phone_prepare.sh` 区分：那个脚本**会**往 userdata 写 16 GiB iOS root（上游行为）。
> 本采集脚本不会。

### 阶段 C：合并、校验、生成

```bash
# 把 hello/touch/key/亮度 的人工探测值填进 device/byron/manual.json
python3 tools/port/gen_byron_config.py \
    --firmware device/byron/firmware.json \
    --live device/byron/live \
    --manual device/byron/manual.json --check --strict

# 数据齐了再生成配置（默认仍不放行启动）
python3 tools/port/gen_byron_config.py ... --write
```

生成三样东西：

| 产物 | 作用 |
|---|---|
| `profiles/byron.env` | 填好实测值的设备配置 |
| `device/byron/adt_overrides.json` | 喂给 `tools/mkadt_pandora.py --board-json` 的白名单覆盖 |
| `docs/byron/PORT_CHECKLIST.md` | 逐项清单：值 / 来源 / 关联代码 / 状态 |

`--board-json` 只允许改 `PHYS_BASE`、`GICD/GICR`、`FB_*`、`MPIDRS` 等白名单常量，
未知键或非整数值一律拒绝（`tools/port/board_overlay.py`），避免笔误毁掉 ADT。
`mac/phone_prepare.sh` 也已改成 `IOS_DEVICE` / `IOS_EXTENTS_DIR` / `ADB_BIN` 可配置，
默认值仍是 popsicle，上游行为不变。

### 闸门语义（重要）

| `BOARD_DATA_COMPLETE` | 含义 | `safe_boot.sh --commit` |
|---|---|---|
| `no` | 必需数据缺失 | 拒绝 |
| `data_ready` | 数据齐了，但**没人在真机验证过** | 仍拒绝 |
| `yes` | 数据齐全 **且** 显式 `--attest`（声明真机启动已验证） | 还需通过 12 项运行时检查才放行 |

"填完表"永远不会自动解锁启动。这是刻意的。

### 阶段 D：内核与驱动（本轮没做，也无法在没有设备的情况下做）

1. 用 `mkadt_pandora.py --board-json device/byron/adt_overrides.json` 重建 ADT；
2. 按 `PORT_CHECKLIST.md` 逐项改 `xnu/patches/0333–0367`，删副屏相关驱动、重标温控/电量计/音频/WLAN；
3. 在 Mac + IPSW 环境跑 `mac/build_boot.sh` 出 `loader-boot.img`（仓库不含任何苹果文件）；
4. 用 60–120 秒短超时做第一次 `fastboot boot`，全程 `tools/safe_boot.sh` 守护。

## 4. 本轮交付的文件

| 文件 | 作用 |
|---|---|
| `tools/port/fetch_ota.py` | ZIP64 + brillo payload 解析，按 HTTP Range 只取指定分区；1 MiB 分块、逐块 SHA-256 校验 |
| `tools/port/split_dtbo.py` | 按 `dt_table_header` 拆 `dtbo.img` 为 DTB |
| `tools/port/extract_boot_dtbs.py` | 拆 `vendor_boot` v4 DTB 段里的连续基础 FDT |
| `docs/byron/FIRMWARE_PROVENANCE.md` | OTA 构建指纹、偏移、哈希与复现命令 |
| `docs/byron/FIRMWARE_DIFF.md` | 真实固件的逐项 diff 报告（本轮生成） |
| `tools/port/popsicle_baseline.json` | 44 项板级参数基线（42 必需），标注 `soc_shared`/`board_specific`、来源、需改代码 |
| `tools/port/analyze_firmware.py` | 复用仓库 `tools/dt.py` 解析 14 个 DTB，逐项 diff，出 JSON + Markdown |
| `tools/port/collect_board.sh` | 真机只读采集（23 个文件，零分区写入） |
| `tools/port/gen_byron_config.py` | 三路数据合并、完整度校验、生成 profile / ADT 覆盖 / 逐项清单 |
| `tools/port/board_overlay.py` | ADT 常量白名单覆盖与类型校验 |
| `tools/port/test_port_tools.py` | **82 项**离线回归（含构造 FDT、构造 payload、真实固件条件检查、mock adb、原有 45 项回归） |
| `tools/mkadt_pandora.py` | +`--board-json`，默认行为不变 |
| `mac/phone_prepare.sh` | `IOS_DEVICE` / `IOS_EXTENTS_DIR` / `ADB_BIN` 可配置 |

## 5. 诚实的边界

- **没有真机、没有 Mac + IPSW 构建环境**：本轮的固件 diff 是**真实官方 OTA**，
  但仍不等于真机验证。42 项必需参数现在只解析出 **21 项**，剩下 21 项里有
  14 项必须上真机（framebuffer 寄存器、TLMM 真实基址、温控/电量计/亮度 DCS、
  16K 页、ABL 装载地址、userdata 映射），另有 `vendor` 分区里的固件清单尚未解包。
- **没有一行 XNU 补丁被移植**。温控、电量计、ADSP 音频、WCN786x（不是 WCN7880）、
  Metal/GPU、面板亮度这些驱动改动仍需逐个真机调试，工作量远大于配置部分。
- `vendor_boot` 里 12 个基础 DTB 对应不同板型/散热版本，真机到底选哪一个由
  bootloader 按 board-id 决定；离线 diff 取的是它们共有且一致的值。
- 即便全部跑通，仍只是研究 Demo：无蜂窝通话、App Store 应用多数打不开、
  安全模型被关闭；解锁 BL 有变砖/失保风险，iOS 许可也不允许在非苹果硬件上运行、禁止商用。
- 真 DSU 启动 iOS 依旧**不可行**：DSU 只换 GSI(system)，不换内核；
  这里沿用上一轮的「DSU 式安全启动」语义（一次性、零写入、超时回滚），见
  `docs/DSU_STYLE_SAFE_BOOT.md`。
