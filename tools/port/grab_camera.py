#!/usr/bin/env python3
"""从 USB 摄像头连续抓帧, 保存清晰度最高的一帧, 供 stride 扫描判定.
用法:
  python3 tools/port/grab_camera.py --seconds 100 --out device/byron/live/camera_capture.png
  python3 tools/port/grab_camera.py --once   # 单帧快速测试 (确认摄像头能看到手机屏幕)
"""
import argparse
import time
import cv2
import numpy as np


def sharpness(frame):
    """拉普拉斯方差, 越高越清晰 (对焦准/无运动模糊)."""
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    return cv2.Laplacian(gray, cv2.CV_64F).var()


def open_camera(index=None):
    # 优先尝试常见索引; 若指定则用指定值
    candidates = [index] if index is not None else [0, 1, 2]
    for idx in candidates:
        cap = cv2.VideoCapture(idx, cv2.CAP_MSMF)
        if not cap.isOpened():
            cap = cv2.VideoCapture(idx)
        if cap.isOpened():
            print(f"camera opened: index={idx} "
                  f"W={int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))} "
                  f"H={int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))}")
            return cap, idx
    return None, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, default=100.0)
    ap.add_argument("--out", default="device/byron/live/camera_capture.png")
    ap.add_argument("--index", type=int, default=None)
    ap.add_argument("--interval", type=float, default=0.5)
    ap.add_argument("--once", action="store_true")
    args = ap.parse_args()

    cap, idx = open_camera(args.index)
    if cap is None:
        print("ERROR: no camera opened")
        return 1

    # 预热: 丢弃前几帧
    for _ in range(6):
        cap.read()
        time.sleep(0.05)

    ok, frame = cap.read()
    if not ok or frame is None:
        print("ERROR: cannot read frame")
        cap.release()
        return 1

    if args.once:
        cv2.imwrite(args.out, frame)
        print(f"saved single frame -> {args.out} ({frame.shape[1]}x{frame.shape[0]}) "
              f"sharpness={sharpness(frame):.1f}")
        cap.release()
        return 0

    best = frame.copy()
    best_score = sharpness(frame)
    t0 = time.time()
    n = 0
    print(f"capturing for {args.seconds}s, interval={args.interval}s ...")
    while time.time() - t0 < args.seconds:
        ok, frame = cap.read()
        if not ok or frame is None:
            time.sleep(args.interval)
            continue
        n += 1
        sc = sharpness(frame)
        if sc > best_score:
            best_score = sc
            best = frame.copy()
        time.sleep(args.interval)

    cv2.imwrite(args.out, best)
    print(f"done: {n} frames, saved最清晰帧 -> {args.out} "
          f"({best.shape[1]}x{best.shape[0]}) sharpness={best_score:.1f}")
    cap.release()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
