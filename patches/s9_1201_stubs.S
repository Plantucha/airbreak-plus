// s9_1201_stubs.S - SX474-1201 firmware function addresses

#define NSTUB(addr,name) \
	.global name; \
	.extern name; \
	name = addr
.text

NSTUB(0x0809870B, lcd_write_cmd)
NSTUB(0x08098721, lcd_write_data)
NSTUB(0x080998E1, gpio_set_bit)
NSTUB(0x080998E5, gpio_clear_bit)
NSTUB(0x08099855, gpio_init)
NSTUB(0x080986E9, lcd_rs_gpio_init)
NSTUB(0x08080AB3, delay_spin)

// Native LCD read, continuation points, and emWin window cache.
NSTUB(0x0809875D, lcd_read_data)
NSTUB(0x08080AE3, stock_lcd_init_resume)
NSTUB(0x08044675, stock_lcd_window_resume)
NSTUB(0x0804464F, stock_lcd_cursor_resume)
NSTUB(0x20016474, lcd_window_x0)
NSTUB(0x20016478, lcd_window_y0)
NSTUB(0x2001647C, lcd_window_x1)
NSTUB(0x20016480, lcd_window_y1)
