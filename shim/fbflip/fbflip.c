/*
 * byron 显示链路"红蓝翻转"诊断镜像 (fastboot boot, 纯 RAM, 不写分区).
 *
 * 目的: 用最朴素的整屏纯色, 区分花屏的两种根因——
 *   A) 数据上了屏但格式错 (UBWC 压缩 / stride / 字节序): 屏幕会随纯色翻转成红/蓝.
 *   B) 数据根本没上屏 (command-mode 无持续刷新 / buffer 地址错): 屏幕始终静止花屏, 不变色.
 *
 * 关键: 纯色填充对 stride/width/字节序都不敏感——只要屏幕能在红蓝之间整体切换,
 * 就证明 CPU->显存->面板这条链是通的, 花屏只是格式问题; 反之链路本身不通.
 *
 * 阶段 (每阶段 6 秒, 循环 3 轮 = 36 秒):
 *   1. 整屏 0xFFFF0000 (ARGB 语义纯红)
 *   2. 整屏 0xFF0000FF (ARGB 语义纯蓝)
 *   3. 上半红 / 下半蓝 (检查垂直方向连续性)
 *   4. 上半蓝 / 下半红
 * 若 H 翻转可见但整体仍花, 说明垂直 stride 有问题; 若纯色都不变色, 属断点 B.
 *
 * 36 秒后 PSCI SYSTEM_RESET 自动回安卓. 长按电源可提前重启.
 */
#include <stdint.h>

#define FB          0xfc800000ull
#define FB_W        1200u
#define FB_H        2608u
#define FB_STRIDE   4800u          /* = 1200 * 4, stridescan 实证 */

static volatile uint32_t *const fb = (volatile uint32_t *)(uintptr_t)FB;

#define RED   0xffff0000u
#define BLUE  0xff0000ffu

static void fill(uint32_t y0, uint32_t h, uint32_t c)
{
	for (uint32_t y = y0; y < y0 + h && y < FB_H; y++) {
		volatile uint32_t *line = fb + y * (FB_STRIDE / 4);
		for (uint32_t x = 0; x < FB_W; x++)
			line[x] = c;
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
	register uint64_t x0 __asm__("x0") = 0x84000009;
	__asm__ volatile("smc #0" : "+r"(x0) :: "x1","x2","x3","memory");
	for (;;) __asm__ volatile("wfe");
}

void fbflip_main(uint64_t fdt, uint64_t el, uint64_t load)
{
	(void)fdt; (void)el; (void)load;

	for (int round = 0; round < 3; round++) {
		fill(0, FB_H, RED);            delay_s(6);   /* 全红 */
		fill(0, FB_H, BLUE);           delay_s(6);   /* 全蓝 */
		fill(0, FB_H / 2, RED);        /* 上半红 */
		fill(FB_H / 2, FB_H / 2, BLUE);/* 下半蓝 */
		delay_s(6);
		fill(0, FB_H / 2, BLUE);       /* 上半蓝 */
		fill(FB_H / 2, FB_H / 2, RED); /* 下半红 */
		delay_s(6);
	}
	reboot();
}
