ENTRY(_head)
SECTIONS {
	. = 0;
	.text : { *(.text.head) *(.text*) }
	.rodata : { *(.rodata*) }
	.data : { *(.data*) }
	/* DWC3 DMA arena needs 4KiB alignment; bump .bss base accordingly. */
	. = ALIGN(4096);
	_bss_start = .;
	.bss : { *(.bss*) *(COMMON) }
	. = ALIGN(16);
	_bss_end = .;
	. += 0x8000;
	_stack_top = .;
	_image_end = .;
	/DISCARD/ : { *(.comment) *(.note*) *(.eh_frame*) }
}
