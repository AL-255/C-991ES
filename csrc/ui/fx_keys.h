/* High-level matrix scanning and key-map lookup. GPL-3.0-only. */
#ifndef FX_KEYS_H
#define FX_KEYS_H
#include "../platform/fx_platform.h"

typedef struct { uint8_t columns, rows; } fx_key_state;
/* Return the active-low F040 value for the selected F046 row mask.
 * A null callback reads the passive peripheral register in platform RAM. */
typedef uint8_t (*fx_key_sample)(void *context, uint8_t rows);
typedef struct { fx_key_sample sample; void *context; } fx_key_input;

/* 1d9a6: ascending rows, first nonempty row, state unchanged if none. */
uint8_t fx_key_scan(fx_platform *platform, const fx_key_input *input, fx_key_state *state);
/* 1d9e4: five samples, columns narrowed to intersections on successful reads. */
uint8_t fx_key_debounce(fx_platform *platform, const fx_key_input *input, fx_key_state *state);
/* 1d958: ten bounded samples; clear busy state when no selected key is held. */
uint8_t fx_key_is_held(fx_platform *platform, const fx_key_input *input, const fx_key_state *state);
/* 1dae6: the highest set bit wins when multiple columns/rows are present. */
uint8_t fx_key_map(fx_platform *platform, fx_key_state state, uint16_t table);
/* Modifier/context table selection in 1dbc2..1dc3e; no editing side effects. */
uint8_t fx_key_map_current(fx_platform *platform, fx_key_state state);
uint8_t fx_key_is_modifier(uint8_t token);
/* 1dcf4: ordinary and four modifier transitions. EC additionally refreshes
 * the editor cursor; return -1 without changing state until that integration. */
int fx_key_update_modifiers(fx_platform *platform, uint8_t token);
/* Stateful token classes at 4106/4120/41d0. */
uint8_t fx_key_is_data_token(fx_platform *platform, uint8_t token);
uint8_t fx_key_is_menu_token(fx_platform *platform, uint8_t token);
uint8_t fx_key_is_direction_token(fx_platform *platform, uint8_t token);
uint8_t fx_key_can_math_input(fx_platform *platform);
void fx_key_normalize_action(fx_platform *platform);
#endif
