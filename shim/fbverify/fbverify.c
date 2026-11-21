/*
 * byron framebuffer 参数肉眼验证程序 (fastboot boot, 纯 RAM, 不写分区).
 *
 * 目的: 用 stridescan 实证的线性 splash 参数 (1200x2608, stride 4800) 往 cont_splash_region 0xfc800000
 * 写已知测试图案, 让用户拍照判断三件事:
 *   0) 【2026-11-21 修正】splash FB 真值 = 1200x4=4800 (band0 实证); 之前 1216/4864 是 Android
 *      UBWC 运行帧缓冲 fb370 的参数, 不适用于 fastboot 后的线性 splash FB, 是花屏根因.
 *   1) stride/width 对不对 —— 棋盘格/边框若倾斜或右侧留黑边, 说明参数错.
 *   2) 字节序 —— 上半部色块用 ARGB word 语义, 下半部用 BGRA word 语义;
 *      看哪一组"红是红、蓝是蓝".
 *   3) 面板有效宽度 —— 边框画到 1216, 若面板只显示 1200 则右边一条被裁掉 (正常).
 *
 * 约 25 秒后 PSCI SYSTEM_RESET 自动回安卓. 长按电源可提前重启.
 */
#include <stdint.h>
#include "font.h"

/* stridescan 实证参数 (2026-11-21): 线性 splash FB pitch = 4800 = 1200*4 */
#define FB          0xfc800000ull
#define FB_W        1200u
#define FB_H        2608u
#define FB_STRIDE   4800u          /* = 1200 * 4, popsicle 原值, stridescan band0 实证 */
#define PANEL_W     1200u          /* dmesg hactive, 现在 = FB_W */

static volatile uint32_t *const fb = (volatile uint32_t *)(uintptr_t)FB;

/* ARGB word 语义 (loader.c 当前用法): 0xAARRGGBB */
#define A(r,g,b)    (0xff000000u | ((r)<<16) | ((g)<<8) | (b))
/* BGRA word 语义 (把 R/B 位对调): 0xAABBGGRR */
#define B(r,g,b)    (0xff000000u | ((b)<<16) | ((g)<<8) | (r))

static void px(uint32_t x, uint32_t y, uint32_t c)
{
	if (x >= FB_W || y >= FB_H) return;
	fb[y * (FB_STRIDE / 4) + x] = c;
}

static void fill(uint32_t x0, uint32_t y0, uint32_t w, uint32_t h, uint32_t c)
{
	for (uint32_t y = y0; y < y0 + h && y < FB_H; y++) {
		volatile uint32_t *line = fb + y * (FB_STRIDE / 4);
		for (uint32_t x = x0; x < x0 + w && x < FB_W; x++)
			line[x] = c;
	}
}

static void hline(uint32_t x0, uint32_t x1, uint32_t y, uint32_t c)
{
	for (uint32_t x = x0; x < x1; x++) px(x, y, c);
}
static void vline(uint32_t x, uint32_t y0, uint32_t y1, uint32_t c)
{
	for (uint32_t y = y0; y < y1; y++) px(x, y, c);
}

/* 8x16 字库放大显示一行文字 */
static void text(int x0, int y0, const char *s, uint32_t fg, uint32_t bg, int scale)
{
	int cx = x0;
	for (const char *p = s; *p; p++) {
		if (*p < 0x20 || *p > 0x7e) continue;
		const unsigned char *g = font8x16[(int)(*p - 0x20)];
		for (int gy = 0; gy < 16; gy++)
			for (int gx = 0; gx < 8; gx++)
				fill(cx + gx * scale, y0 + gy * scale, scale, scale,
				     (g[gy] & (0x80 >> gx)) ? fg : bg);
		cx += 9 * scale;
	}
}

static uint64_t tick(void)
{
	uint64_t v;
	__asm__ volatile("mrs %0, cntvct_el0" : "=r"(v));
	return v;
}
static void delay_s(uint64_t s)
{
	uint64_t frq;
	__asm__ volatile("mrs %0, cntfrq_el0" : "=r"(frq));
	uint64_t start = tick(), limit = frq * s;
	while (tick() - start < limit) __asm__ volatile("wfe");
}
static void reboot(void) __attribute__((noreturn));
static void reboot(void)
{
	register uint64_t x0 __asm__("x0") = 0x84000009; /* PSCI SYSTEM_RESET */
	__asm__ volatile("smc #0" : "+r"(x0) :: "x1","x2","x3","memory");
	for (;;) __asm__ volatile("wfe");
}

void fbverify_main(uint64_t fdt, uint64_t el, uint64_t load)
{
	(void)fdt; (void)el; (void)load;

	const uint32_t white = 0xffffffffu, black = 0xff000000u;

	/* 整屏背景深灰 */
	fill(0, 0, FB_W, FB_H, 0xff404040u);

	/* ---- 顶部: 标题 ---- */
	fill(0, 0, FB_W, 120, 0xff000080u);
	text(30, 24, "BYRON FB VERIFY  1200x2608  STRIDE 4800", white, 0xff000080u, 3);

	/* ---- 第 1 组色条: ARGB word 语义 (loader.c 当前) ---- */
	/* 期望: 若屏幕字节序=ARGB, 这组显示 红绿蓝; 若=ABGR, 红蓝互换 */
	uint32_t y1 = 140;
	fill(30, y1, 400, 90, A(255,0,0));   /* ARGB 红 */
	fill(440, y1, 400, 90, A(0,255,0));  /* ARGB 绿 */
	fill(850, y1, 340, 90, A(0,0,255));  /* ARGB 蓝 */
	text(30, y1 + 96, "ROW A = ARGB word 0xAARRGGBB", white, 0xff404040u, 2);

	/* ---- 第 2 组色条: BGRA word 语义 (R/B 对调) ---- */
	uint32_t y2 = y1 + 160;
	fill(30, y2, 400, 90, B(255,0,0));
	fill(440, y2, 400, 90, B(0,255,0));
	fill(850, y2, 340, 90, B(0,0,255));
	text(30, y2 + 96, "ROW B = BGRA word 0xAABBGGRR", white, 0xff404040u, 2);

	/* ---- 棋盘格区: 检查 stride/倾斜 ---- */
	uint32_t gy = y2 + 180;
	uint32_t cell = 48;
	for (uint32_t r = 0; r < 8; r++)
		for (uint32_t c = 0; c < 24; c++)
			if ((r + c) & 1)
				fill(c * cell, gy + r * cell, cell, cell, white);
	text(30, gy + 8 * cell + 8, "CHECKER = stride/tilt test", 0xff00ff00u, black, 2);

	/* ---- 面板 1200 参考线: 边框画到 1216, 若面板只显示 1200 则右边被裁 ---- */
	vline(PANEL_W - 1, gy + 8 * cell + 60, FB_H - 20, 0xffffff00u);
	text(PANEL_W - 320, gy + 8 * cell + 64, "1200 REF", 0xffffff00u, black, 2);

	/* 整屏外边框 */
	hline(0, FB_W, 0, 0xffff00ffu);
	hline(0, FB_W, FB_H - 1, 0xffff00ffu);
	vline(0, 0, FB_H, 0xffff00ffu);
	vline(FB_W - 1, 0, FB_H, 0xffff00ffu);

	/* 约 25 秒后自动重启回安卓 */
	delay_s(25);
	reboot();
}
