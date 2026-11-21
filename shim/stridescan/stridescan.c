/*
 * byron "stride 扫描" 镜像 (fastboot boot, 纯 RAM, 不写分区).
 *
 * 背景: 关UBWC 两条路都失败(NO PIPE / 全关直接重启). 重新审视证据:
 *       fbflip 纯色正常但复杂图案有【斜纹】—— 斜纹是 stride 不匹配的典型特征
 *       (每行水平错位逐行累积成斜线), 纯色看不出来. 我们此前把 stride 从
 *       popsicle 的 4800(=1200*4) 改成了 4864(=1216*4), 可能正是斜纹来源.
 *
 * 本镜像把屏幕纵向分 4 带, 每带用不同 stride 画【同样的垂直条纹 + 大字】:
 *   带0 (y=0..650)   : stride 4800 (1200*4)  label "S4800"
 *   带1 (y=650..1300): stride 4864 (1216*4)  label "S4864"
 *   带2 (y=1300..1950): stride 4928 (1232*4) label "S4928"
 *   带3 (y=1950..2600): stride 5120 (1280*4) label "S5120"
 *
 * 判定: 垂直条纹在哪个带里是【笔直、不倾斜】的, 那个 stride 就是真实值.
 *       条纹按 y*stride 定位行, 若 stride 用错, 各行起点水平错位 -> 斜纹.
 *
 * ~24s 后 PSCI SYSTEM_RESET 回安卓
 */
#include <stdint.h>
#include "font.h"

#define FB       0xfc800000ull
#define FB_W     1216u
#define FB_H     2608u

static volatile uint32_t *const fb = (volatile uint32_t *)(uintptr_t)FB;

static void put_char(int col, int row, char ch, uint32_t fg, uint32_t bg, uint32_t stride)
{
    const unsigned char *g = &font8x16[(uint8_t)ch - 0x20][0];
    for (int y = 0; y < 16; y++) {
        volatile uint32_t *line = fb + (uint64_t)(row * 16 + y) * (stride / 4) + col * 8;
        uint8_t bits = g[y];
        for (int x = 0; x < 8; x++)
            line[x] = (bits & (0x80u >> x)) ? fg : bg;
    }
}
static void put_str(int col, int row, const char *s, uint32_t fg, uint32_t bg, uint32_t stride)
{
    while (*s) { put_char(col++, row, *s++, fg, bg, stride); }
}

static uint64_t tick(void) { uint64_t v; __asm__ volatile("mrs %0, cntvct_el0" : "=r"(v)); return v; }
static void delay_s(uint64_t s)
{
    uint64_t frq; __asm__ volatile("mrs %0, cntfrq_el0" : "=r"(frq));
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

#define C_BLACK 0xff000000u
#define C_WHITE 0xffffffffu
#define C_RED   0xffff0000u
#define C_GREEN 0xff00ff00u
#define C_YELL  0xffffff00u
#define C_BAND_H 650u

/* 用给定 stride 画一个带: 黑底 + 垂直白条(每32px一条, 宽4px) + 顶部大字 label */
static void band(int idx, uint32_t stride, const char *label, uint32_t lc)
{
    uint32_t y0 = (uint32_t)idx * C_BAND_H;
    /* 黑底 + 垂直条纹 (行按 stride 定位) */
    for (uint32_t j = 0; j < C_BAND_H; j++) {
        volatile uint32_t *line = fb + (uint64_t)(y0 + j) * (stride / 4);
        for (uint32_t x = 0; x < FB_W; x++)
            line[x] = ((x % 32) < 4) ? lc : C_BLACK;
    }
    /* 顶部 label 横幅 (黑底) */
    for (uint32_t j = 0; j < 20; j++) {
        volatile uint32_t *line = fb + (uint64_t)(y0 + j) * (stride / 4);
        for (uint32_t x = 0; x < FB_W; x++) line[x] = C_BLACK;
    }
    put_str(1, (int)(y0 / 16), label, C_YELL, C_BLACK, stride);
}

void stridescan_main(uint64_t fdt, uint64_t el, uint64_t load)
{
    (void)fdt; (void)el; (void)load;

    band(0, 4800u, "BAND0 S4800 =1200x4", C_WHITE);
    band(1, 4864u, "BAND1 S4864 =1216x4", C_WHITE);
    band(2, 4928u, "BAND2 S4928 =1232x4", C_WHITE);
    band(3, 5120u, "BAND3 S5120 =1280x4", C_WHITE);

    delay_s(120);   /* 延长到 120s, 给电脑端摄像头抓帧+分析留足时间 */
    reboot();
}
