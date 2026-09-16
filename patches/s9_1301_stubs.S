// s9_1301_stubs.S - SX474-1301 firmware function addresses

#define NSTUB(addr,name) \
	.global name; \
	.extern name; \
	name = addr
.text

NSTUB(0x080B5AAB, lcd_write_cmd)
NSTUB(0x080B5AC1, lcd_write_data)
NSTUB(0x080B728D, gpio_set_bit)
NSTUB(0x080B7291, gpio_clear_bit)
NSTUB(0x080B7201, gpio_init)
NSTUB(0x080B5A89, lcd_rs_gpio_init)
NSTUB(0x08099FE7, delay_spin)

// Native LCD read, continuation points, and emWin window cache.
NSTUB(0x080B5AFD, lcd_read_data)
NSTUB(0x0809A017, stock_lcd_init_resume)
NSTUB(0x08052A1D, stock_lcd_window_resume)
NSTUB(0x080529F7, stock_lcd_cursor_resume)
NSTUB(0x200176DC, lcd_window_x0)
NSTUB(0x200176E0, lcd_window_y0)
NSTUB(0x200176E4, lcd_window_x1)
NSTUB(0x200176E8, lcd_window_y1)
