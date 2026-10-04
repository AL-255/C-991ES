/* SPDX-License-Identifier: GPL-3.0-only */
#ifndef FX_BOOT_EVENTS_H
#define FX_BOOT_EVENTS_H
#include "fx_boot.h"
#include "fx_diagnostic_contrast.h"
#include "fx_diagnostic_rom_status.h"
#include "../ui/fx_key_controller.h"

typedef enum {
    FX_BOOT_EVENT_WAIT = 0,
    FX_BOOT_EVENT_READY = 1,
    FX_BOOT_EVENT_RESET = 2,
    FX_BOOT_EVENT_EXPORT = 3,
    FX_BOOT_EVENT_INVALID = -1,
    FX_BOOT_EVENT_UNIMPLEMENTED = -2
} fx_boot_event_status;

typedef enum {
    FX_WELCOME_RELEASE = 1,
    FX_WELCOME_POLL = 2,
    FX_WELCOME_SCAN = 3,
    FX_WELCOME_DONE = 4
} fx_welcome_phase;

/* The original 2381-count decision is a number of peripheral polls, not a
 * wall-clock duration. All locals remain with the host. */
typedef struct {
    uint16_t remaining;
    fx_key_state remembered;
    uint8_t phase;
    uint8_t decision;
    uint8_t active;
} fx_welcome_state;

typedef struct { uint8_t active; } fx_host_control_state;

void fx_welcome_begin(fx_welcome_state *state);
/* One release, all-row poll, or scan/debounce phase. READY retains decision;
 * a nonzero decision requests the full diagnostic sequence7044. */
fx_boot_event_status fx_welcome_tick(fx_platform *platform,
    fx_welcome_state *state, const fx_key_input *input);
/* Decision boundary1E51C, after a successful scan and debounce. This adapter
 * consumes a stable physical matrix pair, not a mapped calculator token. */
fx_boot_event_status fx_welcome_accept_pair(fx_platform *platform,
    fx_welcome_state *state, fx_key_state stable_key);
void fx_welcome_draw_banner(fx_platform *platform);

/*5550 split at its peripheral-service boundary5564. The host may change
 *8E00 between begin and finish; finish returns0/1 and always clears it. */
int fx_host_control_begin(fx_platform *platform, fx_host_control_state *state);
int fx_host_control_finish(fx_platform *platform, fx_host_control_state *state);
void fx_host_control_notify(fx_platform *platform);
/*5596 inherits the caller's timer argument; it does not load129A itself. */
void fx_host_control_clear(fx_platform *platform, uint16_t period);

uint16_t fx_diagnostic_checksum(fx_platform *platform);
/*71EC..72CC display-only preparation. read_test_result is supplied explicitly
 * at the7286 label-selection boundary: A5 selects Read OK. This helper does
 * not execute7334 and is separate from the normal boot lifecycle below. */
void fx_diagnostic_draw_screen(fx_platform *platform, uint8_t read_test_result);
/* Actual71EC composition: version/checksum/Pd and two display flushes, then
 * the ordered7334 ROM/status/retention test, then its computed Read caption,
 * ports and final flush. A missing provider returns UNAVAILABLE before any
 * display or bus operation; it is not translated to a native Read NG. */
fx_diagnostic_rom_status_result fx_diagnostic_run_screen(fx_platform *platform,
    const fx_diagnostic_resources *resources);
/*7150/715E/717E/71A6 display preparation, before the raw ALPHA wait.
 * pattern0 white,1 black,2 border,3 alternating55/AA,4 alternatingAA/55. */
int fx_diagnostic_draw_pattern(fx_platform *platform, uint8_t pattern);
uint8_t fx_diagnostic_single_bit(uint8_t value);
/*70D4 counter preparation; caller clears the framebuffer only on entry. */
int fx_diagnostic_draw_key_counter(fx_platform *platform, uint8_t index);

typedef enum {
    FX_BOOT_EVENTS_WELCOME = 1,
    FX_BOOT_EVENTS_PATTERN = 2,
    FX_BOOT_EVENTS_DIAGNOSTIC = 3,
    FX_BOOT_EVENTS_CONTRAST = 4,
    FX_BOOT_EVENTS_KEY_TEST = 5,
    FX_BOOT_EVENTS_RESET_PROMPT = 6,
    FX_BOOT_EVENTS_DONE = 7
} fx_boot_events_phase;

/* Native welcome7010 and diagnostic740C/7044 control flow, expressed as
 * named nonblocking host phases. Keyboard packets stay in8E01/02 until the
 * host clears them after a completed tick. No synthetic RAM locals exist. */
typedef struct {
    fx_welcome_state welcome;
    fx_host_control_state control;
    fx_key_wait raw_wait;
    fx_key_controller keys;
    fx_diagnostic_contrast_state contrast;
    uint8_t phase;
    uint8_t pattern;
    uint8_t key_index;
    uint8_t full_diagnostic;
    uint8_t boot_continuation;
    uint8_t active;
} fx_boot_events;

/* Continue a prior fx_boot_reset/resume WELCOME or DIAGNOSTIC boundary.
 * The standard simulator lifecycle executes7334 against its volatile
 * software resource backend; no success byte is supplied by policy.
 * READY completes the ordinary boot tail atD7AE, including mode12 policy. */
fx_boot_event_status fx_boot_events_begin(fx_platform *platform,
    fx_boot_events *state, fx_boot_status request);
/* Standalone7044 sequence, ending after its reset/default-screen return;
 * useful for semantic hosts and prepared original-ROM comparisons. */
fx_boot_event_status fx_boot_diagnostic_sequence_begin(fx_platform *platform,
    fx_boot_events *state);
fx_boot_event_status fx_boot_events_tick(fx_platform *platform,
    fx_boot_events *state, const fx_key_input *physical_input);
#endif
