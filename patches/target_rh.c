/* Return the climate model's RH fraction for both Auto and Manual control. */
extern int variable_get_by_id(int var_id);
extern const unsigned short target_rh_var_id;
extern const float target_rh_fallback;

float start(void)
{
    /* The patcher supplies the fixed target when no menu setting is installed. */
    if (target_rh_var_id == 0xffffu)
        return target_rh_fallback;
    return (float)variable_get_by_id(target_rh_var_id) * 0.01f;
}
