#ifndef AS11_STUBS_H
#define AS11_STUBS_H

extern int DataItem_get_var_id_virtual(void *item);
extern int DataItem_read_bytes_by_id(unsigned short var_id, void *buffer, unsigned int buffer_size);
extern int DataItem_read_value_by_id(unsigned short var_id);
extern void DataItem_set_visible_by_id(unsigned short var_id, int visible);
extern void DataItem_write_raw_by_id(unsigned short var_id, int raw_value);
extern void DataItem_write_text_notify_by_id(unsigned short var_id, const char *text);
extern void *memset(void *dest, int value, unsigned int length);
extern void AsvFeature_update(void *ctx);
extern void FeedbackInput_get_ref(int **value, unsigned int slot);
extern void FeedbackOutput_get_ref(float **value, unsigned int slot);
extern void *heap_alloc(unsigned int size);

/* Native registry and encoder entry points used by Airbreak RPC providers. */
extern void rpc_profile_json_formatter_registry_ctor(void);
extern void *rpc_profile_json_formatter_registration_ctor(void *registration);
extern int json_encoder_write_raw_span(
    void *formatter, void *encoder, const void *span);

/* Native cellular FileFetcher and flow-generator upgrade state machine. */
extern int gfile_fetcher_control_can_start(void *control);
extern void upgrade_command_executor_set_result(void *executor, unsigned int result);
extern void upgrade_command_executor_set_state_after_hook(void);
extern void GuiTextValueFormatter_ctor(void *formatter);
extern void GuiTextValueFormatter_dtor(void *formatter);
extern void *GuiMenuTextValueListItem_ctor(
    void *item, unsigned int var_id, unsigned int label_id, void *formatter);
extern void *gui_menu_data_value_callback_ctor_empty(void *callback);
extern void gui_menu_data_value_callback_dtor(void *callback);
extern void *GuiMenuDataValueListItem_ctor(
    void *item, unsigned int var_id, unsigned int label_id,
    unsigned int title_id, unsigned int activity_id, void *controller,
    void *callback, unsigned int flags);
extern void *GuiScroller_ctor(
    void *scroller,
    unsigned int arg2,
    unsigned int arg3,
    unsigned int arg4,
    unsigned int arg5,
    void **items,
    unsigned int item_count,
    unsigned int arg8,
    unsigned int arg9,
    unsigned int arg10,
    unsigned int arg11,
    unsigned int arg12);
extern void GuiPaint_DrawLocalizedTextById(
    unsigned int text_id,
    void *rect,
    unsigned int text_size,
    unsigned int font,
    int clip,
    unsigned int alignment);
extern void GuiPaint_DrawStringInRect(
    const char *text,
    void *rect,
    unsigned int text_size,
    unsigned int font,
    int clip,
    unsigned int alignment,
    int font_slot);
extern int gui_localized_text_font_slot_for_id(unsigned int text_id);
extern unsigned int datetime_current_local_milliseconds_of_day(void);
extern void *user_interface_root_widget_ctor(
    void *root,
    unsigned int arg2,
    unsigned int arg3,
    unsigned int arg4);
extern void user_interface_root_widget_status_blink_timer_callback_adjustor(
    void *callback_self);
extern void thunk_gui_timer_handle_reschedule_with_optional_delay(
    void *timer,
    unsigned int delay_ms);
extern void gui_owned_object_invalidate(void *object);

/* Native touch and backlight entry points used by the keep-awake gesture. */
extern void touch_screen_controller_process_report(void *controller);
extern void touch_screen_controller_discard_all_reports(void *controller);
extern unsigned int ring_buffer_free_count(void *ring);
extern void *ring_buffer_front_ptr(void *ring);
extern void ring_buffer_write_elements(
    void *ring, const void *elements, unsigned int count);
extern void user_interface_process_touch_events(void *user_interface);
extern void *led_status_controller_singleton(void);
extern void *led_timeout_channel_slot_by_index(
    void *channels, unsigned int index);
extern void led_channel_schedule_transition(
    void *channel,
    unsigned int priority,
    unsigned int target,
    unsigned int duration_ms,
    unsigned int arg5,
    unsigned int arg6);
extern void led_timeout_fade_channels_off(void *timeout);

#endif
