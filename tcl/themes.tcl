# ============================================================
# ResMed AirSense 10 UI Theme Patcher
# ============================================================

namespace eval theme {

    # --------------------------------------------------------
    # Address layout (per-version)
    # --------------------------------------------------------
    variable entry_len 4
    variable palette_size 0x54
    variable cdx_ver ""
    variable base_addr
    variable end_addr
    # Offsets within one palette. Together these groups cover all 21 entries.
    variable groups
    array set groups {
        selected {0x24}
        whites {0x00 0x1c 0x28 0x40 0x44 0x48}
        bright {0x04 0x0c 0x20}
        mid {0x08}
        low {0x10 0x14 0x30 0x4c}
        black {0x18 0x34 0x50}
        accent {0x2c 0x38}
        light {0x3c}
    }

    # --------------------------------------------------------
    # Detect CDX version and set palette addresses
    # --------------------------------------------------------
    proc _detect_version {} {
        variable cdx_ver
        variable base_addr
        variable end_addr
        variable groups

        set cdx_ver [patch::read_string 0x40000 11 -nul]

        switch -exact -- $cdx_ver {
            SX567-0401 - SX567-0306 {
                set base_addr 0xf26f8
            }
            SX567-0402 {
                set base_addr 0xf2970
            }
            default {
                error "theme: unsupported CDX version \"$cdx_ver\""
            }
        }
        set end_addr [expr {$base_addr + 0x50}]
    }

    proc _ensure_version {} {
        variable cdx_ver
        if {$cdx_ver eq ""} { _detect_version }
    }

    # Palette 0 is the standard theme; palette 1 is the alternate firmware theme.
    proc _palette_base {palette} {
        _ensure_version
        variable base_addr
        variable palette_size
        if {$palette ni {0 1}} { error "theme: palette must be 0 or 1" }
        return [expr {$base_addr + $palette * $palette_size}]
    }

    # Resolve and validate all writes before entering the flash guard.
    # Flat definitions use addresses in palette 0, relocated to the chosen palette.
    proc _writes {defs palette {group_list {}}} {
        variable groups
        variable base_addr
        variable palette_size
        set target [_palette_base $palette]
        set allowed {}
        foreach group $group_list {
            if {![info exists groups($group)]} { error "unknown color group \"$group\"" }
            lappend allowed {*}$groups($group)
        }
        if {[llength $defs] % 2} { error "theme: expected color/value pairs" }
        set writes {}
        foreach {key color} $defs {
            if {![regexp {^[0-9a-fA-F]{6}00$} $color]} {
                error "theme: invalid RGB color \"$color\"; expected rrggbb00"
            }
            if {[string match 0x* $key]} {
                if {![string is integer -strict $key]} { error "theme: invalid address $key" }
                set offset [expr {$key - $base_addr}]
                if {$offset < 0 || $offset >= $palette_size || $offset % 4} {
                    error "theme: address $key is outside palette 0"
                }
                set offsets [list $offset]
            } else {
                if {![info exists groups($key)]} { error "unknown color group \"$key\"" }
                set offsets $groups($key)
            }
            foreach offset $offsets {
                set offset [expr {$offset}]
                if {[llength $group_list]} {
                    set include 0
                    foreach permitted $allowed {
                        if {$offset == $permitted} { set include 1; break }
                    }
                    if {!$include} { continue }
                }
                lappend writes [expr {$target + $offset}] $color
            }
        }
        return $writes
    }

    proc _apply {defs palette {group_list {}}} {
        set writes [_writes $defs $palette $group_list]
        patch::with_guard {
            foreach {addr color} $writes { patch::hexstr $addr $color }
        }
    }


    # --------------------------------------------------------
    # Theme definitions
    # --------------------------------------------------------

    variable themes_uncompensated {
        default {
            selected 0099cc00
            whites   ffffff00
            bright   96969600
            mid      64646400
            low      40404000
            black    00000000
            accent   00395300
            light    d0d0d000
        }

        default_low_gamma {
            selected 0082ad00
            whites   e0e0e000
            bright   86868600
            mid      5e5e5e00
            low      40404000
            black    00000000
        }

        default_very_low_gamma {
            selected 00739900
            whites   cccccd00
            bright   78787800
            mid      54545400
            low      3a3a3a00
            black    00000000
        }

        default_ultra_low_gamma {
            selected 00608000
            whites   b6b6b600
            bright   64646400
            mid      44444400
            low      2e2e2e00
            black    00000000
        }

        default_dim {
            selected 00506600
            whites   cccccd00
            bright   6a6a6a00
            mid      4a4a4a00
            low      24242400
            black    00000000
        }

        default_blackout {
            selected 00404f00
            whites   d6d6d600
            bright   5c5c5c00
            mid      3a3a3a00
            low      1c1c1c00
            black    00000000
        }

        asmageddon {
            selected cc330000
            whites   ffbb4400
            bright   96484800
            mid      64323200
            low      40202000
            black    08000800
        }

        asmageddon_dark {
            selected 70180c00
            whites   f3885100
            bright   50282800
            mid      2c161600
            low      11080800
            black    08000800
        }

        night_vision {
            selected 66000000
            whites   e6c0c000
            bright   4a2a2a00
            mid      32181800
            low      160a0a00
            black    00000000
        }

        night_toned {
            selected 00668800
            whites   d8d8d800
            bright   80808000
            mid      58585800
            low      30303000
            black    00000000
        }

        night_dark {
            selected 00557700
            whites   c8c8c800
            bright   78787800
            mid      50505000
            low      28282800
            black    00000000
        }

        deep_blue {
            selected 004c6600
            whites   c4ccd200
            bright   6e747800
            mid      4a4f5400
            low      2a2f3400
            black    08000800
        }

        night_amber {
            selected 80550000
            whites   e6d3a300
            bright   7a6a4a00
            mid      564a3600
            low      2e261a00
            black    08000800
        }

        graphite {
            selected 4a6a7a00
            whites   d0d4d800
            bright   7a7f8400
            mid      565a5e00
            low      2c2f3300
            black    08000800
        }

        graphite_dark {
            selected 36515f00
            whites   d6d6d600
            bright   62676c00
            mid      44484c00
            low      24272b00
            black    08000800
        }

        night_red {
            selected 7a2a2a00
            whites   e0c8c800
            bright   7a5a5a00
            mid      543a3a00
            low      2a1c1c00
            black    08000800
        }

        ember_night {
            selected 66160000
            whites   d8c6c000
            bright   5a403800
            mid      3e2a2400
            low      1f140f00
            black    00000000
        }

        charcoal_light {
            selected 2e3a4000
            whites   b8b8b800
            bright   4a4a4a00
            mid      2f2f2f00
            low      18181800
            black    00000000
        }

        charcoal {
            selected 1e262a00
            whites   8e8e8e00
            bright   2c2c2c00
            mid      1a1a1a00
            low      0c0c0c00
            black    00000000
        }

        charcoal_warm {
            selected 3a2a2400
            whites   b8a8a000
            bright   4a3e3800
            mid      30262200
            low      18120f00
            black    00000000
        }

    }

    variable themes {

        default {
            selected 0099cc00
            whites   ffffff00
            bright   96969600
            mid      64646400
            low      40404000
            black    00000000
            accent   00395300
            light    d0d0d000
        }

        default_low_gamma {
            selected 00828c00
            whites   e4e0d600
            bright   90867100
            mid      685e4b00
            low      48403100
            black    00000000
        }

        default_very_low_gamma {
            selected 00737a00
            whites   d2ccbe00
            bright   82786300
            mid      5d544200
            low      423a2d00
            black    00000000
        }

        default_ultra_low_gamma {
            selected 00606400
            whites   beb6a300
            bright   6e645000
            mid      4c443500
            low      342e2300
            black    00000000
        }

        default_dim {
            selected 00504f00
            whites   d2ccbe00
            bright   746a5600
            mid      534a3a00
            low      29241800
            black    00000000
        }

        default_blackout {
            selected 00404200
            whites   dbd6ca00
            bright   655c4a00
            mid      413a2d00
            low      1f1c1500
            black    00000000
        }

        ember_night {
            selected 75160000
            whites   e2c6a000
            bright   65402a00
            mid      482a1a00
            low      24140b00
            black    00000000
        }

        asmageddon {
            selected cc330000
            whites   ffbb4400
            bright   96484800
            mid      64323200
            low      40202000
            black    08000800
        }

        asmageddon_dark {
            selected 7d180a00
            whites   ff886300
            bright   58281900
            mid      30160f00
            low      12080700
            black    08000800
        }

        night_vision {
            selected 76000000
            whites   f0c09c00
            bright   542a1f00
            mid      3a180f00
            low      1a0a0700
            black    00000000
        }

        night_toned {
            selected 00666700
            whites   ddd8ce00
            bright   8a806c00
            mid      5f584800
            low      342e2400
            black    00000000
        }

        night_dark {
            selected 00555600
            whites   cec8ba00
            bright   82786300
            mid      564f4000
            low      2c281f00
            black    00000000
        }

        deep_blue {
            selected 004c3600
            whites   cdccb700
            bright   78745e00
            mid      534f3f00
            low      302f2500
            black    08000800
        }

        night_amber {
            selected 8c550000
            whites   f0d39000
            bright   896a3a00
            mid      604c2700
            low      34261400
            black    08000800
        }

        graphite {
            selected 506a5d00
            whites   dad4c400
            bright   897f6800
            mid      5f5a4900
            low      312f2500
            black    08000800
        }

        night_red {
            selected 862a2200
            whites   e6c8aa00
            bright   896a4c00
            mid      5e4f3b00
            low      2e1c1600
            black    08000800
        }

        graphite_dark {
            selected 3b515400
            whites   bfb6a800
            bright   6c675300
            mid      4c483a00
            low      27271f00
            black    08000800
        }

        charcoal_light {
            selected 333a3300
            whites   c0b8a000
            bright   534a3a00
            mid      362f2300
            low      1c181200
            black    00000000
        }

        charcoal {
            selected 22261f00
            whites   988e7900
            bright   322c2100
            mid      1e1a1300
            low      0e0c0900
            black    00000000
        }

        charcoal_warm {
            selected 422a1b00
            whites   c2a88d00
            bright   533e2b00
            mid      37261900
            low      1c120b00
            black    00000000
        }
    }



    # --------------------------------------------------------
    # Apply dispatcher
    # --------------------------------------------------------

    proc apply {name {palette 0}} {
        variable themes

        if {![dict exists $themes $name]} {
            error "unknown theme \"$name\""
        }

        set theme [dict get $themes $name]

        if {[string match 0x* [lindex $theme 0]]} {
            apply_flat $name $palette
        } else {
            apply_grouped $name $palette
        }
    }

    proc apply_flat {name {palette 0}} {
        variable themes

        if {![dict exists $themes $name]} {
            error "unknown theme \"$name\" (use theme::usage)"
        }

        set defs [dict get $themes $name]

        _apply $defs $palette

        return $name
    }


    proc apply_grouped {name {palette 0}} {
        variable themes
        variable groups

        if {![dict exists $themes $name]} {
            error "unknown theme \"$name\""
        }

        set theme [dict get $themes $name]

        _apply $theme $palette

        return $name
    }



    proc patch_group {group givencolor {palette 0}} {
        _apply [list $group $givencolor] $palette

        return $group
    }

    proc patch_groups {group_color_pairs {palette 0}} {
        _apply $group_color_pairs $palette

        return $group_color_pairs
    }

    proc apply_groups {name group_list {palette 0}} {
        variable themes
        variable groups

        if {![dict exists $themes $name]} {
            error "unknown theme \"$name\""
        }

        set defs [dict get $themes $name]

        if {[llength $group_list]} { _apply $defs $palette $group_list }

        return $name
    }


    # Convenience aliases
    proc default {{palette 0}} { apply default $palette }

    # --------------------------------------------------------
    # Internal helper: extract 4 bytes from bulk read
    # --------------------------------------------------------
    proc _read_u32 {blob base addr} {
        set idx [expr {$addr - $base}]
        set bytes [lrange $blob $idx [expr {$idx + 3}]]
        return [string tolower [format "%02x%02x%02x%02x" \
            [scan [lindex $bytes 0] %x] \
            [scan [lindex $bytes 1] %x] \
            [scan [lindex $bytes 2] %x] \
            [scan [lindex $bytes 3] %x]]]
    }

    # --------------------------------------------------------
    # Detect currently applied theme
    # --------------------------------------------------------

    proc current {{palette 0} {arg ""}} {
        # Retain the original `current -v` spelling for palette 0.
        if {$palette eq "-v" && $arg eq ""} { set palette 0; set arg -v }
        set target [_palette_base $palette]
        variable themes
        variable groups
        variable base_addr
        variable end_addr
        variable entry_len

        set verbose 0
        if {$arg eq "-v"} {
            set verbose 1
        } elseif {$arg ne ""} {
            error "usage: theme::current ?palette? ?-v?"
        }

        set len [expr {$end_addr - $base_addr + $entry_len}]
        set blob [patch::read $target $len]

        set current {}

        foreach group [array names groups] {
            set vals {}
            foreach offset $groups($group) {
                lappend vals [_read_u32 $blob $target [expr {$target + $offset}]]
            }
            set uniq [lsort -unique $vals]
            if {[llength $uniq] == 1} {
                dict set current $group [lindex $uniq 0]
            } else {
                dict set current $group mixed
            }
        }

        set detected "custom/unknown"

        foreach {name theme} $themes {
            set ok 1
            foreach {group expected} $theme {
                if {![dict exists $current $group]} {
                    set ok 0
                    break
                }
                if {[dict get $current $group] ne [string tolower $expected]} {
                    set ok 0
                    break
                }
            }
            if {$ok} {
                set detected $name
                break
            }
        }

        if {$verbose} {
            echo "Palette $palette theme: $detected"
            echo "Current colors by group:"
            foreach group [lsort [array names groups]] {
                echo [format "  %-9s : %s" $group [dict get $current $group]]
            }
        }

        return $detected
    }



    # --------------------------------------------------------
    # Usage / help
    # --------------------------------------------------------

    proc usage {} {
        _ensure_version
        variable themes
        variable groups
        variable base_addr
        variable end_addr
        variable entry_len

        echo "Commands:"
        echo "  theme::usage"
        echo "      Show this help and current theme state"
        echo ""
        echo "  theme::current ?palette? \[-v\]"
        echo "      Detect currently applied theme"
        echo ""
        echo "  theme::apply <theme> ?palette?"
        echo "      Apply full theme by name"
        echo ""
        echo "  theme::apply_groups <theme> {group1 group2 ...} ?palette?"
        echo "      Apply only selected color groups from a theme"
        echo ""
        echo "  theme::patch_group <group> <color> ?palette?"
        echo "      Patch a single color group with a raw color value"
        echo ""
        echo "  theme::patch_groups { <group> <color> ... } ?palette?"
        echo "      Patch multiple groups with explicit colors"
        echo ""

        echo "Color groups:"
        foreach group [lsort [array names groups]] {
            echo "  $group"
        }

        echo ""
        echo "Palette: 0 = standard (default), 1 = alternate (For Her)."
        echo "Omitted color groups retain their current values."
        echo ""
        echo "Available themes:"
        foreach {name _} $themes {
            echo "  $name"
        }

        echo ""
        echo "Examples:"
        echo "  theme::apply default_blackout"
        echo "  theme::apply default_blackout 1"
        echo "  theme::apply_groups night_vision { whites low }"
        echo "  theme::patch_group whites d6d6d600"
        echo "  theme::patch_groups { whites d6d6d600 low 1c1c1c00 }"
    }


}

if {[info level] == 0} {
    theme::usage
} else {
    echo "[info script] loaded."
    echo {    theme::usage for instructions}
}
