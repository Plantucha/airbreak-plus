/*
 * Universal S9 LCD adapter for SX474-1201, 1203 and 1301.
 * Detect ILI9225 through register 0; keep the native driver for other IDs.
 * Window/cursor dispatch rereads the ID and restores GRAM write mode before
 * returning. No unallocated SRAM or persistent controller-selection flag.
 */

#define MAIN    __attribute__((section(".text.0.main")))
#define STATIC  static __attribute__((section(".text.x.nonmain")))

typedef unsigned int      uint32;
typedef unsigned short    uint16;
typedef unsigned char     uint8;

extern void lcd_write_cmd(uint16 index);
extern void lcd_write_data(uint16 value);
extern void lcd_read_data(uint16 *value);
extern uint32 stock_lcd_init(void);
extern uint32 stock_lcd_set_window(int x0, int y0, int x1, int y1);
extern uint32 stock_lcd_set_cursor(int x, int y, uint32 r2, uint32 r3);
extern volatile uint32 lcd_window_x0, lcd_window_y0;
extern volatile uint32 lcd_window_x1, lcd_window_y1;
extern void gpio_set_bit(uint32 gpio_base, uint16 bit);
extern void gpio_clear_bit(uint32 gpio_base, uint16 bit);
extern void gpio_init(uint32 gpio_base, void *init_struct);
extern void lcd_rs_gpio_init(void);
extern void delay_spin(void);

typedef struct {
    uint16 pin;
    uint8  mode;
    uint8  speed;
} gpio_init_t;

STATIC void ili_write_reg(uint16 reg, uint16 val)
{
    lcd_write_cmd(reg);
    lcd_write_data(val);
}

// ~1ms per unit. delay_spin is ~0.1ms at 72MHz.
STATIC void ili_delay_ms(int ms)
{
    int i;
    for (i = 0; i < ms * 10; i++)
        delay_spin();
}

// Prepare both boards before reading the controller ID.
STATIC void lcd_prepare(void)
{
    uint32 gpioe = 0x40011800;
    uint16 pin4  = 0x10;

    // GPIOG.15 (RS/DC) - push-pull output
    lcd_rs_gpio_init();

    // GPIOG.9 (FSMC_NE2) - chip select for bank 2 (0x64000000)
    // Enable chip select for boards that route LCD CS through PG9.
    {
        gpio_init_t cfg = { 0x0200, 0x0B, 0x10 };
        gpio_init(0x40012000, &cfg);
    }

    // GPIOE.4 (RESET) - push-pull output
    {
        gpio_init_t cfg = { 0x0010, 0x03, 0x10 };
        gpio_init(gpioe, &cfg);
    }

    // hardware reset
    gpio_clear_bit(gpioe, pin4);
    ili_delay_ms(10);
    gpio_set_bit(gpioe, pin4);
    ili_delay_ms(50);
}

/* Register 0 reads 0x9225 on ILI9225 (datasheet section 8.2.3).
 * Discard an initial read, then require the same ID on two separate accesses.
 * Invalid/unstable values (including an open bus) retain the native driver.
 */
STATIC uint16 lcd_read_id(void)
{
    uint16 value;
    lcd_write_cmd(0);
    lcd_read_data(&value);
    lcd_read_data(&value);
    return value;
}

STATIC int lcd_is_ili9225(int startup)
{
    int attempt;
    for (attempt = 0; attempt < 3; ++attempt) {
        uint16 id = lcd_read_id();
        if (id == 0x0047)  // Native Himax controller ID.
            return 0;
        if (id == 0x9225 && lcd_read_id() == 0x9225)
            return 1;
        if (startup && attempt < 2)
            ili_delay_ms(1);
    }
    return 0;
}

// ILI9225 init values from SX474-0905 firmware at 0x08050030.
STATIC void ili9225_lcd_init(void)
{
    // power-on sequence
    ili_write_reg(0x28, 0x00FF);  ili_delay_ms(5);
    ili_write_reg(0x07, 0x0000);
    ili_write_reg(0x11, 0x0000);  ili_delay_ms(5);

    ili_write_reg(0x11, 0x001A);
    ili_write_reg(0x12, 0x3121);
    ili_write_reg(0x13, 0x004C);
    ili_write_reg(0x14, 0x5C69);
    ili_write_reg(0x10, 0x0800);  ili_delay_ms(10);

    // step-up ramp
    ili_write_reg(0x11, 0x011A);  ili_delay_ms(50);
    ili_write_reg(0x11, 0x031A);  ili_delay_ms(50);
    ili_write_reg(0x11, 0x071A);  ili_delay_ms(50);
    ili_write_reg(0x11, 0x0F1A);  ili_delay_ms(50);
    ili_write_reg(0x11, 0x0F3A);  ili_delay_ms(50);

    // display control
    ili_write_reg(0x01, 0x011C);  // driver output: SS=1, NL=0x1C (176 lines)
    ili_write_reg(0x02, 0x0100);  // line inversion
    ili_write_reg(0x03, 0x0018);  // entry mode: BGR=0 (emWin=RGB565), ID0=1, AM=1
    ili_write_reg(0x07, 0x0000);
    ili_write_reg(0x08, 0x0808);
    ili_write_reg(0x0B, 0x1100);
    ili_write_reg(0x0C, 0x0000);
    ili_write_reg(0x0F, 0x1401);
    ili_write_reg(0x15, 0x0000);

    // full-screen window
    ili_write_reg(0x30, 0x0000);
    ili_write_reg(0x36, 0x00AF);  // H end = 175
    ili_write_reg(0x37, 0x0000);
    ili_write_reg(0x38, 0x00DB);  // V end = 219
    ili_write_reg(0x39, 0x0000);

    // gamma
    ili_write_reg(0x50, 0x0001);
    ili_write_reg(0x51, 0x020B);
    ili_write_reg(0x52, 0x0805);
    ili_write_reg(0x53, 0x0404);
    ili_write_reg(0x54, 0x0C0C);
    ili_write_reg(0x55, 0x000C);
    ili_write_reg(0x56, 0x0101);
    ili_write_reg(0x57, 0x0400);
    ili_write_reg(0x58, 0x1108);
    ili_write_reg(0x59, 0x0006);

    // display on
    ili_write_reg(0x0F, 0x0A01);
    ili_write_reg(0x07, 0x1012);  ili_delay_ms(50);
    ili_write_reg(0x20, 0x0000);
    ili_write_reg(0x21, 0x0000);
    ili_write_reg(0x07, 0x1017);  ili_delay_ms(100);
    lcd_write_cmd(0x22);
}


/*
 * Set drawing window.
 * emWin sends landscape coords (x=0..219, y=0..175).
 * ILI9225 is portrait (H=0..175, V=0..219), so we swap x<->y
 * and invert V (219-x) to fix the left-right mirror.
 * AM=1 in entry mode makes pixel fill match emWin's x-major scan.
 */
__attribute__((section(".text.1.set_window"), used, noinline))
uint32 s9_lcd_set_window(int x0, int y0, int x1, int y1)
{
    if (!lcd_is_ili9225(0))
        return stock_lcd_set_window(x0, y0, x1, y1);

    // Native emWin cache; addresses are supplied by the CDX-specific stubs.
    lcd_window_x0 = x0;
    lcd_window_y0 = y0;
    lcd_window_x1 = x1;
    lcd_window_y1 = y1;

    ili_write_reg(0x37, (uint16)y0);            // H start
    ili_write_reg(0x36, (uint16)y1);            // H end
    ili_write_reg(0x39, (uint16)(219 - x1));    // V start
    ili_write_reg(0x38, (uint16)(219 - x0));    // V end
    ili_write_reg(0x20, (uint16)y0);            // cursor H
    ili_write_reg(0x21, (uint16)(219 - x0));    // cursor V
    lcd_write_cmd(0x22);
    return (uint32)y1;
}


// Set GRAM cursor + enter write mode.
__attribute__((section(".text.2.set_cursor"), used, noinline))
uint32 s9_lcd_set_cursor(int x, int y, uint32 r2, uint32 r3)
{
    if (!lcd_is_ili9225(0))
        return stock_lcd_set_cursor(x, y, r2, r3);
    ili_write_reg(0x20, (uint16)y);
    ili_write_reg(0x21, (uint16)(219 - x));
    lcd_write_cmd(0x22);
    return r3;
}

MAIN uint32 s9_lcd_init(void)
{
    lcd_prepare();
    if (lcd_is_ili9225(1)) {
        ili9225_lcd_init();
        return 0x10030010;
    }
    return stock_lcd_init();
}
