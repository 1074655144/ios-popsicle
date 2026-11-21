/*
 * byron "全 pipe 关 UBWC" 镜像 (fastboot boot, 纯 RAM, 不写分区).
 *
 * 背景: ubwcdiag 实测 NO PIPE — SSPP 的 SRC0_ADDR 不等于物理 0xfc800000
 *       (可能是 IOVA 或 pipe 布局不同), 所以 ubwcoff 的"定位 pipe 后关 UBWC"
 *       从来没执行过. 既然 fastboot 环境下只有 splash 一路 SSPP 在活动,
 *       本镜像直接把【全部 10 路】SSPP 的 UBWC 关掉, 绕开定位难题. 重启即恢复.
 *
 * 同时把每个 pipe 的 SRC0_ADDR 用纯色+文字报告, 便于下次精确判定:
 *   阶段1 (6s): 全屏绿=10路UBWC已全关 / 红=关的动作没跑(异常)
 *   阶段2 (6s): 逐 pipe 报 SRC0_ADDR 是否==0xfc800000 (绿=命中/白=未命中)
 *   阶段3 (循环): 色带+大字+棋盘格 — 判断关掉全部UBWC后复杂画面是否还花
 *   ~40s 后 PSCI SYSTEM_RESET 回安卓
 */
#include <stdint.h>
#include "font.h"

#define MDP         0x09800000ull
#define FB          0xfc800000ull
#define FB_W        1200u
#define FB_H        2608u
#define FB_STRIDE   4800u  /* = 1200*4, stridescan 实证 */

#define SSPP_SRC0_ADDR   0x14u
#define SSPP_SRC_FORMAT  0x30u
#define SSPP_SRC_OP_MODE 0x38u
#define SSPP_UBWC_ERR    0x138u
#define BWC_EN       (1u << 0)
#define FRAME_FMT_MSK (3u << 30)

static const uint32_t pipe_off[] = {
    0x2c000u, 0x35000u, 0x3e000u, 0x47000u,
    0x98000u, 0xa1000u, 0xaa000u, 0xb3000u, 0xbc000u, 0xc5000u,
};
#define NPIPE ((int)(sizeof(pipe_off)/sizeof(pipe_off[0])))

static volatile uint32_t *const fb = (volatile uint32_t *)(uintptr_t)FB;

static uint32_t rd32(uint64_t p) { return *(volatile uint32_t *)(uintptr_t)p; }
static void wr32(uint64_t p, uint32_t v)
{
    *(volatile uint32_t *)(uintptr_t)p = v;
    __asm__ volatile("dsb sy" ::: "memory");
}
static void dmb(void) { __asm__ volatile("dsb sy" ::: "memory"); }

static void full(uint32_t c)
{
    for (uint32_t y = 0; y < FB_H; y++) {
        volatile uint32_t *line = fb + (uint64_t)y * (FB_STRIDE / 4);
        for (uint32_t x = 0; x < FB_W; x++) line[x] = c;
    }
}
static void rect(uint32_t x0, uint32_t y0, uint32_t w, uint32_t h, uint32_t c)
{
    for (uint32_t y = y0; y < y0 + h && y < FB_H; y++) {
        volatile uint32_t *line = fb + (uint64_t)y * (FB_STRIDE / 4);
        for (uint32_t x = x0; x < x0 + w && x < FB_W; x++) line[x] = c;
    }
}
static void put_char(int col, int row, char ch, uint32_t fg, uint32_t bg)
{
    const unsigned char *g = &font8x16[(uint8_t)ch - 0x20][0];
    for (int y = 0; y < 16; y++) {
        volatile uint32_t *line = fb + (uint64_t)(row * 16 + y) * (FB_STRIDE / 4) + col * 8;
        uint8_t bits = g[y];
        for (int x = 0; x < 8; x++)
            line[x] = (bits & (0x80u >> x)) ? fg : bg;
    }
}
static void put_str(int col, int row, const char *s, uint32_t fg, uint32_t bg)
{
    while (*s) { put_char(col++, row, *s++, fg, bg); }
}
static char *hex(char *p, uint64_t v, int digits)
{
    static const char hx[] = "0123456789ABCDEF";
    for (int i = digits - 1; i >= 0; i--) *p++ = hx[(v >> (i * 4)) & 0xf];
    return p;
}
static char *dec(char *p, uint64_t v)
{
    char t[21]; int n = 0;
    if (!v) *p++ = '0';
    while (v) { t[n++] = (char)('0' + v % 10); v /= 10; }
    while (n) *p++ = t[--n];
    return p;
}
static char *cat(char *p, const char *s) { while (*s) *p++ = *s++; return p; }

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
#define C_RED   0xffff0000u
#define C_GREEN 0xff00ff00u
#define C_BLUE  0xff0000ffu
#define C_YELL  0xffffff00u
#define C_CYAN  0xff00ffffu
#define C_MAG   0xffff00ffu
#define C_WHITE 0xffffffffu

void ubwcall_main(uint64_t fdt, uint64_t el, uint64_t load)
{
    (void)fdt; (void)el; (void)load;

    /* ---- 关全部 10 路 SSPP 的 UBWC ---- */
    for (int i = 0; i < NPIPE; i++) {
        uint64_t base = MDP + pipe_off[i];
        uint32_t op  = rd32(base + SSPP_SRC_OP_MODE);
        uint32_t fmt = rd32(base + SSPP_SRC_FORMAT);
        op  &= ~BWC_EN;
        fmt &= ~FRAME_FMT_MSK;
        wr32(base + SSPP_SRC_OP_MODE, op);
        wr32(base + SSPP_SRC_FORMAT, fmt);
        wr32(base + SSPP_UBWC_ERR, 1u << 31);
    }
    dmb();

    /* ---- 阶段1: 全屏绿, 表示"关的动作已跑完" ---- */
    full(C_GREEN);
    put_str(2, 2, "ALL 10 PIPES UBWC OFF", C_BLACK, C_GREEN);
    put_str(2, 4, "PIPES: VIG0-3 DMA0-5", C_BLACK, C_GREEN);
    delay_s(6);

    /* ---- 阶段2: 逐 pipe 报 SRC0_ADDR (命中绿, 未命中白) ---- */
    full(C_BLACK);
    put_str(1, 0, "PIPE : SRC0_ADDR (green=0xfc800000)", C_YELL, C_BLACK);
    for (int i = 0; i < NPIPE; i++) {
        uint32_t src0 = rd32(MDP + pipe_off[i] + SSPP_SRC0_ADDR);
        char b[80], *p = b;
        p = cat(p, "P"); p = dec(p, (uint32_t)i); p = cat(p, " : 0x"); p = hex(p, src0, 8); *p = 0;
        put_str(1, 1 + i, b, (src0 == (uint32_t)FB) ? C_GREEN : C_WHITE, C_BLACK);
    }
    delay_s(8);

    /* ---- 阶段3: 复杂图案循环, 判断关掉全部UBWC后是否还花 ---- */
    for (int round = 0; round < 3; round++) {
        full(C_BLACK);
        put_str(2, 2, "AFTER ALL-UBWC-OFF TEST", C_WHITE, C_BLACK);
        rect(0, 100, FB_W, 200, C_RED);
        rect(0, 300, FB_W, 200, C_GREEN);
        rect(0, 500, FB_W, 200, C_BLUE);
        for (uint32_t y = 800; y < 1600; y++) {
            volatile uint32_t *line = fb + (uint64_t)y * (FB_STRIDE / 4);
            for (uint32_t x = 0; x < FB_W; x++)
                line[x] = (((x / 32) + (y / 32)) & 1) ? C_WHITE : C_BLACK;
        }
        delay_s(6);
    }

    reboot();
}
