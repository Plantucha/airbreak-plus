.syntax unified
.thumb

/* Optional custom-setting ID and the target selected at patch time. */
.section .rodata.target_rh_abi, "a", %progbits
.align 2
.global target_rh_fallback
.type target_rh_fallback, %object
target_rh_fallback:
    .float 0.85
.size target_rh_fallback, . - target_rh_fallback
.global target_rh_var_id
.type target_rh_var_id, %object
target_rh_var_id:
    .short 0xffff
.size target_rh_var_id, . - target_rh_var_id
