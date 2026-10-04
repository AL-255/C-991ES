/* SPDX-License-Identifier: GPL-3.0-only */
#include "fx_annunciator.h"
#include "../platform/fx_result_classify.h"

enum {
    ROW_BUFFER = 0x87d0, LCD_ROW = 0xf800, ROW_BYTES = 12,
    MODIFIERS = 0x80f8, MODE = 0x80f9, RESULT_STATE = 0x80fe,
    DISPLAY_FORMAT = 0x8102, ANGLE_UNIT = 0x8105, MATH_DISPLAY = 0x8106,
    HISTORY_FLAGS = 0x8129, FIRST_SCALAR = 0x8226, SECOND_SCALAR = 0x8408
};

static uint8_t read_byte(fx_platform *p, uint16_t address)
{
    return fx_data_read(p, 0, address);
}

static void indicator(fx_platform *p, unsigned byte, uint8_t mask)
{
    uint16_t address = (uint16_t)(ROW_BUFFER + byte);
    fx_data_write(p, 0, address, (uint8_t)(read_byte(p, address) | mask));
}

int fx_annunciator_draw(fx_platform *p)
{
    uint8_t modifiers, mode, value;
    fx_result_classification result;
    unsigned i;
    int status;
    if (!p || !p->ram) return -1;

    for (i = 0; i < ROW_BYTES; ++i)
        fx_data_write(p, 0, (uint16_t)(ROW_BUFFER + i), 0);

    modifiers = read_byte(p, MODIFIERS);
    if (modifiers & 0x08) indicator(p, 0, 0x10);
    if (modifiers & 0x04) indicator(p, 0, 0x04);
    if (modifiers & 0x01) indicator(p, 1, 0x02);
    if (modifiers & 0x02) indicator(p, 2, 0x40);

    status = fx_result_classify_address(p, FIRST_SCALAR, 0, &result);
    if (status) return status;
    if (result.classification != 1) indicator(p, 1, 0x10);

    mode = read_byte(p, MODE);
    if (mode == 0xc4) {
        indicator(p, 4, 0x80);
        status = fx_result_classify_address(p, SECOND_SCALAR,
                                             result.continuation, &result);
        if (status) return status;
        if (result.classification != 1) indicator(p, 1, 0x10);
    }
    if (mode == 3) indicator(p, 3, 0x40);
    if (mode == 6) indicator(p, 5, 0x40);
    if (mode == 7) indicator(p, 5, 0x02);

    if (mode != 2) {
        value = read_byte(p, ANGLE_UNIT);
        if (value == 4) indicator(p, 7, 0x20);
        if (value == 5) indicator(p, 7, 0x02);
        if (value == 6) indicator(p, 8, 0x10);
        value = read_byte(p, DISPLAY_FORMAT);
        if (value == 8) indicator(p, 8, 0x01);
        if (value == 9) indicator(p, 9, 0x20);
    }
    if (read_byte(p, MATH_DISPLAY) && (mode & 0xc0)) indicator(p, 10, 0x40);

    value = read_byte(p, RESULT_STATE);
    if (value & 0x40) indicator(p, 11, 0x10);
    if (!(value & 0x80)) {
        value = read_byte(p, HISTORY_FLAGS);
        if (value & 0x01) indicator(p, 11, 0x80);
        if (value & 0x02) indicator(p, 10, 0x08);
        if (value & 0x04) indicator(p, 0, 0x40);
        if (value & 0x08) indicator(p, 11, 0x02);
    }

    for (i = 0; i < ROW_BYTES; ++i)
        fx_data_write(p, 0, (uint16_t)(LCD_ROW + i),
                      read_byte(p, (uint16_t)(ROW_BUFFER + i)));
    return 0;
}
