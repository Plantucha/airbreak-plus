// s9_1203_stubs.S - SX474-1203 firmware function addresses

#define NSTUB(addr,name) \
	.global name; \
	.extern name; \
	name = addr
.text

// FSMC LCD bus writes (0x64000000, GPIOG.15 = RS)
NSTUB(0x08098B17, lcd_write_cmd)
NSTUB(0x08098B2D, lcd_write_data)

// GPIO
NSTUB(0x08099CED, gpio_set_bit)
NSTUB(0x08099CF1, gpio_clear_bit)
NSTUB(0x08099C61, gpio_init)
NSTUB(0x08098AF5, lcd_rs_gpio_init)  // GPIOG.15 as push-pull output

// delay loop body, ~0.1ms per call at 72MHz
NSTUB(0x08080E9F, delay_spin)

// Native LCD read, continuation points, and emWin window cache.
NSTUB(0x08098B69, lcd_read_data)
NSTUB(0x08080ECF, stock_lcd_init_resume)
NSTUB(0x08045295, stock_lcd_window_resume)
NSTUB(0x0804526F, stock_lcd_cursor_resume)
NSTUB(0x200164F4, lcd_window_x0)
NSTUB(0x200164F8, lcd_window_y0)
NSTUB(0x200164FC, lcd_window_x1)
NSTUB(0x20016500, lcd_window_y1)
