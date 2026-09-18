# Air11 LCD GRAM capture through the STM32H753 8-bit FMC interface.
# Usage: source tcl/as11-lcd-screenshot.tcl; as11_lcd::capture lcd.ppm

if {[llength [info commands binary]] == 0} {
    source [file join [file dirname [info script]] binary.tcl]
}

namespace eval as11_lcd {
    variable cmd 0x60000000
    variable data 0x60000001
    variable width 320
    variable height 240
    variable moder 0x58021400
    variable odr 0x58021414
    variable bsrr 0x58021418
    variable afrl 0x58021420
}

proc as11_lcd::read32 {address} {
    return [lindex [read_memory $address 32 1] 0]
}

proc as11_lcd::prepare_window {first_row row_count} {
    variable cmd
    variable data
    variable width

    foreach {command start end} [list 0x2a 0 [expr {$width - 1}] 0x2b $first_row [expr {$first_row + $row_count - 1}]] {
        mwb $cmd $command
        foreach byte [list [expr {$start >> 8}] [expr {$start & 255}] [expr {$end >> 8}] [expr {$end & 255}]] {
            mwb $data $byte
        }
    }
    mwb $cmd 0x2e
    # The native 8-bit backend discards one byte, then reads R, G, B.
    read_memory $data 8 1
}

proc as11_lcd::read_row {} {
    variable cmd
    variable width
    set row ""
    set bytes {}
    # Each aligned 32-bit FMC read supplies four consecutive 8-bit bus cycles.
    foreach word [read_memory $cmd 32 [expr {$width * 3 / 4}]] {
        lappend bytes [expr {$word & 255}] [expr {($word >> 8) & 255}] \
            [expr {($word >> 16) & 255}] [expr {($word >> 24) & 255}]
    }
    foreach {r g b} $bytes {
        # Match the native RGB565 conversion, expanded to host RGB888.
        append row [binary format c* [list \
            [expr {($r & 0xf8) | ($r >> 5)}] \
            [expr {($g & 0xfc) | ($g >> 6)}] \
            [expr {($b & 0xf8) | ($b >> 5)}]]]
    }
    return $row
}

proc as11_lcd::restore_rs {saved_moder saved_odr} {
    variable moder
    variable bsrr
    mww $moder $saved_moder
    mww $bsrr [expr {($saved_odr & 1) ? 1 : 0x10000}]
}

proc as11_lcd::capture {{path "lcd.ppm"} {first_row 0} {row_count 240}} {
    variable width
    variable height
    variable moder
    variable odr
    variable bsrr
    variable afrl

    if {![string is integer -strict $first_row] || ![string is integer -strict $row_count] ||
        $first_row < 0 || $row_count < 1 || $first_row + $row_count > $height} {
        error "Invalid LCD row range"
    }
    set header "P6\n$width $height\n255\n"
    if {$first_row > 0 && (![file exists $path] ||
        [file size $path] != [string length $header] + $first_row * $width * 3)} {
        error "LCD output does not contain the preceding $first_row rows"
    }

    if {([read32 0x5c001000] & 0xfff) != 0x450} {
        error "Air11 capture requires an STM32H743/753 target"
    }
    # DBGMCU_APB4FZ1.IWDG1 and DBGMCU_APB3FZ1.WWDG1 stop while halted.
    mww 0x5c001054 [expr {[read32 0x5c001054] | 0x40000}]
    mww 0x5c001034 [expr {[read32 0x5c001034] | 0x40}]
    halt

    if {([read32 0x52004000] & 0x3f) != 1} {
        error "LCD FMC bank 1 is not enabled in non-multiplexed 8-bit SRAM mode"
    }
    set saved_moder [read32 $moder]
    set saved_odr [read32 $odr]
    if {($saved_moder & 3) != 2 || ([read32 $afrl] & 15) != 12} {
        error "LCD PF0 is not configured as FMC_A0"
    }

    set target [target current]
    set dap [$target cget -dap]
    set saved_ap [$dap apsel]
    set out [::open $path [expr {$first_row == 0 ? "wb" : "ab"}]]
    set rs_changed 0
    set csw_saved 0
    set status [catch {
        $dap apsel [$target cget -ap-num]
        if {![regexp {csw (0x[0-9a-fA-F]+)} [$dap apcsw] match saved_csw]} {
            error "Cannot read debug-port memory access attributes"
        }
        set csw_saved 1
        # STM32H7 OpenOCD enables cacheable debug accesses. LCD GRAM reads
        # must reach the bus each time, including repeated reads of one address.
        $dap apcsw 0 0x08000000
        fconfigure $out -translation binary
        if {$first_row == 0} {
            ::puts -nonewline $out $header
        }
        prepare_window $first_row $row_count

        # PF0 is LCD command/data select. Holding it high allows sequential
        # memory reads to consume the data port without alternating commands.
        set rs_changed 1
        mww $bsrr 1
        mww $moder [expr {($saved_moder & ~3) | 1}]
        for {set y 0} {$y < $row_count} {incr y} {
            ::puts -nonewline $out [read_row]
        }
    } message]

    if {$rs_changed} {
        if {[catch {restore_rs $saved_moder $saved_odr} restore_message]} {
            set status 1
            append message "\nFailed to restore PF0: $restore_message"
        }
    }
    if {$csw_saved} {
        if {[catch {$dap apcsw $saved_csw 0x08000000} restore_message]} {
            set status 1
            append message "\nFailed to restore debug-port access attributes: $restore_message"
        }
    }
    if {[catch {$dap apsel $saved_ap} restore_message]} {
        set status 1
        append message "\nFailed to restore debug-port selection: $restore_message"
    }
    if {[catch {::close $out} close_message]} {
        set status 1
        append message "\nFailed to close output: $close_message"
    }
    if {$status} {
        error $message
    }
    return
}
