/* Select fonts from the active language instead of the available-language mask.
 * The GUI task owns profile changes; variable callbacks keep their stock behavior.
 * Existing widgets are retained, including their navigation and editing state.
 */
#include "s10_vars.h"

typedef unsigned char u8;
typedef unsigned short u16;
typedef unsigned int u32;

struct font {
    const void *methods[6];
    u8 height, line_height, x_scale, y_scale;
};

struct font_profile {
    const void *methods;
    const struct font *text, *large;
    u8 initialized;
};

struct value_widget {
    const void *methods;
    int x, y;
    u8 dirty, visible;
    u16 reserved;
    int width, height;
    u16 value_var, enable_var;
    u8 left_aligned;
};

struct pressure_arc {
    u8 state[0x1c];
    const void *bitmap;
    short x, y, radius;
    u8 animation[6];
    struct {
        const void *methods;
        short x0, y0, x1, y1;
    } text_rect;
    u32 text_style;
};

extern const struct font font_16, font_text_japanese, font_text_chinese;
extern const struct font font_large_standard, font_large_cjk;
extern struct font_profile *gui_font_profile_get(void);
extern int variable_get_by_id(int var_id);
extern void variable_set_by_id(int var_id, int value);
extern int gui_variable_binding_update_value(void *binding);
extern unsigned g8_index_from_short_var_id(int var_id);

extern const struct font *GUI_SetFont(const struct font *font);
extern void GUI_SetTextMode(int mode);
extern void GUI_SetTextAlign(int align);
extern void GUI_DispStringAt(const char *text, int x, int y);
extern int gui_get_string_width(const char *text);
extern int gui_base_window_height(void *window);
extern const char *string_id_lookup_current_locale(const short *str_id);
extern void gui_disp_string_lookup_left(void *row, int str_id, int x);

extern void gui_variable_text_widget_update(struct value_widget *widget);
extern void gui_variable_text_widget_draw(struct value_widget *widget);
extern void gui_pressure_arc_layout_init(struct pressure_arc *arc, const void *bitmap,
                                         int x, int y, u32 text_style);
extern void gui_draw_breath_arc(struct pressure_arc *arc);

static unsigned language_profile(unsigned language)
{
    if (language == 13 || language == 19)
        return 1;
    if (language == 16 || language == 17)
        return 2;
    return 0;
}

static const struct font *text_font(unsigned profile)
{
    if (profile == 1)
        return &font_text_japanese;
    if (profile == 2)
        return &font_text_chinese;
    return &font_16;
}

static void select_profile(struct font_profile *fonts, unsigned profile)
{
    fonts->text = text_font(profile);
    fonts->large = profile ? &font_large_cjk : &font_large_standard;

    /* FON also controls text positioning in stock widgets. */
    variable_set_by_id(VAR_ID_FON, profile);
}

/* Called by stock font initialization, which sets the initialized flag afterward. */
void start(struct font_profile *fonts)
{
    select_profile(fonts, language_profile(variable_get_by_id(VAR_ID_LAN)));
}

/* Preserve the GIT refresh signal, and change fonts before menu/dialog updates.
 * Check LAN even when GIT is unchanged: two writes may share a system tick.
 */
int language_fonts_update(void *binding)
{
    int changed = gui_variable_binding_update_value(binding);
    struct font_profile *fonts = gui_font_profile_get();
    unsigned profile = language_profile(variable_get_by_id(VAR_ID_LAN));

    if (fonts->text != text_font(profile)) {
        select_profile(fonts, profile);
        changed = 1;
    }
    return changed;
}

/* The language list contains several scripts at once. Its raw option index is
 * the language ID; other enum lists retain the normal global-font drawing path.
 */
void language_fonts_draw_option(void *row, int str_id, int x)
{
    u8 *model = *(u8 **)((u8 *)row + 0x0c);
    unsigned option = *(u32 *)((u8 *)row + 0x10);
    unsigned g8_index = model[4 + 0x14];

    if (g8_index != g8_index_from_short_var_id(VAR_ID_LAN)) {
        gui_disp_string_lookup_left(row, str_id, x);
        return;
    }

    short ref = (short)str_id;
    const struct font *previous = GUI_SetFont(text_font(language_profile(option)));
    GUI_SetTextMode(2);
    GUI_SetTextAlign(0x0c);
    GUI_DispStringAt(string_id_lookup_current_locale(&ref), x + 5,
                    gui_base_window_height(row) / 2);
    GUI_SetFont(previous);
}

/* Stock caches this width at construction. Keep the original left/right anchor
 * when the font changes; do not move a right-aligned value into its neighbour.
 */
static void update_value_width(struct value_widget *widget)
{
    const struct font *previous = GUI_SetFont(gui_font_profile_get()->large);
    int width = 3 * gui_get_string_width("0") + 5;
    GUI_SetFont(previous);

    if (width != widget->width) {
        if (!widget->left_aligned)
            widget->x += widget->width - width;
        widget->width = width;
        widget->dirty = 1;
    }
}

void language_fonts_update_value(struct value_widget *widget)
{
    update_value_width(widget);
    gui_variable_text_widget_update(widget);
}

void language_fonts_draw_value(struct value_widget *widget)
{
    /* Hidden or timer-driven widgets can be painted before their next update. */
    update_value_width(widget);
    gui_variable_text_widget_draw(widget);
}

void language_fonts_draw_arc(struct pressure_arc *arc)
{
    int half_height = gui_font_profile_get()->large->line_height / 2;
    if (arc->text_rect.y1 - arc->y != half_height) {
        /* Reuse stock geometry without resetting pressure/animation state. */
        gui_pressure_arc_layout_init(arc, arc->bitmap, arc->x, arc->y, arc->text_style);
    }
    gui_draw_breath_arc(arc);
}
