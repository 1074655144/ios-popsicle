#!/usr/bin/env python3
"""捕获 byron USB CDC ACM 探测程序的输出并解析板级参数.

用法:
  python3 tools/port/capture_usb_probe.py --out device/byron/live/usb_probe.txt

流程:
  1. 轮询串口, 等待 VID=1209 PID=316D 的 CDC ACM 设备出现 (探测程序 fastboot boot 后
     会重新枚举成这个 USB 串口). 也接受 --port COMx 直接指定.
  2. 读到 "===BYRON_USB_PROBE_BEGIN===" 开始记录, 到 "===BYRON_USB_PROBE_END==="
     结束. 超时或失败兜底 (BYRON_USB_FAIL) 也会记录.
  3. 解析 W/H/STRIDE/FMT/LOAD/MMFR0/GCTL/... 各行, 打印人类可读的结果, 并存盘.

退出码: 0 拿到完整探测; 1 超时未拿到; 2 参数错误.
"""
import argparse
import os
import sys
import time

try:
    import serial
    import serial.tools.list_ports
except ImportError:
    sys.stderr.write("需要 pyserial: python3 -m pip install pyserial\n")
    sys.exit(2)

VID, PID = 0x1209, 0x316D
BEGIN = "BYRON_USB_PROBE_BEGIN"
END = "BYRON_USB_PROBE_END"
FAIL = "BYRON_USB_FAIL"


def find_port(explicit):
    if explicit:
        return explicit
    for p in serial.tools.list_ports.comports():
        if p.vid == VID and p.pid == PID:
            return p.device
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", help="串口名 (如 COM12); 不指定则自动查找 VID:PID")
    ap.add_argument("--out", default="device/byron/live/usb_probe.txt")
    ap.add_argument("--wait", type=float, default=90.0, help="等待设备+数据的最长秒数")
    ap.add_argument("--baud", type=int, default=115200)
    args = ap.parse_args()

    print(f"[*] 等待探测设备 VID={VID:04x} PID={PID:04x} " +
          (f"(指定 {args.port})" if args.port else "(自动查找)"))
    deadline = time.time() + args.wait
    ser = None
    port = None
    while time.time() < deadline:
        port = find_port(args.port)
        if port:
            try:
                ser = serial.Serial(port, args.baud, timeout=1)
                print(f"[+] 打开 {port}")
                break
            except serial.SerialException as e:
                print(f"[!] {port} 打开失败: {e}")
        time.sleep(0.5)
    if ser is None:
        print("[x] 超时: 未找到探测串口. 检查: 手机是否 fastboot boot 了 usbprobe-boot.img, "
              "Windows 是否装了 usbser 驱动 (设备管理器应出现 'USB Serial Device' 或未知设备 VID_1209 PID_316D).")
        return 1

    started = False
    failed = False
    lines = []
    data_deadline = time.time() + args.wait
    try:
        while time.time() < data_deadline:
            raw = ser.read(4096)
            if not raw:
                continue
            text = raw.decode("ascii", errors="replace")
            for line in text.replace("\r", "\n").split("\n"):
                line = line.strip()
                if not line:
                    continue
                if BEGIN in line:
                    started = True
                    lines = []
                    print("[+] 探测开始")
                if FAIL in line and not started:
                    failed = True
                    print("[!] 收到失败兜底 (USB 未起来), 记录诊断值")
                lines.append(line)
                print("    " + line)
                if (started and END in line) or (failed and "FAIL_END" in line):
                    ser.close()
                    return finish(lines, args.out, failed)
    finally:
        try:
            ser.close()
        except Exception:
            pass

    print("[x] 超时: 串口打开但未收到完整探测帧.")
    if lines:
        finish(lines, args.out, failed)
    return 1


def finish(lines, out, failed):
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"[+] 已保存 {out}")
    if not failed:
        parse(lines)
    return 0


def parse(lines):
    import re
    kv = {}
    for line in lines:
        if "=" in line and not line.startswith("==="):
            # 探测程序可能一行放多个 KEY=VALUE (如 "FB=0x.. W=1200 H=2608");
            # 每个 key 的值取到下一个 "KEY=" 之前. 逗号分隔的管道行 P0=..,.. 保持整体.
            matches = list(re.finditer(r'(?:^|\s)([A-Z][A-Z0-9_]*)=', line))
            for i, mt in enumerate(matches):
                k = mt.group(1)
                vstart = mt.end()
                vend = matches[i + 1].start() if i + 1 < len(matches) else len(line)
                kv[k] = line[vstart:vend].strip()
    print("\n===== 解析结果 =====")
    def show(k, label):
        if k in kv:
            print(f"  {label:16} = {kv[k]}")
    for k, label in [("EL", "异常级"), ("LOAD", "ABL装载地址"), ("MMFR0", "ID_AA64MMFR0_EL1"),
                     ("PAGES16K", "16K页"), ("FB", "framebuffer基址"), ("W", "fb宽"),
                     ("H", "fb高"), ("STRIDE", "stride"), ("FMT", "format"), ("PIPE", "SSPP管道"),
                     ("GCTL", "DWC3 GCTL"), ("DCTL", "DWC3 DCTL"), ("DSTS", "DWC3 DSTS")]:
        show(k, label)
    missing = [k for k in ("LOAD", "W", "H", "STRIDE", "FMT") if k not in kv]
    if missing:
        print(f"  [!] 缺少关键字段: {', '.join(missing)}")
    else:
        print("  [OK] 5 项必需参数 (LOAD/W/H/STRIDE/FMT) 全部拿到")


if __name__ == "__main__":
    sys.exit(main())
