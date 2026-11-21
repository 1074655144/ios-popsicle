#!/bin/bash
# DSU 式安全启动封装：一次性、只进内存、不写任何分区、超时自动回安卓。
#
# 注意：Android 官方 DSU 只替换 GSI(system) 镜像，沿用原厂 Linux kernel，
# 无法启动本项目自编译的 XNU 内核。本脚本提供的是 DSU 的「安全语义」：
#   - 一次性（不启用 sticky、不安装开机菜单）
#   - 不写分区（只 fastboot boot；绝不 fastboot flash）
#   - 可丢弃（冷启动即回原系统，iOS 数据只在 /data 的固定 pinned 文件里）
#   - 自动回滚（内核 pandora_reboot_after 到点重启）
#   - 启动前强制校验分区备份、boot_b 未被 bootmgr 改写、pinned 文件未移动
#
#   tools/safe_boot.sh --device byron --kernel KERNEL [--seconds 180]
#                      [--extra "boot-args"] [--commit] [--watch]
#                      [--adb PATH] [--fastboot PATH] [--launcher PATH]
#                      [--backup-manifest PATH] [--state-dir PATH]
#
# 默认 dry-run：只做全部前置检查并打印将执行的命令。
# 真实启动必须同时给 --commit 和 SAFE_BOOT_CONFIRM=1（或交互式输入 YES）。
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
usage() {
	sed -n '2,24p' "$0" | sed 's/^# \{0,1\}//'
	exit 2
}

DEVICE=byron PROFILE="" KERNEL="" SECS=180 EXTRA=""
ADB=${SAFE_BOOT_ADB:-adb} FB=${SAFE_BOOT_FASTBOOT:-fastboot}
LAUNCHER_CLI="" MANIFEST="$ROOT/backup/manifest.txt" STATE="$ROOT/device/sessions"
DRY=1 WATCH=0
while [ $# -gt 0 ]; do
	case $1 in
	--device) DEVICE=$2; shift 2 ;;
	--profile) PROFILE=$2; shift 2 ;;
	--kernel) KERNEL=$2; shift 2 ;;
	--seconds) SECS=$2; shift 2 ;;
	--extra) EXTRA=$2; shift 2 ;;
	--adb) ADB=$2; shift 2 ;;
	--fastboot) FB=$2; shift 2 ;;
	--launcher) LAUNCHER_CLI=$2; shift 2 ;;
	--backup-manifest) MANIFEST=$2; shift 2 ;;
	--state-dir) STATE=$2; shift 2 ;;
	--commit) DRY=0; shift ;;
	--dry-run) DRY=1; shift ;;
	--watch) WATCH=1; shift ;;
	-h | --help) usage ;;
	*) echo "unknown option: $1" >&2; usage ;;
	esac
done

FAILS=0
ok() { printf '  [OK]   %s\n' "$1"; }
bad() { printf '  [FAIL] %s\n' "$1"; FAILS=$((FAILS + 1)); }
plain() { printf '%s\n' "$1"; }

[ -n "$PROFILE" ] || PROFILE="$ROOT/profiles/$DEVICE.env"
if [ ! -f "$PROFILE" ]; then echo "profile not found: $PROFILE" >&2; exit 2; fi
# shellcheck disable=SC1090
. "$PROFILE"
CODENAME=${CODENAME:?profile: CODENAME}
COMPLETE=${BOARD_DATA_COMPLETE:-no}
EXDIR=${EXTENTS_DIR:-mac/extents}
# 相对路径按仓库根解析；绝对路径（含 Windows 盘符）原样使用。
case "$EXDIR" in /* | [A-Za-z]:*) EXABS=$EXDIR ;; *) EXABS="$ROOT/$EXDIR" ;; esac
# profile 里的 LAUNCHER 是相对仓库根的路径；命令行给的路径原样使用。
if [ -n "$LAUNCHER_CLI" ]; then
	LAUNCHER=$LAUNCHER_CLI
else
	L=${LAUNCHER:-mac/boot_ios.sh}
	case "$L" in /* | [A-Za-z]:*) LAUNCHER=$L ;; *) LAUNCHER="$ROOT/$L" ;; esac
fi

plain "== 0. 会话"
plain "  机型    : ${PROFILE_NAME:-$DEVICE} ($CODENAME, ${SOC:-?})"
plain "  模式    : $([ "$DRY" = 1 ] && echo 'dry-run（不会启动）' || echo 'commit（真实启动）')"
plain "  超时    : ${SECS}s 后内核自动重启回安卓"
plain "  profile : $PROFILE"

plain "== 1. 参数与板级数据"
[ -f "$KERNEL" ] && ok "内核文件 $KERNEL" || bad "内核文件不存在: $KERNEL"
case "$SECS" in
'' | *[!0-9]*) bad "--seconds 必须是整数" ;;
*) if [ "$SECS" -ge 60 ] && [ "$SECS" -le 900 ]; then ok "超时 ${SECS}s 在 60..900 范围内"; else bad "超时必须在 60..900 秒"; fi ;;
esac
[ -f "$LAUNCHER" ] && ok "启动器 $LAUNCHER" || bad "启动器不存在: $LAUNCHER"
if [ "$COMPLETE" = yes ]; then
	ok "板级数据已采集（$CODENAME）"
else
	bad "板级数据未采集：$CODENAME 是待验证骨架，禁止真实启动"
	plain "        见 docs/DSU_STYLE_SAFE_BOOT.md 的 byron 移植清单"
fi

plain "== 2. 手机与分区完整性"
online=$("$ADB" devices 2>/dev/null | tail -n +2 | tr -d '\r' | grep -cw device || true)
[ "$online" -ge 1 ] && ok "adb 设备在线" || bad "adb 没有在线设备"
got=$("$ADB" shell getprop ro.product.device 2>/dev/null | tr -d '\r')
[ "$got" = "$CODENAME" ] && ok "ro.product.device = $CODENAME" || bad "机型不符：手机是 '$got'，profile 要 '$CODENAME'"

if [ -f "$MANIFEST" ]; then
	if grep -q '^MISMATCH' "$MANIFEST"; then
		bad "分区备份 manifest 有校验失败项: $MANIFEST"
	else
		ok "分区备份 manifest 无 MISMATCH"
	fi
	line=$(grep -E '^ok[[:space:]]+boot_b[[:space:]]' "$MANIFEST" | tail -1 || true)
	if [ -n "$line" ]; then
		want=$(echo "$line" | awk '{print $4}')
		cur=$("$ADB" shell "su -c 'sha256sum /dev/block/by-name/boot_b'" 2>/dev/null | tr -d '\r' | awk '{print $1}')
		if [ -n "$want" ] && [ "$cur" = "$want" ]; then
			ok "boot_b 与备份一致（开机菜单未写入）"
		else
			bad "boot_b 已被改动（cur=${cur:-空} want=${want:-空}）——可能装过 bootmgr"
		fi
	else
		bad "manifest 里没有 boot_b 记录，请先跑 tools/backup.sh"
	fi
else
	bad "缺少分区备份: $MANIFEST（先跑 tools/backup.sh）"
fi

if [ "$online" -ge 1 ]; then
	guard=$("$ADB" shell "su -c 'ls /data/adb/modules/pandora_bootmgr_guard 2>/dev/null'" 2>/dev/null | tr -d '\r')
	[ -z "$guard" ] && ok "未安装 bootmgr guard 模块" || bad "检测到 bootmgr guard，安全启动要求卸载后再试"
else
	bad "无在线设备：无法确认 bootmgr guard 状态"
fi

plain "== 3. DSU / pinned 文件状态"
if [ "$online" -ge 1 ]; then
	dsu=""
	for p in ro.gsid.image_running ro.boot.dsu; do
		v=$("$ADB" shell getprop "$p" 2>/dev/null | tr -d '\r')
		[ -z "$v" ] || dsu="$dsu $p=$v"
	done
	[ -z "$dsu" ] && ok "未检测到激活的 DSU/GSI 会话" || bad "检测到 DSU 状态：$dsu（先跑 tools/safe_recover.sh）"
else
	bad "无在线设备：无法确认 DSU/GSI 状态"
fi

P=/data/local/tmp/pinfile
for f in iosroot.img ioslog.img; do
	st=$("$ADB" shell "su -c '$P status /data/local/tmp/$f'" 2>/dev/null | tr -d '\r')
	case "$st" in
	*': pinned (GC move failures 0)'*) ok "$f 已钉住且未被 GC 移动" ;;
	*) bad "$f 未钉住或已移动: ${st:-无响应}" ;;
	esac
done
for f in iosroot.json ioslog.json; do
	[ -f "$EXABS/$f" ] && ok "extents 记录 $f" || bad "缺 extents 记录 $EXABS/$f（需重跑 mac/phone_prepare.sh）"
done

plain "== 4. 结论"
if [ "$FAILS" -gt 0 ]; then
	plain "  前置检查失败 $FAILS 项。"
	[ "$DRY" = 1 ] && { plain "  dry-run：仅报告，未执行任何启动或写入。"; exit 0; }
	plain "  拒绝启动。修复后重试，或先跑 tools/safe_recover.sh。"
	exit 3
fi

mkdir -p "$STATE"
STAMP=$(date +%Y%m%d-%H%M%S)
SESSION="$STATE/session-$CODENAME-$STAMP.txt"
{
	plain "device=$CODENAME profile=$PROFILE"
	plain "soc=${SOC:-} board_data_complete=$COMPLETE"
	plain "kernel=$KERNEL"
	[ -f "$KERNEL" ] && plain "kernel_sha256=$(sha256sum "$KERNEL" | cut -d' ' -f1)"
	plain "seconds=$SECS extra=$EXTRA"
	plain "boot_b_hash=$(grep -E '^ok[[:space:]]+boot_b[[:space:]]' "$MANIFEST" | tail -1 | awk '{print $4}')"
	plain "mode=$([ "$DRY" = 1 ] && echo dry-run || echo commit)"
	plain "created=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
} > "$SESSION"
plain "  会话记录：$SESSION"

if [ "$DRY" = 1 ]; then
	plain "  dry-run：将执行 ->"
	plain "    IOS_DEVICE=$CODENAME IOS_EXTENTS_DIR=$EXABS \\"
	plain "    ADB_BIN=$ADB FASTBOOT_BIN=$FB bash $LAUNCHER $KERNEL $SECS \"$EXTRA\""
	plain "  未启动、未写入任何分区。确认无误后加 --commit 与 SAFE_BOOT_CONFIRM=1。"
	exit 0
fi

if [ "${SAFE_BOOT_CONFIRM:-}" != 1 ]; then
	if [ -t 0 ]; then
		read -r -p "  确认一次性 RAM 启动？输入 YES： " ans
		[ "$ans" = YES ] || { plain "  已取消"; exit 4; }
	else
		plain "  非交互环境需要 SAFE_BOOT_CONFIRM=1 才会真实启动"
		exit 4
	fi
fi

plain "== 5. 一次性 RAM 启动（不写分区）"
export IOS_DEVICE="$CODENAME" IOS_EXTENTS_DIR="$EXABS"
export ADB_BIN="$ADB" FASTBOOT_BIN="$FB"
bash "$LAUNCHER" "$KERNEL" "$SECS" "$EXTRA" || { plain "  启动器失败"; exit 5; }
plain "  已启动。${SECS}s 后内核自动重启回安卓。"
plain "  兜底：长按 电源+音量下 约 10 秒强制重启；或跑 tools/safe_recover.sh。"
if [ "$WATCH" = 1 ]; then
	sleep $((SECS + 90))
	if "$ADB" devices 2>/dev/null | grep -qw device; then
		plain "  已检测到 adb：Android 已恢复"
	else
		plain "  仍未检测到 adb：请长按 电源+音量下 10 秒，再跑 safe_recover.sh"
	fi
fi
