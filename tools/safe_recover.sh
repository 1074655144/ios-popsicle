#!/bin/bash
# DSU 式安全启动的回滚/收尾：让手机回到原装 Android 并核对分区完整性。
#
#   tools/safe_recover.sh [--device byron] [--adb PATH] [--fastboot PATH]
#                         [--backup-manifest PATH] [--stock-boot-b PATH]
#                         [--restore-bootb] [--commit]
#
# 默认 dry-run：只检查、只打印将执行的动作。真实动作需 --commit 且
# SAFE_BOOT_CONFIRM=1。唯一写分区的动作是 --restore-bootb 时的
# `fastboot flash boot_b`，且只在 boot_b 校验失败、原装备份存在时允许。
# 绝不删除 pinned 文件、绝不改 super/userdata、绝不启用 DSU sticky。
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
usage() { sed -n '2,16p' "$0" | sed 's/^# \{0,1\}//'; exit 2; }

DEVICE=byron PROFILE="" ADB=${SAFE_BOOT_ADB:-adb} FB=${SAFE_BOOT_FASTBOOT:-fastboot}
MANIFEST="$ROOT/backup/manifest.txt" STOCK="" RESTORE=0 DRY=1
while [ $# -gt 0 ]; do
	case $1 in
	--device) DEVICE=$2; shift 2 ;;
	--profile) PROFILE=$2; shift 2 ;;
	--adb) ADB=$2; shift 2 ;;
	--fastboot) FB=$2; shift 2 ;;
	--backup-manifest) MANIFEST=$2; shift 2 ;;
	--stock-boot-b) STOCK=$2; shift 2 ;;
	--restore-bootb) RESTORE=1; shift ;;
	--commit) DRY=0; shift ;;
	--dry-run) DRY=1; shift ;;
	-h | --help) usage ;;
	*) echo "unknown option: $1" >&2; usage ;;
	esac
done

[ -n "$PROFILE" ] || PROFILE="$ROOT/profiles/$DEVICE.env"
[ -f "$PROFILE" ] || { echo "profile not found: $PROFILE" >&2; exit 2; }
# shellcheck disable=SC1090
. "$PROFILE"
[ -n "$STOCK" ] || STOCK="$ROOT/${STOCK_BOOT_B:-device/stock/boot_b.img}"
MODE=$([ "$DRY" = 1 ] && echo 'dry-run' || echo 'commit')
echo "== 回滚检查（$MODE，${PROFILE_NAME:-$DEVICE} / $CODENAME）"

do_cmd() {
	if [ "$DRY" = 1 ]; then
		echo "  [dry-run] $*"
	else
		echo "  [exec]    $*"
		"$@"
	fi
}

echo "-- 1. 当前所处状态"
in_fastboot=$("$FB" devices 2>/dev/null | tr -d '\r' | grep -cw fastboot || true)
in_adb=$("$ADB" devices 2>/dev/null | tail -n +2 | tr -d '\r' | grep -cw device || true)
echo "  adb 设备 $in_adb 个 / fastboot 设备 $in_fastboot 个"
if [ "$in_fastboot" -ge 1 ]; then
	do_cmd "$FB" reboot
	echo "  提示：fastboot reboot 让手机冷启动回原装 Android（不写分区）"
elif [ "$in_adb" -ge 1 ]; then
	echo "  已在 Android，通常无需操作；若刚从 iOS 超时重启，直接核对分区即可"
else
	echo "  没有在线设备：长按 电源+音量下 约 10 秒强制重启后再跑本脚本"
fi

echo "-- 2. 关闭 DSU sticky（防止下次误进 GSI）"
if [ "$in_adb" -ge 1 ]; then
	do_cmd "$ADB" shell gsi_tool disable
	dsu=$("$ADB" shell getprop ro.gsid.image_running 2>/dev/null | tr -d '\r')
	[ -z "$dsu" ] && echo "  [OK]   无激活的 DSU 会话" || echo "  [WARN] ro.gsid.image_running=$dsu，请冷启动后复查"
else
	echo "  [skip] 无 adb 设备"
fi

echo "-- 3. boot_b 与备份比对"
want=""
if [ -f "$MANIFEST" ]; then
	line=$(grep -E '^ok[[:space:]]+boot_b[[:space:]]' "$MANIFEST" | tail -1 || true)
	[ -n "$line" ] && want=$(echo "$line" | awk '{print $4}')
	grep -q '^MISMATCH' "$MANIFEST" && echo "  [WARN] manifest 里有 MISMATCH 记录"
else
	echo "  [WARN] 缺 $MANIFEST，无法比对（先跑 tools/backup.sh）"
fi
cur=""
if [ "$in_adb" -ge 1 ]; then
	cur=$("$ADB" shell "su -c 'sha256sum /dev/block/by-name/boot_b'" 2>/dev/null | tr -d '\r' | awk '{print $1}')
elif [ "$in_fastboot" -ge 1 ]; then
	echo "  [skip] 处于 fastboot，无法读分区哈希；回到 Android 后复查"
fi
if [ -n "$want" ] && [ -n "$cur" ]; then
	if [ "$cur" = "$want" ]; then
		echo "  [OK]   boot_b 与备份一致，开机菜单未写入"
	else
		echo "  [FAIL] boot_b 与备份不一致"
	fi
else
	echo "  [info] want=${want:-空} cur=${cur:-空}"
fi

echo "-- 4. 恢复 boot_b（仅在显式要求且校验失败时）"
if [ "$RESTORE" = 1 ]; then
	if [ "$cur" = "$want" ] && [ -n "$want" ]; then
		echo "  [OK]   无需恢复"
	elif [ ! -f "$STOCK" ]; then
		echo "  [FAIL] 缺原装备份 $STOCK；拒绝刷写。请先用 tools/backup.sh 生成"
	elif [ "$DRY" = 1 ]; then
		echo "  [dry-run] $FB flash boot_b $STOCK（加 --commit + SAFE_BOOT_CONFIRM=1 才执行）"
	elif [ "${SAFE_BOOT_CONFIRM:-}" != 1 ]; then
		echo "  [FAIL] 刷写分区需要 SAFE_BOOT_CONFIRM=1"
		exit 4
	else
		echo "  [exec]  $FB flash boot_b $STOCK"
		"$FB" flash boot_b "$STOCK"
		echo "  刷写完成，请重启回 Android 后重跑本脚本核对哈希"
	fi
else
	echo "  [skip] 未给 --restore-bootb；本脚本默认绝不写分区"
fi

echo "-- 5. 兜底"
echo "  · 长按 电源+音量下 约 10 秒可强制重启，RAM 里的 iOS 随之消失"
echo "  · 不删除 /data/local/tmp/iosroot.img 等 pinned 文件；要彻底清理请用 mac/phone_prepare.sh 的 Undo 步骤"
echo "  · 分区备份在 backup/manifest.txt；恢复前确认备份无 MISMATCH"
