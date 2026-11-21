/*
 * byron "关 UBWC 验证" 镜像 (fastboot boot, 纯 RAM, 不写分区).
 *
 * 背景: fbflip 已证明 CPU->显存->DSI->面板链路通, 花屏纯粹是 SSPP 按 UBWC
 *       解读我们写的线性像素. 本镜像在写屏前, 先编程 SDE/SSPP 寄存器把那一路
 *       正在扫描 splash buffer (0xfc800000) 的 pipe 的 UBWC 关掉, 再写线性图案.
 *
 * 关 UBWC 的寄存器依据 (mainline dpu_hw_sspp.c / dpu_hwio.h):
 *   SSPP_SRC0_ADDR   = 0x14  (源地址低 32 位) -> 用来定位激活 pipe
 *   SSPP_SRC_FORMAT  = 0x30  (bits[31:30] FRAME_FORMAT; linear 时为 0)
 *   SSPP_SRC_OP_MODE = 0x38  (bit0 = MDSS_MDP_OP_BWC_EN, 1=UBWC开, 0=线性)
 *   SSPP_UBWC_ERROR_STATUS = 0x138 (写 BIT31 清错误)
 *
 * pipe 基址 (byron live FDT qcom,sde-sspp-off, 相对 MDP 0x9800000):
 *   VIG  0x2c000 0x35000 0x3e000 0x47000
 *   DMA  0x98000 0xa1000 0xaa000 0xb3000 0xbc000 0xc5000
 *
 * 流程:
 *   1. 逐个 pipe 读 SRC0_ADDR, 找 == 0xfc800000 的 (打印全部到屏幕, 便于诊断).
 *   2. 若找到: 清该 pipe 的 OP_MODE bit0 + SRC_FORMAT bits[31:30] + 清 UBWC 错误.
 *   3. 写线性测试图案 (色条 + 大字), 若不再花屏 -> 关 UBWC 路径可行.
 *   4. 若没找到 pipe: 仍写图案 (等同 fbflip), 屏幕会显示 "NO PIPE" 诊断字样.
 *   5. ~40 秒后 PSCI SYSTEM_RESET 回安卓; 长按电源可提前重启.
 */
#include <stdint.h>
#include "font.h"

#define MDP         0x09800000ull
#define MDP_SIZE    0x1c8800ull
#define FB          0xfc800000ull
#define FB_W        1200u
#define FB_H        2608u
#define FB_STRIDE   4800u          /* = 1200 * 4, stridescan 实证 */

/* SSPP register offsets (relative to pipe base) */
#define SSPP_SRC0_ADDR   0x14u
#define SSPP_SRC_FORMAT  0x30u
#define SSPP_SRC_OP_MODE 0x38u
#define SSPP_UBWC_ERR    0x138u

#define BWC_EN       (1u << 0)
#define FRAME_FMT_MSK (3u << 30)   /* 0 = linear */

static const uint32_t pipe_off[] = {
    0x2c000u, 0x35000u, 0x3e000u, 0x47000u,          /* VIG0-3 */
    0x98000u, 0xa1000u, 0xaa000u, 0xb3000u, 0xbc000u, 0xc5000u, /* DMA0-5 */
};
#define NPIPE ((int)(sizeof(pipe_off)/sizeof(pipe_off[0])))

static volatile uint32_t *const fb = (volatile uint32_t *)(uintptr_t)FB;

/* ---------- 物理读写 ---------- */
static uint32_t rd32(uint64_t p)
{
    return *(volatile uint32_t *)(uintptr_t)p;
}
static void wr32(uint64_t p, uint32_t v)
{
    *(volatile uint32_t *)(uintptr_t)p = v;
    __asm__ volatile("dsb sy" ::: "memory");
}
static void dmb(void) { __asm__ volatile("dsb sy" ::: "memory"); }

/* ---------- 显示原语 ---------- */
static void rect(uint32_t x0, uint32_t y0, uint32_t w, uint32_t h, uint32_t c)
{
    for (uint32_t y = y0; y < y0 + h && y < FB_H; y++) {
        volatile uint32_t *line = fb + (uint64_t)y * (FB_STRIDE / 4);
        for (uint32_t x = x0; x < x0 + w && x < FB_W; x++)
            line[x] = c;
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

/* ---------- 计时 / 重启 ---------- */
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

#define C_WHITE 0xffffffffu
#define C_BLACK 0xff000000u
#define C_GREEN 0xff00ff00u
#define C_RED   0xffff0000u
#define C_YELL  0xffffff00u

/* 扫描: 找到 SRC0_ADDR == 0xfc800000 的 pipe, 返回其 index, -1 表示没找到.
 * 同时把每个 pipe 的 (index, SRC0_ADDR 低32) 画到屏幕上便于诊断. */
static int scan_and_report(uint32_t *found_op_before, uint32_t *found_fmt_before)
{
    int found = -1;
    rect(0, 0, FB_W, 12, C_BLACK);
    put_str(0, 0, "SSPP SCAN: idx : SRC0_ADDR", C_YELL, C_BLACK);

    for (int i = 0; i < NPIPE; i++) {
        uint64_t base = MDP + pipe_off[i];
        uint32_t src0 = rd32(base + SSPP_SRC0_ADDR);
        char b[80], *p = b;
        p = cat(p, "P"); p = dec(p, (uint32_t)i); p = cat(p, " : 0x"); p = hex(p, src0, 8);
        *p = 0;
        put_str(0, 1 + i, b, (src0 == (uint32_t)FB) ? C_GREEN : C_WHITE, C_BLACK);

        if (src0 == (uint32_t)FB && found < 0) {
            found = i;
            *found_op_before  = rd32(base + SSPP_SRC_OP_MODE);
            *found_fmt_before = rd32(base + SSPP_SRC_FORMAT);
        }
    }
    return found;
}

void ubwcoff_main(uint64_t fdt, uint64_t el, uint64_t load)
{
    (void)fdt; (void)el; (void)load;

    uint32_t op_before = 0, fmt_before = 0;
    int found = scan_and_report(&op_before, &fmt_before);

    /* 报告找到的 pipe 及其寄存器原值 */
    {
        char b[96], *p;
        rect(0, 0, FB_W, 12, C_BLACK);
        if (found >= 0) {
            p = b; p = cat(p, "FOUND P"); p = dec(p, (uint32_t)found);
            p = cat(p, " OP=0x"); p = hex(p, op_before, 8);
            p = cat(p, " FMT=0x"); p = hex(p, fmt_before, 8); *p = 0;
            put_str(0, 0, b, C_GREEN, C_BLACK);
        } else {
            put_str(0, 0, "NO PIPE with SRC0=0xfc800000", C_RED, C_BLACK);
        }
    }
    dmb();
    delay_s(5);   /* 给用户时间读诊断 */

    /* 关 UBWC: 清 OP_MODE bit0, 清 SRC_FORMAT bits[31:30], 清 UBWC 错误 */
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

    /* 写线性测试图案: 大字 + 三条色带 */
    rect(0, 0, FB_W, FB_H, C_BLACK);
    put_str(2, 2, found >= 0 ? "UBWC OFF - LINEAR TEST" : "NO PIPE - PLAIN TEST",
            found >= 0 ? C_GREEN : C_RED, C_BLACK);
    {
        char b[96], *p = b;
        p = cat(p, "PIPE=");
        if (found >= 0) { p = dec(p, (uint32_t)found); } else { p = cat(p, "NONE"); }
        p = cat(p, " OP 0x"); p = hex(p, op_before, 8);
        p = cat(p, " -> 0x"); p = hex(p, found >= 0 ? (rd32(MDP + pipe_off[found] + SSPP_SRC_OP_MODE)) : 0, 8);
        *p = 0;
        put_str(2, 4, b, C_YELL, C_BLACK);
    }
    /* 三条色带: 线性模式下应显示纯正红/绿/蓝且无斜纹 */
    rect(0, 100, FB_W, 200, 0xffff0000u);   /* 红 */
    rect(0, 300, FB_W, 200, 0xff00ff00u);   /* 绿 */
    rect(0, 500, FB_W, 200, 0xff0000ffu);   /* 蓝 */
    put_str(2, 45, "RED / GREEN / BLUE BARS", C_WHITE, C_BLACK);

    /* 循环翻转色带颜色, 便于确认持续刷新 */
    for (int round = 0; round < 4; round++) {
        delay_s(4);
        rect(0, 100, FB_W, 200, 0xff0000ffu);
        rect(0, 300, FB_W, 200, 0xffff0000u);
        rect(0, 500, FB_W, 200, 0xff00ff00u);
        delay_s(4);
        rect(0, 100, FB_W, 200, 0xff00ff00u);
        rect(0, 300, FB_W, 200, 0xff0000ffu);
        rect(0, 500, FB_W, 200, 0xffff0000u);
    }

    reboot();
}
