/* SPDX-License-Identifier: GPL-3.0-only */
#include "fx_diagnostic_contrast.h"
#include "../render/fx_render_memory.h"

static int valid_platform(const fx_platform *p)
{
    return p && p->ram;
}

static void put(fx_platform *p, uint16_t address, uint8_t value)
{
    fx_data_write(p, 0, address, value);
}

static fx_render display(fx_platform *p)
{
    fx_render render = {p->rom, p->rom_size, p->ram};
    return render;
}

static void paint_menu(fx_platform *p)
{
    fx_render render = display(p);
    /* 402E enters 54E6 directly, without 54E0's special-screen guard. */
    put(p, 0x811f, 7);
    put(p, 0x8121, 0);
    put(p, 0xf031, 6);
    static const struct { uint16_t address; uint8_t mask; } indicators[] = {
        {0xf800, 0x10}, {0xf800, 0x04}, {0xf801, 0x02},
        {0xf802, 0x40}, {0xf80b, 0x80}, {0xf80a, 0x08}, {0xf80b, 0x10}
    };
    for (unsigned n = 0; n < sizeof indicators / sizeof indicators[0]; ++n)
        put(p, indicators[n].address,
            (uint8_t)(fx_data_read(p, 0, indicators[n].address) & ~indicators[n].mask));
    fx_fill_display(&render, 0, 2);
    uint16_t caption = 0x11ce;
    for (unsigned row = 0; row < 4; ++row) {
        fx_draw_text(&render, 0, (int8_t)(1u + 8u*row), &caption);
        caption = (uint16_t)(caption + 1u);
    }
    put(p, 0x8121, 1);
    fx_display_port_active(p);
}

fx_diagnostic_contrast_status fx_diagnostic_contrast_draw_value(
    fx_platform *p, uint8_t value)
{
    if (!valid_platform(p)) return FX_DIAGNOSTIC_CONTRAST_INVALID;
    uint8_t high = (uint8_t)((value >> 4) | 0x30);
    uint8_t low = (uint8_t)(value | 0x30);
    int signed_low = low & 0x80 ? (int)low - 256 : low;
    if (signed_low > 0x39) low = (uint8_t)(low + 7u);
    const uint8_t caption[3] = {high, low, 'h'};
    put(p, 0x8121, 0);
    put(p, 0x811f, 7);
    fx_render render = display(p);
    for (unsigned n = 0; n < sizeof caption; ++n)
        fx_draw_glyph(&render, (uint8_t)(6u*n), 8, caption[n]);
    put(p, 0x8121, 1);
    return FX_DIAGNOSTIC_CONTRAST_WAIT;
}

fx_diagnostic_contrast_status fx_diagnostic_contrast_begin(
    fx_platform *p, fx_diagnostic_contrast_state *state, uint8_t expanded)
{
    if (!valid_platform(p) || !state) return FX_DIAGNOSTIC_CONTRAST_INVALID;
    state->value = fx_data_read(p, 0, 0x8112);
    state->minimum = expanded ? 0 : 4;
    state->maximum = expanded ? 31 : 29;
    state->expanded = expanded;
    state->active = 1;
    paint_menu(p);
    if (expanded) fx_diagnostic_contrast_draw_value(p, state->value);
    return FX_DIAGNOSTIC_CONTRAST_WAIT;
}

fx_diagnostic_contrast_status fx_diagnostic_contrast_step(
    fx_platform *p, fx_diagnostic_contrast_state *state, uint8_t token)
{
    if (!valid_platform(p) || !state || !state->active)
        return FX_DIAGNOSTIC_CONTRAST_INVALID;
    if (token == 0xe6) {
        state->active = 0;
        return FX_DIAGNOSTIC_CONTRAST_DONE;
    }
    if (token == 0xe3) {
        if (state->value > state->minimum) {
            fx_acquire_busy(p);
            --state->value;
        } else fx_clear_busy(p);
    } else if (token == 0xe2) {
        if (state->value < state->maximum) {
            fx_acquire_busy(p);
            ++state->value;
        } else fx_clear_busy(p);
    }
    put(p, 0xf032, state->value);
    put(p, 0x8112, state->value);
    if (state->expanded) fx_diagnostic_contrast_draw_value(p, state->value);
    return FX_DIAGNOSTIC_CONTRAST_WAIT;
}
