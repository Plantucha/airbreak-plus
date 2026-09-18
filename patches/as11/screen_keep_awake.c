/* Toggle LCD inactivity suppression with a three-finger hold. */

#include "stubs.h"

#define TOUCH_RING_OFFSET       0x10u
#define TOUCH_POINT_1_OFFSET    0x32u
#define TOUCH_POINT_2_OFFSET    0x36u
#define TOUCH_POINT_3_OFFSET    0x3Au
#define TOUCH_HOLD_LATCH_OFFSET 0x49u
#define TOUCH_HOLD_TIMER_OFFSET 0x4Cu
#define TOUCH_REPORT_STATE_OFFSET 0x58u

#define LED_TIMEOUT_OFFSET       0x30u
#define LED_CHANNEL_INDEX_OFFSET 0x00u
#define LED_TRANSITION_SLOT_0_OFFSET 0x2Cu
#define LED_RUNTIME_STATE_OFFSET 0x6Au
#define LED_LCD_CHANNEL_INDEX     3u

#define TOUCH_POINT_ACTIVE 0x80u
#define TOUCH_REPORT_READY 4u
#define TOUCH_DEFER_MS     300u
#define HOLD_DURATION_MS   2000u
#define CONFIRMATION_FADE_MS   200u
#define CONFIRMATION_PERIOD_MS 800u
#define CONFIRMATION_ON_MS     400u
#define CONFIRMATION_DURATION_MS 650u
#define DISABLE_FADE_MS        400u

#define STATE_KEEP_AWAKE     0x01u
#define STATE_GESTURE_ACTIVE 0x02u
#define STATE_GESTURE_FIRED  0x04u
#define STATE_FADE_PENDING   0x08u
#define STATE_TOUCH_CANDIDATE 0x10u
#define STATE_TOUCH_DEFERRED  0x20u
#define STATE_CONFIRMATION_ACTIVE 0x40u
#define STATE_WAIT_RELEASE 0x80u

typedef struct {
    unsigned int type;
    short x;
    short y;
} touch_event_t;

static unsigned int read_u32(void *base, unsigned int offset)
{
    return *(volatile unsigned int *)((unsigned char *)base + offset);
}

static void write_u32(void *base, unsigned int offset, unsigned int value)
{
    *(volatile unsigned int *)((unsigned char *)base + offset) = value;
}

static unsigned char *lcd_channel(void)
{
    unsigned char *controller = led_status_controller_singleton();
    void *timeout = controller + LED_TIMEOUT_OFFSET;
    void **slot = led_timeout_channel_slot_by_index(
        *(void **)timeout, LED_LCD_CHANNEL_INDEX);

    return *slot;
}

static volatile unsigned char *lcd_runtime_state(void)
{
    return lcd_channel() + LED_RUNTIME_STATE_OFFSET;
}

static int point_is_active(void *controller, unsigned int offset)
{
    return (read_u32(controller, offset) & TOUCH_POINT_ACTIVE) != 0;
}

static touch_event_t decode_touch_point(unsigned int packed)
{
    touch_event_t event;

    event.type = (packed & TOUCH_POINT_ACTIVE) != 0;
    event.x = (short)(((packed & 0x70u) << 4) |
        ((packed >> 8) & 0xFFu));
    event.y = (short)(((packed & 0x07u) << 8) |
        ((packed >> 16) & 0xFFu));
    return event;
}

static int enqueue_cancel_sequence(void *controller)
{
    touch_event_t events[3];
    void *ring = (unsigned char *)controller + TOUCH_RING_OFFSET;

    if (ring_buffer_free_count(ring) < 3)
        return 0;

    /* The first contact is already in the GUI queue when the third appears. */
    events[0] = decode_touch_point(
        read_u32(controller, TOUCH_POINT_2_OFFSET));
    events[1] = decode_touch_point(
        read_u32(controller, TOUCH_POINT_3_OFFSET));
    events[2].type = 0;
    events[2].x = -1;
    events[2].y = -1;
    ring_buffer_write_elements(ring, events, 3);
    return 1;
}

static void start_enable_confirmation(void)
{
    led_channel_schedule_transition(
        lcd_channel(), 0, 2, CONFIRMATION_FADE_MS,
        CONFIRMATION_PERIOD_MS, CONFIRMATION_ON_MS);
}

static void start_disable_confirmation(void)
{
    led_channel_schedule_transition(
        lcd_channel(), 0, 0, DISABLE_FADE_MS, ~0u, ~0u);
}

static void clear_confirmation(void)
{
    lcd_channel()[LED_TRANSITION_SLOT_0_OFFSET] = 0;
}

void __attribute__((section(".text.0.main")))
start(void *controller)
{
    volatile unsigned char *state;
    int first = point_is_active(controller, TOUCH_POINT_1_OFFSET);
    int second = point_is_active(controller, TOUCH_POINT_2_OFFSET);
    int third = point_is_active(controller, TOUCH_POINT_3_OFFSET);
    int all_three = first && second && third;
    int any = first || second || third;
    unsigned int saved_third = 0;

    if (*((volatile unsigned char *)controller +
            TOUCH_REPORT_STATE_OFFSET) != TOUCH_REPORT_READY) {
        touch_screen_controller_process_report(controller);
        return;
    }

    state = lcd_runtime_state();

    if ((*state & STATE_WAIT_RELEASE) != 0) {
        /* A clinical-menu hold owns all contacts through the final release. */
        if (!any) {
            *((volatile unsigned char *)controller + TOUCH_HOLD_LATCH_OFFSET) = 0;
            touch_screen_controller_process_report(controller);
            *state &= (unsigned char)~STATE_WAIT_RELEASE;
            return;
        }
        saved_third = read_u32(controller, TOUCH_POINT_3_OFFSET);
        write_u32(controller, TOUCH_POINT_3_OFFSET, saved_third | TOUCH_POINT_ACTIVE);
        touch_screen_controller_process_report(controller);
        write_u32(controller, TOUCH_POINT_3_OFFSET, saved_third);
        return;
    }

    if ((*state & STATE_GESTURE_ACTIVE) == 0 &&
            (*state & STATE_TOUCH_CANDIDATE) == 0 && any) {
        *state |= STATE_TOUCH_CANDIDATE;
        /* Leave earlier reports drainable, especially a preceding release. */
        if (ring_buffer_front_ptr((unsigned char *)controller + TOUCH_RING_OFFSET) == 0)
            *state |= STATE_TOUCH_DEFERRED;
        write_u32(controller, TOUCH_HOLD_TIMER_OFFSET, 0);
    }

    if ((*state & STATE_GESTURE_ACTIVE) == 0 && !any) {
        *state &= (unsigned char)~(
            STATE_TOUCH_CANDIDATE | STATE_TOUCH_DEFERRED);
        *((volatile unsigned char *)controller +
            TOUCH_HOLD_LATCH_OFFSET) = 0;
    }

    if (all_three && (*state & STATE_GESTURE_ACTIVE) == 0 &&
            ((*state & STATE_TOUCH_DEFERRED) != 0 ||
             enqueue_cancel_sequence(controller))) {
        if ((*state & STATE_TOUCH_DEFERRED) != 0)
            touch_screen_controller_discard_all_reports(controller);
        *state = (*state & STATE_KEEP_AWAKE) | STATE_GESTURE_ACTIVE;
        write_u32(controller, TOUCH_HOLD_TIMER_OFFSET, 0);
    }

    if ((*state & STATE_GESTURE_ACTIVE) == 0) {
        if (first && second && !third) {
            const touch_event_t *pending = ring_buffer_front_ptr(
                (unsigned char *)controller + TOUCH_RING_OFFSET);

            /* Do not replay a deferred press into the newly opened menu. */
            if (pending && pending->type != 2)
                touch_screen_controller_discard_all_reports(controller);
        }

        if ((*state & STATE_TOUCH_DEFERRED) != 0) {
            unsigned int elapsed = read_u32(
                controller, TOUCH_HOLD_TIMER_OFFSET);
            int moved = 0;

            if (first && !second && !third) {
                const touch_event_t *initial = ring_buffer_front_ptr(
                    (unsigned char *)controller + TOUCH_RING_OFFSET);
                touch_event_t current = decode_touch_point(
                    read_u32(controller, TOUCH_POINT_1_OFFSET));

                /* Preserve the queued press, then pass movement to the GUI now. */
                moved = initial && initial->type == 1 &&
                    (current.x != initial->x || current.y != initial->y);
            }

            if (first && !second && !third && (moved || elapsed >= TOUCH_DEFER_MS)) {
                *state &= (unsigned char)~STATE_TOUCH_DEFERRED;
                *((volatile unsigned char *)controller +
                    TOUCH_HOLD_LATCH_OFFSET) = 0;
                write_u32(controller, TOUCH_HOLD_TIMER_OFFSET, 0);
            }
        }

        touch_screen_controller_process_report(controller);

        if (first && second && !third) {
            const touch_event_t *pending = ring_buffer_front_ptr(
                (unsigned char *)controller + TOUCH_RING_OFFSET);

            if (pending && pending->type == 2) {
                *state &= (unsigned char)~(STATE_TOUCH_CANDIDATE | STATE_TOUCH_DEFERRED);
                *state |= STATE_WAIT_RELEASE;
            }
        }
        if ((*state & STATE_TOUCH_DEFERRED) != 0)
            *((volatile unsigned char *)controller +
                TOUCH_HOLD_LATCH_OFFSET) = 1;
        return;
    }

    if (any) {
        /* Keep partial releases on the stock three-contact suppression path. */
        if (!all_three) {
            saved_third = read_u32(controller, TOUCH_POINT_3_OFFSET);
            write_u32(
                controller,
                TOUCH_POINT_3_OFFSET,
                saved_third | TOUCH_POINT_ACTIVE);
        }

        touch_screen_controller_process_report(controller);

        if (!all_three) {
            write_u32(controller, TOUCH_POINT_3_OFFSET, saved_third);
            *((volatile unsigned char *)controller +
                TOUCH_HOLD_LATCH_OFFSET) = 0;
            write_u32(controller, TOUCH_HOLD_TIMER_OFFSET, 0);
            if ((*state & STATE_CONFIRMATION_ACTIVE) != 0) {
                clear_confirmation();
                *state &= (unsigned char)~STATE_CONFIRMATION_ACTIVE;
            }
            return;
        }

        if ((*state & STATE_GESTURE_FIRED) == 0 &&
                read_u32(controller, TOUCH_HOLD_TIMER_OFFSET) >=
                    HOLD_DURATION_MS) {
            if ((*state & STATE_KEEP_AWAKE) != 0) {
                *state &= (unsigned char)~STATE_KEEP_AWAKE;
                *state |= STATE_FADE_PENDING;
                start_disable_confirmation();
            } else {
                *state |= STATE_KEEP_AWAKE | STATE_CONFIRMATION_ACTIVE;
                start_enable_confirmation();
                write_u32(controller, TOUCH_HOLD_TIMER_OFFSET, 0);
            }
            *state |= STATE_GESTURE_FIRED;
        }

        if ((*state & STATE_CONFIRMATION_ACTIVE) != 0 &&
                read_u32(controller, TOUCH_HOLD_TIMER_OFFSET) >=
                    CONFIRMATION_DURATION_MS) {
            clear_confirmation();
            *state &= (unsigned char)~STATE_CONFIRMATION_ACTIVE;
        }

        /* Reuse the stock two-finger timer while all three contacts remain. */
        *((volatile unsigned char *)controller + TOUCH_HOLD_LATCH_OFFSET) =
            (*state & (STATE_GESTURE_FIRED | STATE_CONFIRMATION_ACTIVE)) !=
                STATE_GESTURE_FIRED;
        return;
    }

    *((volatile unsigned char *)controller + TOUCH_HOLD_LATCH_OFFSET) = 0;
    write_u32(controller, TOUCH_HOLD_TIMER_OFFSET, 0);
    if ((*state & (STATE_GESTURE_FIRED | STATE_FADE_PENDING)) ==
            STATE_GESTURE_FIRED)
        clear_confirmation();
    touch_screen_controller_process_report(controller);
    *state &= (STATE_KEEP_AWAKE | STATE_FADE_PENDING);
}

void screen_keep_awake_process_touch_events(void *user_interface)
{
    volatile unsigned char *state = lcd_runtime_state();

    if ((*state & STATE_TOUCH_DEFERRED) != 0)
        return;

    user_interface_process_touch_events(user_interface);
    if ((*state & (STATE_GESTURE_ACTIVE | STATE_FADE_PENDING)) ==
            STATE_FADE_PENDING) {
        *state &= (unsigned char)~STATE_FADE_PENDING;
        led_timeout_fade_channels_off(
            (unsigned char *)led_status_controller_singleton() +
                LED_TIMEOUT_OFFSET);
        clear_confirmation();
    }
}

void screen_keep_awake_schedule_transition(
    void *channel,
    unsigned int priority,
    unsigned int target,
    unsigned int duration_ms,
    unsigned int arg5,
    unsigned int arg6)
{
    unsigned char *bytes = channel;

    if (bytes[LED_CHANNEL_INDEX_OFFSET] == LED_LCD_CHANNEL_INDEX &&
            (bytes[LED_RUNTIME_STATE_OFFSET] &
                (STATE_KEEP_AWAKE | STATE_FADE_PENDING)) != 0)
        return;

    led_channel_schedule_transition(
        channel, priority, target, duration_ms, arg5, arg6);
}
