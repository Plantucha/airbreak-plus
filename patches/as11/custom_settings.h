#ifndef AS11_CUSTOM_SETTINGS_H
#define AS11_CUSTOM_SETTINGS_H

/* Stock clinical-menu rows available while custom factories are called. */
typedef struct {
    void **stock_items;
    unsigned int stock_item_count;
} custom_menu_context_t;

typedef void *(*custom_menu_item_factory_t)(
    unsigned int var_id, unsigned int label_id, const custom_menu_context_t *context);

#endif
