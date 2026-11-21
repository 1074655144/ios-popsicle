# byron 官方 OTA 取包存证（离线只读）

> 本轮**已经**用小米官方 OTA 做了真实固件解析，不再是手工构造的样本。
> 全过程只有 HTTP `Range: bytes` 的 GET 和写本机文件，**没有连接手机、没有写任何分区**。

## 1. 输入

| 项 | 值 |
|---|---|
| 包名 | `byron-ota_full-OS4.0.4.0.XAFCNXM-user-17.0-2aa8107df3.zip` |
| 服务器 | `ultimateota.d.miui.com`（URL 带 `t` / `s` 签名参数，会过期，复现时需换成当次有效链接） |
| ZIP 大小 | 9,456,114,743 B（8.81 GiB），ZIP64，`Accept-Ranges: bytes` |
| build fingerprint | `Xiaomi/byron/byron:17/CP2A.260605.016/17OS4.0.261028.232329496.QCPECN.S:user/release-keys` |
| incremental | `17OS4.0.261028.232329496.QCPECN.S` |
| SDK / 补丁 | Android 17 / SDK 37 / security patch 2026-10-01 |
| post-timestamp | 1793205578 → 2026-10-28 16:39:38 UTC |
| `pre-device` | `byron` |
| `ota-type` | `AB` |

ZIP 共 7 个条目：`payload.bin`（9,456,105,946 B，store）、`payload_properties.txt`、
`apex_info.pb`、`care_map.pb`、`META-INF/*`。

## 2. payload 结构

| 项 | 值 |
|---|---|
| magic / version | `CrAU` / 2 |
| manifest 大小 | 348,007 B（读取范围 5149–353155） |
| metadata signature | 267 B |
| 数据区起点（文件内绝对偏移） | 353,423 |
| 分区数 / block size | 58 / 4096 |
| `FILE_HASH` | `H3pEUZ7YTFWbH3LzE5IQHVMlJF3xXDgUQKllidnI6ug=` |

新版 manifest 的分区在 protobuf field 13（不是旧版的 2），分区名 field 1、
`new_partition_info` field 7、`InstallOperation` field 8。每个 op 的
`data_sha256_hash`（field 8）都逐块校验过，任一不符即中止。

## 3. 实际取回的镜像（按需 Range，而非整包）

| 文件 | 重建大小 | 说明 | SHA-256 |
|---|---|---|---|
| `device/byron/firmware/dtbo.img` | 23,068,672 B | 11 个 op，但只有 1 个 55,144 B 的 XZ 块有实数据，其余是零填充 | `89e03e5dcca9cdc07e39eebff4602b2aec81ef5fd927c160a80dd8a2964dcab6` |
| `device/byron/firmware/vendor_boot.img` | 100,663,296 B | v4 头，DTB 段在 +21,790,720，长 6,557,211 B | `3dc70be868b18c24aefbbedd28898790dfa3dc7598331b700c14720f69ceb291` |
| `device/byron/firmware/boot.img` | 100,663,296 B | 通用 boot 镜像，未发现有效 FDT（唯一 magic 命中是随机字节） | `cf64ea3d6842fd63baca0f32e9e22fbabd2a754f900fbc5dcf585793ba3936cf` |

CDN 会截断较大的单次 Range，因此取包工具按 1 MiB 分块读取、逐块校验并重试。
**没有下载 8.81 GiB 的完整包**；dtbo 的实数据只传了约 56 KB。

## 4. 拆出的设备树

- `dtbo.img`：`dt_table_header` 2 个条目 →
  `dtbs/dtb-00.dtb` 137,267 B、`dtbs/dtb-01.dtb` 555,851 B，
  model 均为 **`Qualcomm Technologies, Inc. Byron based on SM8850`**。
- `vendor_boot.img` DTB 段：12 个首尾相接的 FDT（合计正好 6,557,211 B），
  model 为 Canoe / CanoeP / CanoeP SG / Whale / WhaleP 等 SM8850 家族变体
  （含 `Alt. Thermal Profile` / `v2`）。这是 **SoC 基础树**；dtbo 是叠在其上的板级层。
- 因此 `analyze_firmware.py` 必须同时喂 14 个 DTB，否则 GIC/内存/CPU 等常量会全部判为 `missing`。

## 5. 复现命令

```bash
URL='<当次有效的签名 URL>'
OUT=device/byron/firmware

python3 tools/port/fetch_ota.py --url "$URL" --list \
    --describe-json "$OUT/ota_manifest.json"
python3 tools/port/fetch_ota.py --url "$URL" --partition dtbo \
    --out "$OUT/dtbo.img"
python3 tools/port/fetch_ota.py --url "$URL" --partition vendor_boot \
    --out "$OUT/vendor_boot.img"
python3 tools/port/fetch_ota.py --url "$URL" --partition boot \
    --out "$OUT/boot.img"
python3 tools/port/fetch_ota.py --url "$URL" --entry payload_properties.txt \
    --out "$OUT/payload_properties.txt"

python3 tools/port/split_dtbo.py --dtbo "$OUT/dtbo.img" \
    --out-dir "$OUT/dtbs" --meta "$OUT/dtbo_meta.json"
python3 tools/port/extract_boot_dtbs.py --vendor-boot "$OUT/vendor_boot.img" \
    --out-dir "$OUT/base_dtbs" --meta "$OUT/base_dtbs.json"

python3 tools/port/analyze_firmware.py \
    --dtb "$OUT"/base_dtbs/*.dtb "$OUT"/dtbs/*.dtb \
    --device byron --out device/byron/firmware.json \
    --report docs/byron/FIRMWARE_DIFF.md
```

## 6. 数据边界

- 上述文件都在 `device/byron/` 下，被上游 `.gitignore` 的 `/device/*` 忽略——
  **只放本地，不提交**；仓库里不要出现任何厂商固件或苹果固件二进制。
- `vendor`（589 MB，erofs）里的 `/vendor/firmware_mnt` **尚未解包**，
  所以 `firmware_files` 仍是 `pending_firmware`。
- 未接触真机。`/data/vendor/thermal/decrypt.txt`、pinned extents、TLMM 真实基址、
  framebuffer 寄存器这些只能从 byron 本机只读采集，见 `docs/byron/PORTING_GUIDE.md`。

## 7. 用户提供的 9008 字库备份（2026-11-20）

用户给出本机完整字库备份 `<local firmware dump>`（164 个分区镜像，5.0 GB）。
这是**真机自身的只读镜像**，比 OTA 更可信。处理全程只读，未写任何分区。

**版本交叉验证**（`tools/port/extract_stock_dump.py`）：

| 分区 | 字库 SHA-256 | 与 OTA 比对 |
|---|---|---|
| `boot_a.img` | `cf64ea3d6842fd63baca0f32e9e22fbabd2a754f900fbc5dcf585793ba3936cf` | 完全一致 |
| `vendor_boot_a.img` | `3dc70be868b18c24aefbbedd28898790dfa3dc7598331b700c14720f69ceb291` | 完全一致 |
| `dtbo_a.img` | `0f6bffbcd4a095415da5bd20af4e66cfc47587941f290d840e8cf62d5801ba82` | 去零有效区一致（字库保留 32 MB 满分区填充） |

→ 确认字库 = OTA `OS4.0.4.0.XAFCNXM` 同一构建，之前 diff 结论全部成立。
（A/B 双槽哈希不同属正常——两个槽可能处于不同更新时点。）

**从字库新提取的板级事实** → `device/byron/stock_dump.json`：

- 芯片型号（DTB）：电量计 `ti,bq27z561_master`、充电 PMIC `smb1501`、Wi-Fi `qcom,wcn786x`、
  功放 `tfa98xx_1@34`、触摸 `synaptics,tcm-spi`。
  → popsicle 的功放是 CS35L43，byron 是 tfa98xx，驱动必须改。
- `persist.img`（ext4，用 WSL `debugfs` 只读导出）：
  面板 ID / cell ID / Wi-Fi MAC 等均为设备唯一值，仅记录在本地 `device/byron/`，
  功放双通道校准 `CH[0] T:5976 / CH[1] B:5722`、完整 demura/色温 LUT。
- 字库**没有** `vendor`/`system` 分区（在 `super` 动态分区里，此备份未含），
  所以 `firmware_files` 仍需真机 `/vendor/firmware_mnt` 采集。

**字库无法替代的部分**：`ddr.img`/`cdt.img` 是二进制训练数据，不含运行时寄存器值；
`memory_banks`/`splash_size`（DT 里 `<0 0>`，ABL 运行时填）、framebuffer 参数、
TLMM 真基址 `0x0f100000`、16K 页、ABL 装载地址仍须真机只读采集或引导阶段探测。

安全提醒：字库含 IMEI/MAC/校准等**设备唯一数据**，只在本地 `device/byron/`（已被忽略），
**不要公开上传**。
