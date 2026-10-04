#include "fx_keys.h"

static uint8_t read_columns(fx_platform *p, const fx_key_input *input, uint8_t rows)
{
    return input && input->sample ? input->sample(input->context, rows) : fx_data_read(p, 0, 0xf040);
}

uint8_t fx_key_scan(fx_platform *p, const fx_key_input *input, fx_key_state *state)
{
    uint8_t found = 0, rows = 1;
    for (unsigned n = 0; n < 7; ++n, rows = (uint8_t)(rows << 1)) {
        fx_data_write(p, 0, 0xf046, rows);
        uint8_t sample = read_columns(p, input, rows);
        if (sample != 0xff) {
            state->columns = (uint8_t)~sample;
            state->rows = rows;
            found = 1;
            break;
        }
    }
    fx_key_deselect_all(p);
    return found;
}

uint8_t fx_key_debounce(fx_platform *p, const fx_key_input *input, fx_key_state *state)
{
    unsigned hits = 0;
    for (unsigned n = 0; n < 5; ++n) {
        fx_timer_start(p, 13);
        fx_data_write(p, 0, 0xf046, state->rows);
        uint8_t columns = (uint8_t)~read_columns(p, input, state->rows);
        fx_key_deselect_all(p);
        columns &= state->columns;
        if (columns) { ++hits; state->columns = columns; }
    }
    return (uint8_t)(hits == 5);
}

uint8_t fx_key_is_held(fx_platform *p, const fx_key_input *input, const fx_key_state *state)
{
    uint8_t found = 0;
    fx_data_write(p, 0, 0xf046, state->rows);
    for (unsigned n = 0; n < 10; ++n) {
        if (((uint8_t)~read_columns(p, input, state->rows)) & state->columns) {
            found = 1; break;
        }
        fx_timer_start(p, 13);
    }
    fx_key_deselect_all(p);
    if (!found) fx_clear_busy(p);
    return found;
}

static unsigned highest_bit(uint8_t mask)
{
    unsigned index = 0;
    while ((mask >>= 1) != 0) ++index;
    return index;
}

uint8_t fx_key_map(fx_platform *p, fx_key_state state, uint16_t table)
{
    if (!state.columns || !state.rows) return 0;
    unsigned index = highest_bit(state.columns) * 8 + highest_bit(state.rows);
    return fx_data_read(p, 0, (uint16_t)(table + index));
}

uint8_t fx_key_map_current(fx_platform *p, fx_key_state state)
{
    uint8_t modifiers = fx_data_read(p, 0, 0x80f8);
    uint8_t calculation = fx_data_read(p, 0, 0x80f9);
    uint16_t table;
    if (modifiers & 4) table = 0x087e;
    else if (modifiers & 2) table = 0x08be;
    else if (modifiers & 1) table = 0x08fe;
    else if (modifiers & 8) table = calculation == 2 ? 0x097e : 0x083e;
    else table = calculation == 2 ? 0x093e : 0x07fe;
    return fx_key_map(p, state, table);
}

uint8_t fx_key_is_modifier(uint8_t token) { return (uint8_t)(token >= 0xe8 && token <= 0xec); }

int fx_key_update_modifiers(fx_platform *p, uint8_t token)
{
    uint8_t flags = fx_data_read(p, 0, 0x80f8);
    if (token == 0xec) return -1;
    switch (token) {
    case 0xe8: flags = (uint8_t)((flags ^ 4) & 0xf4); break;
    case 0xe9: flags = (uint8_t)((flags ^ 8) & 0xf8); break;
    case 0xea: flags = (uint8_t)((flags ^ 2) & 0xf2); break;
    case 0xeb: flags = (uint8_t)((flags ^ 1) & 0xf1); break;
    default: flags &= 0xf0; break;
    }
    fx_data_write(p, 0, 0x80f8, flags);
    return 0;
}

uint8_t fx_key_is_data_token(fx_platform *p, uint8_t token)
{
    return (uint8_t)(token && (!fx_data_read(p, 0, 0x80f7) || (token >= 32 && token <= 223)));
}

uint8_t fx_key_is_menu_token(fx_platform *p, uint8_t token)
{
    return (uint8_t)(token && fx_data_read(p, 0, 0x80f7) &&
                    (token == 0xf1 || (token >= 0xf6 && token <= 0xfb)));
}

uint8_t fx_key_is_direction_token(fx_platform *p, uint8_t token)
{
    return (uint8_t)(fx_data_read(p, 0, 0x80f7) && token >= 0xe0 && token <= 0xe3);
}

uint8_t fx_key_can_math_input(fx_platform *p)
{
    if (!fx_data_read(p, 0, 0x8106) || fx_data_read(p, 0, 0x810c)) return 0;
    uint8_t context = fx_data_read(p, 0, 0x80f9);
    if (!(context & 0x40)) return 0;
    if (context == 69 && fx_data_read(p, 0, 0x80fe) == 1 && fx_data_read(p, 0, 0x80fa) <= 2) return 0;
    return 1;
}

void fx_key_normalize_action(fx_platform *p)
{
    if (fx_data_read(p, 0, 0x80fe) != 1 || fx_data_read(p, 0, 0x80f7) != 1) return;
    uint8_t token = fx_data_read(p, 0, 0x80f5);
    if (token == 0xf6) {
        fx_data_write(p, 0, 0x80f5, 0x5c);
        fx_data_write(p, 0, 0x80f7, 0);
    } else if (token == 0xf1 || (token >= 0xf7 && token <= 0xfb))
        fx_data_write(p, 0, 0x80f5, 0);
}
