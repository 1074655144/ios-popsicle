/*
 * byron (Xiaomi 17 Max, SM8850-AC) 引导阶段探测 —— USB CDC ACM 回传版.
 *
 * 与 shim/hello 一样由 `fastboot boot` 以 Linux arm64 Image 载入, MMU 关闭,
 * x0=FDT, 不写任何存储. 区别是回传通道: 接管 ABL 交接的 DWC3 (a600000,
 * device mode, SMMU stream 0x40 bypass bank 已就绪), 用 CDC ACM 把探测到的
 * 板级寄存器值直接发到电脑串口, 而不是依赖已证伪的屏幕/pstore/devmem.
 *
 * 所有探测逻辑沿用 hello.c: SSPP 源寄存器 -> framebuffer 的 w/h/stride/fmt,
 * 装载地址 load, ID_AA64MMFR0_EL1.TGran16. 加上本程序自己的 DWC3 初始化
 * 自检码, 便于串口端判断卡在哪一步.
 *
 * 内存: 全部静态, 无 malloc, 无 libc. Image 链接于 0, 可加载到任意 4KiB
 * 对齐的物理地址; 代码中不含绝对地址重定位 (用 adr 自定位). DMA 为物理
 * 地址直通 (bootloader 的 SMMU bypass bank), 故 dma_cpu 的物理地址须与
 * CPU 访问地址相同 —— MMU off 下二者天然相等.
 */
#include <stdint.h>
#include <stddef.h>
#include "Dwc3.h"
#include "Dwc3Regs.h"

/* ---- 探测寄存器 (来自 hello.c, byron FDT 实证) ---- */
#define MDP          0x09800000ull   /* qcom,mdss_mdp@9800000 */
#define DWC3_BASE    0x0a600000ull
#define QSCRATCH     (DWC3_BASE + 0xf8810ull) /* dwc3-msm QSCRATCH HS_PHY_CTRL */
#define SW_VBUS_MASK ((1u << 20) | (1u << 28)) /* sw VBUS valid + session valid */
#define SPLASH       0xfc800000ull
#define SPLASH_SIZE  0x2b00000ull

/* 交接状态自检: 每次读一次, 随探测结果一起回传, 便于判断 USB 前提是否成立. */
static uint32_t diag_gctl, diag_dctl, diag_dsts, diag_phycfg, diag_vbus, diag_hwparams;
static const uint32_t sspp_off[10] = {
	0x2c000, 0x35000, 0x3e000, 0x47000,
	0x98000, 0xa1000, 0xaa000, 0xb3000, 0xbc000, 0xc5000,
};
struct pipe { uint32_t addr, size, stride, fmt; uint32_t fault; };
static struct pipe pipes[10];

/* ---- 字符串工具 (无 libc) ---- */
static char *cat(char *p, const char *s) { while (*s) *p++ = *s++; *p = 0; return p; }
static char *hex(char *p, uint64_t v, int n)
{
	static const char hx[] = "0123456789ABCDEF";
	for (int i = n - 1; i >= 0; i--) *p++ = hx[(v >> (i * 4)) & 0xf];
	*p = 0; return p;
}
static char *dec(char *p, uint64_t v)
{
	char t[24]; int n = 0;
	do t[n++] = (char)('0' + v % 10); while (v /= 10);
	while (n) *p++ = t[--n];
	*p = 0; return p;
}

/* ---- 底层 MMIO / 计数 / 屏障 ---- */
static inline uint32_t rd32(uint64_t pa) { return *(volatile uint32_t *)(uintptr_t)pa; }
static inline void wr32(uint64_t pa, uint32_t v) { *(volatile uint32_t *)(uintptr_t)pa = v; }
#define SYSREG(r) ({ uint64_t v_; __asm__ volatile("mrs %0, " #r : "=r"(v_)); v_; })
static uint64_t tick(void) { uint64_t v; __asm__ volatile("isb\nmrs %0, cntvct_el0" : "=r"(v)); return v; }

/* DWC3 platform 回调: MMU off, 物理地址即虚拟地址; 缓存一致性由 -mstrict-align
 * + Device memory 访问保证 (探测环境 MMU 关闭, 所有访问为 Device, 无 D-cache
 * 别名). Strict-align 下 DwC3 结构内的 8/16 位字段也安全. */
static uint32_t plat_read32(void *cookie, uint32_t off)
{
	(void)cookie;
	return rd32(0x0a600000ull + off);
}
static void plat_write32(void *cookie, uint32_t off, uint32_t v)
{
	(void)cookie;
	wr32(0x0a600000ull + off, v);
}
static void plat_delay_us(void *cookie, uint32_t us)
{
	(void)cookie;
	uint64_t frq = SYSREG(cntfrq_el0);
	if (!frq || !us) return;
	uint64_t start = tick();
	uint64_t need = frq * (uint64_t)us / 1000000ull;
	if (!need) need = 1;
	while (tick() - start < need)
		__asm__ volatile("yield" ::: "memory");
}
static void plat_dma_sync(void *cookie, void *cpu, size_t bytes,
                          enum dwc3_sync_direction dir)
{
	(void)cookie; (void)cpu; (void)bytes; (void)dir;
	/* MMU off: Device memory, no cache maintenance needed. */
	__asm__ volatile("dsb sy" ::: "memory");
}
static void plat_barrier(void *cookie) { (void)cookie; __asm__ volatile("dsb sy" ::: "memory"); }
static void plat_trace(void *cookie, enum dwc3_trace e, uint32_t a, uint32_t b)
{
	(void)cookie; (void)e; (void)a; (void)b;
}

/* DWC3 core 上下文 + DMA 区 (4KiB 对齐). 合计约 52KiB, 放进 .bss. */
static uint8_t dwc3_ctx[DWC3_CONTEXT_BYTES] __attribute__((aligned(8)));
static uint8_t dwc3_dma[DWC3_DMA_BYTES]   __attribute__((aligned(DWC3_DMA_ALIGNMENT)));
static struct dwc3 *dev;

static const struct dwc3_identity identity = {
	0x1209u, 0x316du, "UniXNU", "Byron Probe", "BYRON2026"
};

/* ---- USB 交接准备: 幂等. fastboot boot 后绝大多数已就绪, 只补未置位的位. ---- */
static void prepare_usb(void)
{
	diag_gctl     = rd32(DWC3_BASE + DWC3_GCTL);
	diag_dctl     = rd32(DWC3_BASE + DWC3_DCTL);
	diag_dsts     = rd32(DWC3_BASE + 0xc70cu);   /* DWC3_DSTS */
	diag_hwparams = rd32(DWC3_BASE + DWC3_GHWPARAMS0);

	/* Device role? GCTL.PRTCAPDIR bits 13:12 == 2. 若不是, dwc3_init 会强行设为 device. */
	/* PHY: 清 SUSPHY(bit6) + ENBLSLPM(bit8), 让 HS PHY 保持唤醒 (上游 acquire_phy). */
	diag_phycfg = rd32(DWC3_BASE + DWC3_GUSB2PHYCFG(0));
	if (diag_phycfg & ((1u << 6) | (1u << 8)))
		wr32(DWC3_BASE + DWC3_GUSB2PHYCFG(0), diag_phycfg & ~((1u << 6) | (1u << 8)));

	/* VBUS: 若软件 VBUS/session 位未置, 补上 (上游 acquire_vbus). */
	diag_vbus = rd32(QSCRATCH);
	if ((diag_vbus & SW_VBUS_MASK) != SW_VBUS_MASK)
		wr32(QSCRATCH, diag_vbus | SW_VBUS_MASK);
}

/* ---- 探测: 采集 SSPP 源寄存器 (只读, safe_rd32 在 start.S) ---- */
extern uint32_t safe_rd32(uint64_t pa, uint32_t *faulted);
static void probe_pipes(void)
{
	for (int i = 0; i < 10; i++) {
		uint64_t b = MDP + sspp_off[i];
		uint32_t f = 0, any = 0;
		pipes[i].addr   = safe_rd32(b + 0x00, &f); any |= f;
		pipes[i].size   = safe_rd32(b + 0x14, &f); any |= f;
		pipes[i].stride = safe_rd32(b + 0x24, &f); any |= f;
		pipes[i].fmt    = safe_rd32(b + 0x30, &f); any |= f;
		pipes[i].fault  = any;
	}
}

/* ---- 发送: 攒成 ASCII 行, 入 DWC3 TX 环, 循环 poll 直到发空 ---- */
static size_t strlen_local(const char *s) { size_t n = 0; while (s[n]) n++; return n; }
static void send_line(const char *s)
{
	if (dev) (void)dwc3_queue(dev, s, strlen_local(s));
}

static void send_all(uint64_t el, uint64_t load, uint64_t mmfr0)
{
	char b[160], *p;

	send_line("\r\n===BYRON_USB_PROBE_BEGIN===\r\n");
	send_line("MAGIC=BYRUSB1\r\n");

	p = cat(b, "EL="); p = dec(p, el); p = cat(p, "\r\n"); send_line(b);
	/* USB 交接自检 */
	p = cat(b, "GCTL=0x"); p = hex(p, diag_gctl, 8); p = cat(p, " DCTL=0x");
	p = hex(p, diag_dctl, 8); p = cat(p, " DSTS=0x"); p = hex(p, diag_dsts, 8);
	p = cat(p, "\r\n"); send_line(b);
	p = cat(b, "PHYCFG=0x"); p = hex(p, diag_phycfg, 8); p = cat(p, " VBUS=0x");
	p = hex(p, diag_vbus, 8); p = cat(p, " HWP0=0x"); p = hex(p, diag_hwparams, 8);
	p = cat(p, "\r\n"); send_line(b);
	/* load / mmfr0 */
	p = cat(b, "LOAD=0x"); p = hex(p, load, 16); p = cat(p, "\r\n"); send_line(b);
	p = cat(b, "MMFR0=0x"); p = hex(p, mmfr0, 16); p = cat(p, "\r\n"); send_line(b);
	int has16k = ((mmfr0 >> 20) & 0xf) != 0;
	p = cat(b, "PAGES16K="); p = cat(p, has16k ? "YES" : "NO"); p = cat(p, "\r\n"); send_line(b);

	/* framebuffer: 从 SSPP 选出的那条管道 */
	int pick = -1;
	for (int i = 0; i < 10; i++)
		if (!pipes[i].fault && pipes[i].addr >= SPLASH &&
		    pipes[i].addr < SPLASH + SPLASH_SIZE) { pick = i; break; }
	if (pick < 0)
		for (int i = 0; i < 10; i++)
			if (!pipes[i].fault) { pick = i; break; }

	if (pick >= 0) {
		uint32_t w = pipes[pick].size & 0xffff;
		uint32_t h = (pipes[pick].size >> 16) & 0xffff;
		uint32_t s = pipes[pick].stride & 0xffff;
		p = cat(b, "FB=0x"); p = hex(p, pipes[pick].addr, 8);
		p = cat(p, " W="); p = dec(p, w);
		p = cat(p, " H="); p = dec(p, h); p = cat(p, "\r\n"); send_line(b);
		p = cat(b, "STRIDE="); p = dec(p, s); p = cat(p, "\r\n"); send_line(b);
		p = cat(b, "FMT=0x"); p = hex(p, pipes[pick].fmt, 8);
		p = cat(p, " PIPE="); p = dec(p, pick); p = cat(p, "\r\n"); send_line(b);
	} else {
		send_line("FB=NONE\r\n");
	}

	/* 全部 10 条管道的原始值, 供离线复核 */
	for (int i = 0; i < 10; i++) {
		p = cat(b, "P"); p = dec(p, i);
		p = cat(p, "="); p = hex(p, pipes[i].addr, 8);
		p = cat(p, ","); p = hex(p, pipes[i].size, 8);
		p = cat(p, ","); p = hex(p, pipes[i].stride, 8);
		p = cat(p, ","); p = hex(p, pipes[i].fmt, 8);
		p = cat(p, ","); p = hex(p, pipes[i].fault, 1);
		p = cat(p, "\r\n"); send_line(b);
	}
	send_line("===BYRON_USB_PROBE_END===\r\n");
}

/* 让主机有时间把 TX 环里的字节读走: poll 直至发空并保持一段时间. */
static void drain_and_wait(uint64_t seconds)
{
	uint64_t frq = SYSREG(cntfrq_el0);
	uint64_t start = tick();
	uint64_t limit = frq * seconds;
	while (tick() - start < limit) {
		if (dev) (void)dwc3_poll(dev, 256);
		__asm__ volatile("yield" ::: "memory");
	}
}

static void psci_reset(void) __attribute__((noreturn));
static void psci_reset(void)
{
	register uint64_t x0 __asm__("x0") = 0x84000009;
	__asm__ volatile("smc #0" : "+r"(x0) :: "x1", "x2", "x3", "memory");
	for (;;) __asm__ volatile("wfe" ::: "memory");
}

/* start.S 传入 fdt, el, load. */
void usbprobe_main(uint64_t fdt, uint64_t el, uint64_t load)
{
	(void)fdt;
	struct dwc3_platform platform = {
		.cookie = NULL,
		.read32 = plat_read32,
		.write32 = plat_write32,
		.delay_us = plat_delay_us,
		.dma_sync = plat_dma_sync,
		.barrier = plat_barrier,
		.trace = plat_trace,
	};
	uint64_t mmfr0 = SYSREG(id_aa64mmfr0_el1);

	probe_pipes();

	/* DWC3 交接自检: GSNPSID 必须是 Synopsys DWC3. 若是 0/全 1, 说明
	 * 基址或时钟不对, 串口也不会出现——但值会写进 ramoops 尾部兜底. */
	uint32_t snpsid = rd32(DWC3_BASE + DWC3_GSNPSID);

	prepare_usb();
	int rc = dwc3_init(dwc3_ctx, sizeof(dwc3_ctx), &platform, &identity,
	                   dwc3_dma, (uint64_t)(uintptr_t)dwc3_dma, sizeof(dwc3_dma));
	dev = (struct dwc3 *)(void *)dwc3_ctx;

	if (rc == 0) {
		(void)dwc3_start(dev);
		/* 先发一个 banner, 让主机开始枚举; 枚举完成前 queued 会缓存. */
		send_line("\r\nBYRON USB PROBE v1 — waiting for CDC ACM host\r\n");
		/* Windows 首次识别这个 CDC ACM (VID 1209:316D) 通常要装 usbser/Zadig
		 * 驱动, 可能耗 1-2 分钟. 因此循环重发完整帧, 每轮 poll 3 秒让主机读走,
		 * 共 ~150 秒后才 reset. 捕获脚本只要在这窗口内打开串口就能拿到完整帧. */
		for (uint64_t round = 0; round < 50; round++) {
			send_all(el, load, mmfr0);
			drain_and_wait(3);
		}
	} else {
		/* USB 起不来: 把失败码与自检写进 ramoops 尾部, 重启后从 pstore 读.
		 * 这里只写纯 ASCII 且避开 console 环形区头部, 结构破坏风险可控. */
		volatile unsigned char *p = (volatile unsigned char *)(uintptr_t)0xff4ff800ull;
		char b[96], *q;
		#define PUTS(s) do { const char *_s = (s); while (*_s) *p++ = (unsigned char)*_s++; } while (0)
		PUTS("\nBYRON_USB_FAIL\n");
		PUTS("RC="); q = dec(b, (uint64_t)(int64_t)rc); PUTS(q); PUTS("\n");
		PUTS("SNPSID=0x"); q = hex(b, snpsid, 8); PUTS(q); PUTS("\n");
		PUTS("GCTL=0x"); q = hex(b, diag_gctl, 8); PUTS(q); PUTS("\n");
		PUTS("DSTS=0x"); q = hex(b, diag_dsts, 8); PUTS(q); PUTS("\n");
		PUTS("VBUS=0x"); q = hex(b, diag_vbus, 8); PUTS(q); PUTS("\n");
		PUTS("LOAD=0x"); q = hex(b, load, 16); PUTS(q); PUTS("\n");
		PUTS("MMFR0=0x"); q = hex(b, mmfr0, 16); PUTS(q); PUTS("\n");
		PUTS("P0=0x"); q = hex(b, pipes[0].addr, 8); PUTS(q); PUTS("\n");
		PUTS("BYRON_USB_FAIL_END\n");
		__asm__ volatile("dsb sy" ::: "memory");
		drain_and_wait(2);
	}
	psci_reset();
}
