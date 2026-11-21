/*
 * byron "关 UBWC 诊断" 镜像 (fastboot boot, 纯 RAM, 不写分区).
 *
 * 目的: ubwcoff 镜像用文字报告 FOUND/NO PIPE, 但文字被斜纹干扰读不清.
 *       本镜像改用【整屏纯色块 + 闪烁次数】传递诊断结果 — 纯色显示已被
 *       fbflip 证明在 byron 上可靠 (红蓝整体翻转可见).
 *
 * 你只需回答 3 个问题:
 *   Q1 第 1 个色块: 绿 还是 红?
 *   Q2 第 2 个色块: 黄 / 青 / 黑?
 *   Q3 后面的大纯色块 (红绿蓝白): 内部【有】斜纹还是【没有】斜纹?
 *
 * 编码:
 *   阶段1 (8s) 全屏: 绿=找到pipe(FOUND) / 红=没找到(NO PIPE)
 *   阶段2 (8s) 全屏: 黄=关之前UBWC原本开着(bit0=1) / 青=原本就关着(bit0=0) / 黑=没找到pipe
 *   阶段3 (8s) 全屏: 品红=FRAME_FORMAT非0(压缩) / 白=FRAME_FORMAT=0(linear) / 黑=没找到pipe
 *   阶段4 关UBWC (若找到)
 *   阶段5 大纯色块循环 (每块5s x 2轮): 红/绿/蓝/白 — 看块内有无斜纹
 *   ~50s 后 PSCI SYSTEM_RESET 回安卓
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

/* fbflip 已验证的 ARGB word 纯色 */
#define C_BLACK 0xff000000u
#define C_RED   0xffff0000u
#define C_GREEN 0xff00ff00u
#define C_BLUE  0xff0000ffu
#define C_YELL  0xffffff00u
#define C_CYAN  0xff00ffffu
#define C_MAG   0xffff00ffu
#define C_WHITE 0xffffffffu

void ubwcdiag_main(uint64_t fdt, uint64_t el, uint64_t load)
{
    (void)fdt; (void)el; (void)load;

    int found = -1;
    uint32_t op_before = 0, fmt_before = 0;

    for (int i = 0; i < NPIPE; i++) {
        uint64_t base = MDP + pipe_off[i];
        uint32_t src0 = rd32(base + SSPP_SRC0_ADDR);
        if (src0 == (uint32_t)FB && found < 0) {
            found = i;
            op_before  = rd32(base + SSPP_SRC_OP_MODE);
            fmt_before = rd32(base + SSPP_SRC_FORMAT);
        }
    }
    dmb();

    /* ---- 阶段1: FOUND / NO PIPE (纯色, 8s) ---- */
    if (found >= 0) {
        full(C_GREEN);
        put_str(2, 2, "STAGE1 GREEN = FOUND PIPE", C_BLACK, C_GREEN);
    } else {
        full(C_RED);
        put_str(2, 2, "STAGE1 RED = NO PIPE", C_WHITE, C_RED);
    }
    delay_s(8);

    /* ---- 阶段2: op_before 的 BWC_EN bit (8s) ---- */
    if (found >= 0) {
        if (op_before & BWC_EN) {
            full(C_YELL);
            put_str(2, 2, "STAGE2 YELLOW = UBWC WAS ON", C_BLACK, C_YELL);
        } else {
            full(C_CYAN);
            put_str(2, 2, "STAGE2 CYAN = UBWC WAS OFF", C_BLACK, C_CYAN);
        }
    } else {
        full(C_BLACK);
    }
    delay_s(8);

    /* ---- 阶段3: fmt_before 的 FRAME_FORMAT (8s) ---- */
    if (found >= 0) {
        if (fmt_before & FRAME_FMT_MSK) {
            full(C_MAG);
            put_str(2, 2, "STAGE3 MAGENTA = FMT NONZERO", C_WHITE, C_MAG);
        } else {
            full(C_WHITE);
            put_str(2, 2, "STAGE3 WHITE = FMT LINEAR", C_BLACK, C_WHITE);
        }
    } else {
        full(C_BLACK);
    }
    delay_s(8);

    /* ---- 阶段4: 关 UBWC (若找到) ---- */
    if (found >= 0) {
        uint64_t base = MDP + pipe_off[found];
        uint32_t op = rd32(base + SSPP_SRC_OP_MODE);
        uint32_t fmt = rd32(base + SSPP_SRC_FORMAT);
        op &= ~BWC_EN;
        fmt &= ~FRAME_FMT_MSK;
        wr32(base + SSPP_SRC_OP_MODE, op);
        wr32(base + SSPP_SRC_FORMAT, fmt);
        wr32(base + SSPP_UBWC_ERR, 1u << 31);
        dmb();
    }

    /* ---- 阶段5: 有细节图案 (色带+字+棋盘), 判断关UBWC后复杂画面是否还花 ---- */
    for (int round = 0; round < 3; round++) {
        full(C_BLACK);
        put_str(2, 2, "AFTER UBWC-OFF TEST", C_WHITE, C_BLACK);
        /* 三条色带 */
        for (uint32_t y = 100; y < 300; y++) {
            volatile uint32_t *line = fb + (uint64_t)y * (FB_STRIDE / 4);
            for (uint32_t x = 0; x < FB_W; x++) line[x] = C_RED;
        }
        for (uint32_t y = 300; y < 500; y++) {
            volatile uint32_t *line = fb + (uint64_t)y * (FB_STRIDE / 4);
            for (uint32_t x = 0; x < FB_W; x++) line[x] = C_GREEN;
        }
        for (uint32_t y = 500; y < 700; y++) {
            volatile uint32_t *line = fb + (uint64_t)y * (FB_STRIDE / 4);
            for (uint32_t x = 0; x < FB_W; x++) line[x] = C_BLUE;
        }
        /* 棋盘格 (对格式最敏感) */
        for (uint32_t y = 800; y < 1600; y++) {
            volatile uint32_t *line = fb + (uint64_t)y * (FB_STRIDE / 4);
            for (uint32_t x = 0; x < FB_W; x++)
                line[x] = (((x / 32) + (y / 32)) & 1) ? C_WHITE : C_BLACK;
        }
        delay_s(6);
    }

    reboot();
}
