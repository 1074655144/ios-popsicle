# byron 移植逐项清单

> 由 `tools/port/gen_byron_config.py` 自动生成。`BOARD_DATA_COMPLETE=no`。
> `same` 只表示数值一致，不等于验证通过；`soc_shared` 且 `same` 才可直接复用。

| 字段 | byron 值 | 来源 | 复用类 | 需改动的代码 | 状态 | 备注 |
|---|---|---|---|---|---|---|
| `gicd_base` | `0x17000000` | firmware | soc_shared | `tools/mkadt_pandora.py:GICD` | ✅ | GICv3 distributor; DT_FINDINGS 第二轮 |
| `gicr_base` | `0x17080000` | firmware | soc_shared | `tools/mkadt_pandora.py:GICR` | ✅ | 8 redistributors |
| `gicr_stride` | `0x40000` | firmware | soc_shared | `tools/mkadt_pandora.py:GICR_SIZE` | ✅ | redistributor-stride property (Qualcomm writes <0 0x40000>) |
| `timer_freq` | `19200000` | firmware | soc_shared | `tools/mkadt_pandora.py:TIMEBASE` | ✅ | arm,armv8-timer clock-frequency |
| `vtimer_intid` | `27` | firmware | soc_shared | `tools/mkadt_pandora.py:VTIMER_INTID` | ✅ | PPI 11 -> INTID 27 (SM8850 uses standard numbering, unlike older QCOM) |
| `mpidrs` | `['0x0', '0x100', '0x200', '0x300', '0x400', '0x5` | firmware | soc_shared | `tools/mkadt_pandora.py:MPIDRS` | ✅ | 6 E cores + 2 P cores |
| `psci_method` | `smc` | firmware | soc_shared | `xnu kernel psci init` | ✅ | arm,psci-1.0 |
| `ufs_base` | `0x1d84000` | firmware | soc_shared | `tools/mkadt_pandora.py:UFS` | ✅ | UFSHCI 4.0, legacy single doorbell at handoff |
| `ufs_smmu_sid` | `0x60` | firmware | soc_shared | `xnu/patches (SmmuTakeover)` | ✅ | bootloader leaves SID 0x60 in passthrough context 0 (UFS iommus 2nd cell) |
| `spmi_arb_base` | `0xc400000` | firmware | soc_shared | `xnu/patches power key driver` | ✅ | qcom,canoe-spmi-pmic-arb, v8 |
| `mdp_base` | `0x9800000` | firmware | soc_shared | `xnu/patches scanout/GPU` | ✅ | qcom,mdss_mdp |
| `memory_banks` | `[[0x81960000,0xa0000],[0x81a60000,0x1a0000],[0x8` | firmware | board_specific | `tools/mkadt_pandora.py:PHYS_BASE/MEM_SIZE/HIGH_MEM_SIZE` | ✅ | RAM size differs by SKU; byron 基础 DTB 的 /memory 是 <0 0> 占位符，ABL 启动填写，必须真机读取 |
| `phys_base` | `0x8c0000000` | manual | board_specific | `tools/mkadt_pandora.py:PHYS_BASE` | ✅ | chosen clean 5 GiB bank; must be recomputed from byron /memory + reserved-memory |
| `dsp_shm` | `0xb0000000` | manual | board_specific | `tools/mkadt_pandora.py:DSP_SHM` | ✅ | ADSP takes 32-bit addresses; must be free DRAM, no fixed carve-out |
| `splash_base` | `0xfc800000` | firmware | board_specific | `tools/mkadt_pandora.py:FB` | ✅ | reserved-memory cont_splash_region; bootloader keeps scanning out here |
| `splash_size` | `0x2b00000` | firmware | board_specific | `tools/mkadt_pandora.py:FB_SIZE` | ✅ | must equal ABL's scanout buffer size; byron DTBO 里是 0x0 占位符，由 ABL 启动填写，必须真机读取 |
| `fb_w` | `—` | — | board_specific | `tools/mkadt_pandora.py:FB_W` | ❌ 必需 | measured by shim/hello + SSPP registers, NOT the panel's physical width |
| `fb_h` | `—` | — | board_specific | `tools/mkadt_pandora.py:FB_H` | ❌ 必需 | byron's public spec is also 1200x2608, but the framebuffer must be measured |
| `fb_stride` | `—` | — | board_specific | `tools/mkadt_pandora.py:FB_STRIDE` | ❌ 必需 | read SSPP source stride register; do NOT assume width*4 |
| `fb_format` | `—` | — | board_specific | `shim/loader/loader.c` | ❌ 必需 | SSPP format register at +0x30 |
| `panel_phys_w` | `1200` | firmware | board_specific | `xnu/patches (DSC / panel timings)` | ✅ | physical panel resolution from DT, distinct from framebuffer |
| `panel_phys_h` | `2608` | firmware | board_specific | `xnu/patches (DSC / panel timings)` | ✅ | byron DTBO 实测 1200x2608 (qcom,mdss-dsi-panel-width/height), 与公网规格一致 |
| `panel_mode` | `command-mode DSC 30bpp 1-120Hz` | firmware | board_specific | `xnu/patches scanout` | ✅ | command mode means ABL's buffer keeps self-refreshing after handoff |
| `rear_display` | `none` | firmware | board_specific | `xnu/patches (secondary panel + touch)` | ✅ | byron DTBO 已确认无副屏、无 FocalTech；删掉这些驱动反而简化移植 |
| `touch_main` | `synaptics,tcm-spi (irq158 reset66)` | firmware | board_specific | `xnu/patches pandora_touch` | ✅ | TouchComm v1; byron DTBO 同厂 synaptics,tcm-spi, irq GPIO 158 / reset GPIO 66 |
| `touch_irq_gpio` | `158` | live | board_specific | `xnu/patches pandora_touch` | ✅ | TLMM GPIO; distinguish main vs rear by /proc/interrupts counter while touching |
| `touch_reset_gpio` | `66` | firmware | board_specific | `xnu/patches pandora_touch` | ✅ | synaptics,reset-gpio 2nd cell; plus avdd GPIO 117 / iovdd RPMh L4I_E0 |
| `touch_secondary` | `—` | — | board_specific | `xnu/patches (secondary touch)` | ⚪ 可选 | expected ABSENT on byron (no rear screen); absence is the correct result |
| `vol_up_gpio` | `101` | firmware | board_specific | `xnu/patches gpio keys` | ✅ | TLMM, active low |
| `tlmm_base_dt` | `0xf000000` | firmware | soc_shared | `xnu/patches` | ✅ | what the DT claims (pinctrl@f000000, qcom,canoe-tlmm) |
| `tlmm_base_real` | `0x0f100000 (derived:soc_shared, unverified-on-by` | manual | soc_shared | `xnu/patches 0343 WL_TLMM_PA and all GPIO drivers` | ✅ | CRITICAL: the real base is 0x0f100000, NOT the DT value. Reading 0x0f065000 hangs the SoC  |
| `tdm_slots` | `2` | firmware | board_specific | `xnu/patches/0342-popsicle-tdm-four-slots.patch` | ✅ | qcom,tdm-max-slots; byron DTBO 实测 2（立体声双扬），4-slot 补丁必须改 |
| `wifi_chip` | `wcn786x` | stock_dump | board_specific | `xnu/patches/0343-0367 WLAN series` | ✅ | byron DTBO 是 qcom,wcn786x，不是 WCN7880；WLAN 系列补丁的板级文件/电压表要换 |
| `thermal_table` | `captured (5005 bytes, needs manual review)` | live | board_specific | `xnu/patches/0333,0335,0337,0339,0340` | ✅ | byron 8000mAh + different chassis: all thresholds and the 95C junction hysteresis must be  |
| `battery_gauge` | `fuel gauge ti,bq27z561_master` | stock_dump | board_specific | `xnu/patches pandora_gauge` | ✅ | byron 8000mAh + P3/G2 charging ICs |
| `charger_ic` | `qcom,i2c-pmic` | stock_dump | board_specific | `xnu/patches charging` | ✅ | read /sys/class/power_supply + vendor DTBO |
| `brightness_dcs` | `DCS 0x51 (16-bit), dimming 0x53, peak 0xc65d40 (` | manual | board_specific | `xnu/patches/0139-0141 backlight` | ✅ | DSI test-pattern FIFO kickoff; byron's M10 panel uses a different range |
| `page_size_16k` | `yes (derived:arch ARMv9.2 Cortex-X925 TGran16, u` | manual | soc_shared | `shim/hello probe` | ✅ | XNU wants 16K pages; must be probed in a tiny bootloader before committing to a port |
| `abl_load_addr` | `—` | — | board_specific | `shim/loader/start.S` | ❌ 必需 | where ABL places the payload; upstream step 1 probe |
| `userdata_dev` | `/dev/block/sda34` | live | board_specific | `mac/phone_prepare.sh` | ✅ | always resolve /dev/block/by-name/userdata, never hardcode sdX |
| `userdata_lba` | `30380032..1029136343` | live | board_specific | `tools/pinfile rawwrite` | ✅ | dm-default-key table: full-block mapping, offset 0 |
| `pinned_extents` | `present on disk` | live | board_specific | `device/byron/extents/` | ✅ | generated by phone_prepare.sh on the byron unit; FIEMAP positions are device-specific |
| `firmware_files` | `632 files: 05B04A44-BF30-42DF-9E2F-B366B980ED19.` | firmware | board_specific | `xnu/patches fw packs` | ✅ | extract from /vendor/firmware_mnt (vendor 分区尚未解包); byron 是 WCN786x; never commit vendor bl |
| `stock_boot_b_sha256` | `present on disk` | live | board_specific | `backup/manifest.txt` | ✅ | tools/backup.sh on the byron unit, before any bootmgr experiment |

## 仍然无法自动化、必须人在真机上做

1. `shim/hello` 探测：framebuffer 宽/高/stride/格式、16K 页支持、ABL 装载地址。**只读 SSPP 子块**，读 MDSS 顶层寄存器会在时钟关闭时让整机重启（上游 t2 实测）。
2. TLMM 真实基址：DT 写 `0x0f000000`，SM8850 硬件实测 `0x0f100000`，必须自行确认。
3. 触摸主屏确认 IRQ、逐个按物理键确认 GPIO、面板亮度 DCS 读回。
4. 首次真机启动用 60–120 秒短超时（`pandora_reboot_after`），并先跑 `tools/safe_boot.sh` 的 dry-run。

> 数据齐全 ≠ 能开机。所有 `required` 项齐备且 `--attest` 之后，`tools/safe_boot.sh` 还有 12 项运行时检查（备份、`boot_b` 哈希、DSU 状态、pinned 文件、机型、超时）才会放行 `--commit`。
