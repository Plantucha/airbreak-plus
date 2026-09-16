/* Replay only the verified instructions replaced by the LCD entry hooks.
 * Init's first BL is PC-relative, so reassemble it rather than copying bytes.
 * The remaining native code, literals and return conventions stay in place.
 */
.syntax unified
.thumb
.section .text.x.native,"ax",%progbits

.global stock_lcd_init
.thumb_func
stock_lcd_init:
    push {r7, lr}
    bl lcd_rs_gpio_init
    b.w stock_lcd_init_resume

.global stock_lcd_set_window
.thumb_func
stock_lcd_set_window:
    push {r3, r4, r5, r6, r7, lr}
    movs r7, r0
    b.w stock_lcd_window_resume

.global stock_lcd_set_cursor
.thumb_func
stock_lcd_set_cursor:
    push {r3, r4, r5, lr}
    movs r5, r0
    b.w stock_lcd_cursor_resume
