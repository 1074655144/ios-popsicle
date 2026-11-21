#!/bin/bash
# 本地回归测试：用 mock adb/fastboot/launcher 验证 DSU 式安全启动的行为。
# 不连接真机、不写任何分区。运行：bash tools/tests/test_safe_boot.sh
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
SAFE="$ROOT/tools/safe_boot.sh"
RECOVER="$ROOT/tools/safe_recover.sh"
T=$(mktemp -d /tmp/safeboot.XXXXXX)
trap 'rm -rf "$T"' EXIT
LOG="$T/mock.log"
PASS=0 FAILN=0

fail() { echo "  FAIL: $1"; FAILN=$((FAILN + 1)); }
pass() { echo "  pass: $1"; PASS=$((PASS + 1)); }
assert_rc() {
  if [ "$RC" = "$1" ]; then pass "退出码 $RC"; else
    fail "期望退出码 $1，实际 $RC；输出: $(echo "$OUT" | head -3 | tr '\n' ' ')"
  fi
}
assert_out() { echo "$OUT" | grep -qF "$1" && pass "输出含 '$1'" || fail "输出缺 '$1'"; }
assert_log() { grep -qF "$1" "$LOG" && pass "执行了 '$1'" || fail "未执行 '$1'"; }
assert_no_log() { grep -qF "$1" "$LOG" && fail "不该执行却执行了 '$1'" || pass "未执行 '$1'"; }

# ---- mock 命令 ----------------------------------------------------------
cat > "$T/adb" <<'EOF'
#!/bin/bash
echo "adb $*" >> "${MOCK_LOG:?}"
case "$*" in
"devices") printf 'List of devices attached\nMOCK\tdevice\n' ;;
"shell getprop ro.product.device") printf '%s\n' "${MOCK_DEVICE:-popsicle}" ;;
"shell getprop ro.boot.slot_suffix") printf '_a\n' ;;
"shell getprop ro.gsid.image_running")
	[ "${MOCK_DSU:-0}" = 1 ] && printf '1\n' || printf '\n' ;;
"shell getprop ro.boot.dsu") printf '\n' ;;
*sha256sum*boot_b*) printf '%s  /dev/block/by-name/boot_b\n' "${MOCK_BOOTB_HASH:-GOODHASH}" ;;
*pandora_bootmgr_guard*) printf '%s\n' "${MOCK_GUARD:-}" ;;
*pinfile*status*iosroot.img*) printf 'iosroot.img: %s\n' "${MOCK_PINNED:-pinned (GC move failures 0)}" ;;
*pinfile*status*ioslog.img*) printf 'ioslog.img: %s\n' "${MOCK_PINNED:-pinned (GC move failures 0)}" ;;
*gsi_tool*) printf 'disabled\n' ;;
*) printf '\n' ;;
esac
EOF
cat > "$T/fastboot" <<'EOF'
#!/bin/bash
echo "fastboot $*" >> "${MOCK_LOG:?}"
case "$*" in
"devices") [ "${MOCK_IN_FASTBOOT:-0}" = 1 ] && printf 'MOCK\tfastboot\n' || printf '\n' ;;
*) printf 'OKAY\n' ;;
esac
EOF
cat > "$T/launcher" <<'EOF'
#!/bin/bash
echo "launcher $*" >> "${MOCK_LOG:?}"
printf 'mock launcher ok\n'
EOF
chmod +x "$T/adb" "$T/fastboot" "$T/launcher"

# ---- 固定素材 ----------------------------------------------------------
KERNEL="$T/kernel.macho"
echo "mock kernel" > "$KERNEL"
mkdir -p "$T/extents" "$T/state"
echo '{"extents":[]}' > "$T/extents/iosroot.json"
echo '{"extents":[]}' > "$T/extents/ioslog.json"
echo "stock boot" > "$T/stock_boot_b.img"
MANIFEST="$T/manifest.txt"
printf 'ok boot_a 12345 OTHERHASH\nok boot_b 12345 GOODHASH\n' > "$MANIFEST"
cat > "$T/popsicle.env" <<EOF
PROFILE_NAME="Test popsicle"
CODENAME=popsicle
SOC=SM8850
BOARD_DATA_COMPLETE=yes
LAUNCHER=mac/boot_ios.sh
EXTENTS_DIR=$T/extents
STOCK_BOOT_B=$T/stock_boot_b.img
EOF

BASE=(--adb "$T/adb" --fastboot "$T/fastboot" --launcher "$T/launcher"
      --backup-manifest "$MANIFEST" --state-dir "$T/state" --kernel "$KERNEL")
run_boot() {
	: > "$LOG"
	set +e
	OUT=$(env MOCK_LOG="$LOG" MOCK_DEVICE="${MOCK_DEVICE:-popsicle}" \
		MOCK_BOOTB_HASH="${MOCK_BOOTB_HASH:-GOODHASH}" MOCK_PINNED="${MOCK_PINNED:-pinned (GC move failures 0)}" \
		MOCK_DSU="${MOCK_DSU:-0}" MOCK_GUARD="${MOCK_GUARD:-}" \
		SAFE_BOOT_CONFIRM="${SAFE_BOOT_CONFIRM:-0}" \
		bash "$SAFE" "$@" 2>&1)
	RC=$?
	set -e
}
run_recover() {
	: > "$LOG"
	set +e
	OUT=$(env MOCK_LOG="$LOG" MOCK_DEVICE="${MOCK_DEVICE:-popsicle}" \
		MOCK_BOOTB_HASH="${MOCK_BOOTB_HASH:-GOODHASH}" \
		MOCK_IN_FASTBOOT="${MOCK_IN_FASTBOOT:-0}" SAFE_BOOT_CONFIRM="${SAFE_BOOT_CONFIRM:-0}" \
		bash "$RECOVER" "$@" 2>&1)
	RC=$?
	set -e
}

echo "== 0. 语法检查"
for f in "$SAFE" "$RECOVER" "$ROOT/mac/boot_ios.sh"; do
	if bash -n "$f"; then pass "bash -n $(basename "$f")"; else fail "bash -n $(basename "$f")"; fi
done

echo "== 1. byron 骨架：默认 dry-run 绝不启动"
run_boot --device byron --profile "$ROOT/profiles/byron.env" "${BASE[@]}"
MOCK_DEVICE=byron run_boot --device byron --profile "$ROOT/profiles/byron.env" "${BASE[@]}" --dry-run
assert_rc 0
assert_out "dry-run"
assert_out "板级数据未采集"
assert_no_log "launcher"
assert_no_log "flash"
assert_no_log "fastboot"

echo "== 2. byron 骨架：--commit 必须被拒绝"
MOCK_DEVICE=byron SAFE_BOOT_CONFIRM=1 run_boot --device byron --profile "$ROOT/profiles/byron.env" "${BASE[@]}" --commit
assert_rc 3
assert_no_log "launcher"
assert_no_log "flash"

echo "== 3. popsicle 全绿：真实启动只调用 launcher，绝不 flash"
SAFE_BOOT_CONFIRM=1 run_boot --profile "$T/popsicle.env" "${BASE[@]}" --commit
assert_rc 0
assert_log "launcher $KERNEL 180 "
assert_no_log "fastboot flash"
assert_no_log "adb reboot bootloader"
assert_out "已启动"

echo "== 4. boot_b 被改写（疑似装过 bootmgr）→ 拒绝"
MOCK_BOOTB_HASH=BADHASH SAFE_BOOT_CONFIRM=1 run_boot --profile "$T/popsicle.env" "${BASE[@]}" --commit
assert_rc 3
assert_out "boot_b 已被改动"
assert_no_log "launcher"

echo "== 5. pinned 文件未钉住 → 拒绝"
MOCK_PINNED="not pinned" SAFE_BOOT_CONFIRM=1 run_boot --profile "$T/popsicle.env" "${BASE[@]}" --commit
assert_rc 3
assert_out "未钉住"
assert_no_log "launcher"

echo "== 6. 超时非法 → 拒绝"
SAFE_BOOT_CONFIRM=1 run_boot --profile "$T/popsicle.env" "${BASE[@]}" --seconds 10 --commit
assert_rc 3
assert_out "60..900"
assert_no_log "launcher"

echo "== 7. DSU/GSI 仍在运行 → 拒绝"
MOCK_DSU=1 SAFE_BOOT_CONFIRM=1 run_boot --profile "$T/popsicle.env" "${BASE[@]}" --commit
assert_rc 3
assert_out "DSU"
assert_no_log "launcher"

echo "== 8. 机型不符 → 拒绝"
MOCK_DEVICE=byron SAFE_BOOT_CONFIRM=1 run_boot --profile "$T/popsicle.env" "${BASE[@]}" --commit
assert_rc 3
assert_out "机型不符"
assert_no_log "launcher"

echo "== 9. 缺分区备份 manifest → 拒绝"
SAFE_BOOT_CONFIRM=1 run_boot --profile "$T/popsicle.env" "${BASE[@]}" --backup-manifest "$T/nope.txt" --commit
assert_rc 3
assert_out "缺少分区备份"
assert_no_log "launcher"

echo "== 10. 回滚默认 dry-run：不写分区"
run_recover --profile "$T/popsicle.env" --adb "$T/adb" --fastboot "$T/fastboot" \
	--backup-manifest "$MANIFEST" --stock-boot-b "$T/stock_boot_b.img"
assert_rc 0
assert_out "dry-run"
assert_no_log "fastboot flash"
assert_no_log "adb shell gsi_tool disable"

echo "== 11. 回滚：boot_b 不一致时显式恢复才写一次分区"
MOCK_BOOTB_HASH=BADHASH SAFE_BOOT_CONFIRM=1 run_recover --profile "$T/popsicle.env" \
	--adb "$T/adb" --fastboot "$T/fastboot" --backup-manifest "$MANIFEST" \
	--stock-boot-b "$T/stock_boot_b.img" --restore-bootb --commit
assert_rc 0
assert_out "分区"
grep -qF "fastboot flash boot_b" "$LOG" && pass "执行了一次 flash boot_b" || fail "未执行 flash boot_b"

echo "== 12. 回滚：boot_b 一致时不写分区"
SAFE_BOOT_CONFIRM=1 run_recover --profile "$T/popsicle.env" \
	--adb "$T/adb" --fastboot "$T/fastboot" --backup-manifest "$MANIFEST" \
	--stock-boot-b "$T/stock_boot_b.img" --restore-bootb --commit
assert_rc 0
assert_no_log "fastboot flash"
assert_out "无需恢复"

echo
echo "结果：通过 $PASS 项，失败 $FAILN 项"
[ "$FAILN" = 0 ] || exit 1
