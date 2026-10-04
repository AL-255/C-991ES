/* SPDX-License-Identifier: GPL-3.0-only */
#include "fx_key_dispatch.h"

int fx_key_process_token(fx_platform *p, uint8_t token,
                          uint16_t action_address, uint8_t *output)
{
    if (!output) return -1;
    *output = 0;
    if (fx_data_read(p, 0, 0x80f9) == 0xc4) {
        if (token == 0xf8 || token == 0xf9) token = 0x80;
        else if (token == 0x60 && (fx_data_read(p, 0, 0x80f8) & 8)) token = 0xaf;
    }
    if (token == 0xe7) {
        fx_data_write(p, 0, action_address, 3);
        fx_timer_start(p, 1);
    }
    if (fx_key_is_modifier(token)) {
        if (fx_editor_update_modifiers(p, token)) return -1;
        return 0;
    }
    if (fx_editor_update_modifiers(p, 0)) return -1;
    if (token == 0xf0 && !fx_key_can_math_input(p)) token = 0xed;
    if (token == 0xc8 && fx_data_read(p, 0, 0x80f9) != 0xc1) token = 0;
    *output = token;
    return 1;
}
