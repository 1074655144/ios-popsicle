#!/usr/bin/env python3
"""透视校正 stridescan 手机照片，并分析每个横带的条纹周期与竖直度。"""
import sys
import numpy as np
from PIL import Image

PHOTO = sys.argv[1] if len(sys.argv) > 1 else r"C:\Users\qq107\.workbuddy\clipboard-images\clipboard-2026-11-21T06-38-35-688Z-5f67e504.jpg"
OUTDIR = r"C:\Users\qq107\WorkBuddy\2026-11-14-14-16-35\ios-popsicle\device\byron\live"
SCALE = 2.0  # 缩略图(720x960)坐标 -> 原图(1440x1920)

img = Image.open(PHOTO).convert("RGB")
arr = np.asarray(img).astype(np.float32)
H, W = arr.shape[:2]
print(f"photo size = {W}x{H}")

# 屏幕四角（720x960 缩略图坐标，目测）—— 按 左上/右上/右下/左下，乘以 SCALE
src = np.array([
    [183, 72],    # 左上
    [540, 80],    # 右上
    [548, 860],   # 右下
    [160, 845],   # 左下
], dtype=np.float64) * SCALE

DW, DH = 608, 1304  # 校正后尺寸（面板宽:高 ≈ 1216:2608 的一半）
dst = np.array([[0, 0], [DW - 1, 0], [DW - 1, DH - 1], [0, DH - 1]], dtype=np.float64)


def homography(s, d):
    A = []
    for (x, y), (u, v) in zip(s, d):
        A.append([x, y, 1, 0, 0, 0, -u * x, -u * y, -u])
        A.append([0, 0, 0, x, y, 1, -v * x, -v * y, -v])
    A = np.asarray(A, dtype=np.float64)
    _, _, Vt = np.linalg.svd(A)
    M = Vt[-1].reshape(3, 3)
    return M / M[2, 2]


Hm = homography(src, dst)
Hinv = np.linalg.inv(Hm)

# 反向映射 + 双线性采样
yy, xx = np.mgrid[0:DH, 0:DW]
p = Hinv @ np.stack([xx.ravel(), yy.ravel(), np.ones(DW * DH)])
sx = p[0] / p[2]
sy = p[1] / p[2]
sx = np.clip(sx, 0, W - 1)
sy = np.clip(sy, 0, H - 1)
x0 = sx.astype(int); y0 = sy.astype(int)
x1 = np.clip(x0 + 1, 0, W - 1); y1 = np.clip(y0 + 1, 0, H - 1)
wx = (sx - x0)[:, None]; wy = (sy - y0)[:, None]

c00 = arr[y0, x0]; c10 = arr[y0, x1]
c01 = arr[y1, x0]; c11 = arr[y1, x1]
out = (c00 * (1 - wx) * (1 - wy) + c10 * wx * (1 - wy) +
       c01 * (1 - wx) * wy + c11 * wx * wy)
out = np.clip(out, 0, 255).astype(np.uint8).reshape(DH, DW, 3)

rect_path = f"{OUTDIR}\\stridescan_rectified.png"
Image.fromarray(out).save(rect_path)
print("rectified saved:", rect_path)

# 分四个横带，每带 650/2 = 325 行
BAND = DH // 4
for i in range(4):
    band = out[i * BAND:(i + 1) * BAND]
    Image.fromarray(band).save(f"{OUTDIR}\\stridescan_band{i}.png")

    g = band.mean(axis=2)
    # 只用中间区域避开边缘透视残差
    core = g[:, 40:-40]
    # 水平方向自相关找条纹周期：对每一行做 FFT，取主频
    profile = core.mean(axis=0)
    prof = profile - profile.mean()
    spec = np.abs(np.fft.rfft(prof * np.hanning(len(prof))))
    freqs = np.fft.rfftfreq(len(prof))
    # 排除直流，找前几个峰
    idx = np.argsort(spec[1:])[::-1][:5] + 1
    peaks = [(round(1.0 / freqs[k], 1) if freqs[k] > 0 else 0, round(spec[k], 1)) for k in idx[:3]]

    # 竖直度：对相邻行计算最佳水平位移 dx（互相关），看是否稳定为 0
    shifts = []
    ref = core[core.shape[0] // 2]
    ref = ref - ref.mean()
    ref_f = np.fft.rfft(ref * np.hanning(len(ref)))
    for y in range(20, core.shape[0] - 20, 20):
        row = core[y] - core[y].mean()
        if np.std(row) < 3:
            continue
        cross = np.fft.irfft(np.fft.rfft(row * np.hanning(len(row))) * np.conj(ref_f))
        cross = np.roll(cross, len(cross) // 2)
        dx = np.argmax(cross) - len(cross) // 2
        shifts.append(dx)
    shifts = np.array(shifts)
    print(f"band{i}: FFT period(pix)={peaks}  rowshift mean={shifts.mean():+.2f} std={shifts.std():.2f} min={shifts.min()} max={shifts.max()} (n={len(shifts)})")
