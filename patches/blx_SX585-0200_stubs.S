.syntax unified
.thumb

/* SX585-0200 BLX is copied from file offset 0x300 to SRAM 0x20000000. */
.global boot_command_dispatch
.thumb_set boot_command_dispatch, 0x200001bf

.global usart_dma_write
.thumb_set usart_dma_write, 0x200012f3

.global timer_reset
.thumb_set timer_reset, 0x20000e57

.global timeout_get_instance
.thumb_set timeout_get_instance, 0x20000f99

.global usart_get
.thumb_set usart_get, 0x2000142b

.global frame_build
.thumb_set frame_build, 0x200015a5
