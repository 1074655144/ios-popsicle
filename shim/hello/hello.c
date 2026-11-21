/*
 * pandora-hello: byron (Xiaomi 17 Max, SM8850-AC) 引导阶段只读探测.
 * 大字精简版: 只探测并大字显示 6 项引导期参数, 300 秒后 PSCI SYSTEM_RESET
 * 回到安卓. `fastboot boot` 启动, 不写任何存储; 长按电源键可随时强制重启.
 *
 * 显示 6 项: 16K 页支持 / 装载地址 / FB 基址 / 宽高 / stride / fmt.
 * MMU 关闭, 所有访问均为 Device memory, 以 -mstrict-align 编译.
 * Image 链接于 0 且可加载到任意位置: 数据中无绝对指针.
 */
#include <stdint.h>
#include "font.h"

uint32_t safe_rd32(uint64_t pa, uint32_t *faulted);
void fatal(void) __attribute__((noreturn));
extern uint64_t fault_esr;

#define SYSREG(r) ({ uint64_t v_; __asm__ volatile("mrs %0, " #r : "=r"(v_)); v_; })

/* 与 byron 真机 FDT / 固件一致: qcom,mdss_mdp@9800000, splash_region. */
#define MDP          0x9800000ull
#define SPLASH       0xfc800000ull
#define SPLASH_SIZE  0x2b00000ull
static const uint32_t sspp_off[10] = {
	0x2c000, 0x35000, 0x3e000, 0x47000,                     /* VIG 0-3 */
	0x98000, 0xa1000, 0xaa000, 0xb3000, 0xbc000, 0xc5000,   /* DMA 0-5 */
};
struct pipe { uint32_t size, addr, stride, fmt, faulted; };
static struct pipe pipes[10];

static volatile uint32_t *fb;
static uint32_t fb_w, fb_h, fb_stride, fb_fmt;   /* stride 单位: 字节 */
static int row;

/* 超大字体: 每字符 64x128 像素, 一屏 1200 宽可容纳约 18 字符. */
#define SCALE 8
#define CW    (8 * SCALE)
#define CH    (16 * SCALE)
#define MARGIN 24

#define BG     0xff102040u
#define WHITE  0xffffffffu
#define YELLOW 0xffffff00u
#define GREEN  0xff40ff40u
#define RED    0xffff4040u

static void fill(uint32_t x0, uint32_t y0, uint32_t w, uint32_t h, uint32_t c)
{
	for (uint32_t y = y0; y < y0 + h && y < fb_h; y++) {
		volatile uint32_t *line = fb + y * (fb_stride / 4);
		for (uint32_t x = x0; x < x0 + w && x < fb_w; x++)
			line[x] = c;
	}
}

static void put_char(int col, char ch, uint32_t fg)
{
	if (ch < 0x20 || ch > 0x7e)
		ch = '?';
	const unsigned char *g = font8x16[ch - 0x20];
	uint32_t x0 = MARGIN + col * CW, y0 = MARGIN + row * CH;
	if (x0 + CW > fb_w || y0 + CH > fb_h)
		return;
	for (int gy = 0; gy < 16; gy++)
		for (int gx = 0; gx < 8; gx++)
			fill(x0 + gx * SCALE, y0 + gy * SCALE, SCALE, SCALE,
			    (g[gy] & (0x80 >> gx)) ? fg : BG);
}

static int put_str(int col, const char *s, uint32_t fg)
{
	while (*s)
		put_char(col++, *s++, fg);
	return col;
}

static char *hex(char *p, uint64_t v, int digits)
{
	for (int i = digits - 1; i >= 0; i--) {
		unsigned d = (v >> (4 * i)) & 0xf;
		*p++ = d < 10 ? '0' + d : 'A' + d - 10;
	}
	*p = 0;
	return p;
}

static char *dec(char *p, uint64_t v)
{
	char t[21];
	int n = 0;
	do t[n++] = '0' + v % 10; while (v /= 10);
	while (n)
		*p++ = t[--n];
	*p = 0;
	return p;
}

static char *cat(char *p, const char *s)
{
	while (*s)
		*p++ = *s++;
	*p = 0;
	return p;
}

/* 整行一个字符串, 从最左列开始, 写完换下一行. */
static void row_text(const char *s, uint32_t fg)
{
	put_str(0, s, fg);
	row++;
}

static void find_framebuffer(void)
{
	int pick = -1;
	for (int i = 0; i < 10; i++) {
		uint64_t b = MDP + sspp_off[i];
		uint32_t f = 0, any = 0;
		pipes[i].size = safe_rd32(b + 0x00, &f); any |= f;
		pipes[i].addr = safe_rd32(b + 0x14, &f); any |= f;
		pipes[i].stride = safe_rd32(b + 0x24, &f); any |= f;
		pipes[i].fmt = safe_rd32(b + 0x30, &f); any |= f;
		pipes[i].faulted = any;
		if (!any && pick < 0 && pipes[i].addr >= SPLASH && pipes[i].addr < SPLASH + SPLASH_SIZE)
			pick = i;
	}
	/* 无可用管道时的兜底: popsicle 占位值, 仅用于显示, 不影响探测. */
	uint64_t base = SPLASH;
	fb_w = 1220; fb_h = 2656; fb_stride = 1220 * 4; fb_fmt = 0;
	if (pick >= 0) {
		uint32_t w = pipes[pick].size & 0xffff, h = pipes[pick].size >> 16;
		uint32_t s = pipes[pick].stride & 0xffff;
		if (w >= 64 && w <= 4096 && h >= 64 && h <= 4096 && s >= w * 4 &&
		    pipes[pick].addr + (uint64_t)s * h <= SPLASH + SPLASH_SIZE) {
			base = pipes[pick].addr;
			fb_w = w; fb_h = h; fb_stride = s; fb_fmt = pipes[pick].fmt;
		}
	}
	/* 写屏永不越出 splash 保留区. */
	if (base + (uint64_t)fb_stride * fb_h > SPLASH + SPLASH_SIZE)
		fb_h = (uint32_t)((SPLASH + SPLASH_SIZE - base) / fb_stride);
	fb = (volatile uint32_t *)(uintptr_t)base;
}

static void psci_reset(void) __attribute__((noreturn));
static void psci_reset(void)
{
	register uint64_t x0 __asm__("x0") = 0x84000009;
	__asm__ volatile("smc #0" : "+r"(x0) :: "x1", "x2", "x3", "memory");
	fatal();
}

/* 把探测结果写成 ASCII, 放进 ramoops console 区尾部 (0xff400000..0xff500000).
 * reset 后安卓内核的 pstore 把它导出到 /sys/fs/pstore/console-ramoops-0, 直接读.
 * 用醒目标记行包裹, 便于从内核日志中 grep. */
#define RAMOOPS_CONSOLE_BASE 0xff400000ull
#define RAMOOPS_CONSOLE_SIZE 0x100000ull
static void putc_dump(volatile unsigned char **pp, char c) { *(*pp)++ = (unsigned char)c; }
static void puts_dump(volatile unsigned char **pp, const char *s)
{ while (*s) putc_dump(pp, *s++); }
static void hex8_dump(volatile unsigned char **pp, uint64_t v)
{
	static const char hx[] = "0123456789ABCDEF";
	putc_dump(pp, '0'); putc_dump(pp, 'x');
	for (int i = 7; i >= 0; i--) putc_dump(pp, hx[(v >> (i * 4)) & 0xf]);
}
static void dec_dump(volatile unsigned char **pp, uint64_t v)
{
	char t[24]; int n = 0;
	do t[n++] = '0' + v % 10; while (v /= 10);
	while (n) putc_dump(pp, t[--n]);
}
static void write_dump(uint64_t el, uint64_t load, uint64_t mmfr0)
{
	/* 写在 console 区末尾 2KB, 避开内核新日志的循环写入方向.
	 * 用 movz/movk 构造地址, 避免 64 位常量进入 rodata 产生 ABS64 重定位
	 * (Image 会被加载到任意地址, 绝对地址会失效). */
	uint64_t dump_pa;
	__asm__ volatile("movz %0, #0xf800\n\tmovk %0, #0xff4f, lsl #16"
	                 : "=r"(dump_pa));   /* 0xff4ff800 */
	volatile unsigned char *p = (volatile unsigned char *)(uintptr_t)dump_pa;
	int has16k = ((mmfr0 >> 20) & 0xf) != 0;
	puts_dump(&p, "\n===BYRON_PROBE_BEGIN===\n");
	puts_dump(&p, "MAGIC=BYRDPROBE1\n");
	puts_dump(&p, "EL="); dec_dump(&p, el); putc_dump(&p, '\n');
	puts_dump(&p, "LOAD="); hex8_dump(&p, load); putc_dump(&p, '\n');
	puts_dump(&p, "MMFR0="); hex8_dump(&p, mmfr0); putc_dump(&p, '\n');
	puts_dump(&p, "PAGES16K="); puts_dump(&p, has16k ? "YES" : "NO"); putc_dump(&p, '\n');
	puts_dump(&p, "FB="); hex8_dump(&p, (uint64_t)(uintptr_t)fb); putc_dump(&p, '\n');
	puts_dump(&p, "W="); dec_dump(&p, fb_w);
	puts_dump(&p, " H="); dec_dump(&p, fb_h); putc_dump(&p, '\n');
	puts_dump(&p, "STRIDE="); dec_dump(&p, fb_stride); putc_dump(&p, '\n');
	puts_dump(&p, "FMT="); hex8_dump(&p, fb_fmt); putc_dump(&p, '\n');
	for (int i = 0; i < 10; i++) {
		puts_dump(&p, "P"); dec_dump(&p, i);
		puts_dump(&p, "="); hex8_dump(&p, pipes[i].addr);
		puts_dump(&p, ","); hex8_dump(&p, pipes[i].stride);
		puts_dump(&p, ","); hex8_dump(&p, pipes[i].size);
		puts_dump(&p, ","); hex8_dump(&p, pipes[i].fmt);
		putc_dump(&p, '\n');
	}
	puts_dump(&p, "===BYRON_PROBE_END===\n");
	__asm__ volatile("dsb sy" ::: "memory");
}

void hello_main(uint64_t fdt, uint64_t el, uint64_t load)
{
	(void)fdt;
	find_framebuffer();
	uint64_t mmfr0 = SYSREG(id_aa64mmfr0_el1);
	write_dump(el, load, mmfr0);
	fill(0, 0, fb_w, fb_h, BG);
	row = 0;
	char b[64], *p;

	row_text("BYRON PROBE V2", YELLOW);

	/* TGran16 != 0 即支持 16K 页 (ID_AA64MMFR0_EL1.TGran16, bits 23:20). */
	int has16k = ((mmfr0 >> 20) & 0xf) != 0;
	row_text(has16k ? "16K PAGE YES" : "16K PAGE NO", has16k ? GREEN : RED);

	p = hex(cat(b, "LOAD 0x"), load, 8);
	row_text(b, WHITE);

	p = hex(cat(b, "FB 0x"), (uint64_t)(uintptr_t)fb, 8);
	row_text(b, WHITE);

	p = dec(cat(b, "W "), fb_w);
	p = cat(p, " H ");
	p = dec(p, fb_h);
	row_text(b, WHITE);

	p = dec(cat(b, "STRIDE "), fb_stride);
	row_text(b, WHITE);

	p = hex(cat(b, "FMT 0x"), fb_fmt, 8);
	row_text(b, WHITE);

	/* 结果已写入保留内存; 短暂停留后重启, 回安卓从 /dev/mem 读回. */
	uint64_t frq = SYSREG(cntfrq_el0);
	uint64_t t0 = SYSREG(cntvct_el0);
	int crow = row;
	for (uint64_t s = 12; s > 0; s--) {
		row = crow;
		fill(MARGIN, MARGIN + row * CH, fb_w - 2 * MARGIN, CH, BG);
		p = dec(cat(b, "REBOOT IN "), s);
		cat(p, " S");
		row_text(b, GREEN);
		while (SYSREG(cntvct_el0) - t0 < (12 - s + 1) * frq)
			;
	}
	psci_reset();
}
